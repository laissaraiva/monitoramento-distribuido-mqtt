import argparse
import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import paho.mqtt.client as mqtt

from common.validation import PREFIXO_TOPICO, validar_mensagem_mqtt
from server.state import EstadoCentral, MetricaRecebida

HOST_PADRAO: str = "127.0.0.1"
PORTA_PADRAO: int = 1883
KEEPALIVE_PADRAO: int = 60
FILTRO_PADRAO: str = f"{PREFIXO_TOPICO}/+/+"
QOS: int = 0

INTERVALO_TABELA_PADRAO: float = 5.0
ARQUIVO_LOG_PADRAO: str = "monitor.log"
EVENTOS_EXIBIDOS: int = 6

LIMPAR_TELA: str = "\033[H\033[2J"

logger = logging.getLogger("monitor")
logger_mensagens = logging.getLogger("monitor.mensagens")


def formatar_metrica(id_maquina: str, metrica: str, leitura: MetricaRecebida) -> str:
    linha = (
        f"{leitura.timestamp} | {id_maquina} | {metrica:<7} | "
        f"{leitura.valor} {leitura.unidade}"
    )
    detalhes = leitura.detalhes or {}
    if "por_nucleo" in detalhes:
        linha += f" | núcleos: {detalhes['por_nucleo']}"
    if "total" in detalhes:
        linha += f" | total: {detalhes['total']} MB"
    if "livre" in detalhes:
        linha += f" | livre: {detalhes['livre']} MB"
    if "percentual" in detalhes:
        linha += f" | uso: {detalhes['percentual']}%"
    return linha


def formatar_idade(segundos: float) -> str:
    segundos = max(int(segundos), 0)
    if segundos < 60:
        return f"há {segundos}s"
    if segundos < 3600:
        return f"há {segundos // 60}m{segundos % 60:02d}s"
    return f"há {segundos // 3600}h{(segundos % 3600) // 60:02d}m"


def _texto_cpu(leitura: Optional[Dict[str, Any]]) -> str:
    if not leitura:
        return "-"
    return f"{leitura['valor']:.1f} {leitura['unidade']}"


def _texto_memoria(leitura: Optional[Dict[str, Any]]) -> str:
    if not leitura:
        return "-"
    texto = f"{leitura['valor']:.1f} {leitura['unidade']}"
    percentual = (leitura.get("detalhes") or {}).get("percentual")
    if percentual is not None:
        texto += f" ({percentual:.1f}%)"
    return texto


def _texto_atualizacao(ultima: Optional[datetime], agora: datetime) -> str:
    if ultima is None:
        return "-"
    return f"{ultima.strftime('%H:%M:%S')} ({formatar_idade((agora - ultima).total_seconds())})"


def formatar_tabela(linhas: List[Dict[str, Any]], agora: datetime) -> str:
    # linhas: resultado de EstadoCentral.snapshot()
    if not linhas:
        return "Nenhuma máquina registrada até o momento."

    cabecalho = ("MÁQUINA", "CPU", "RAM", "ÚLTIMA ATUALIZAÇÃO")
    corpo = [
        (
            linha["id_maquina"],
            _texto_cpu(linha["cpu"]),
            _texto_memoria(linha["memoria"]),
            _texto_atualizacao(linha["ultima_atualizacao"], agora),
        )
        for linha in linhas
    ]

    larguras = [
        max(len(cabecalho[i]), *(len(linha[i]) for linha in corpo))
        for i in range(len(cabecalho))
    ]

    def montar(colunas) -> str:
        return "  ".join(texto.ljust(larguras[i]) for i, texto in enumerate(colunas)).rstrip()

    separador = "  ".join("-" * largura for largura in larguras)
    return "\n".join([montar(cabecalho), separador, *(montar(linha) for linha in corpo)])


class HandlerEventos(logging.Handler):
    # Guarda os últimos eventos (conexão, desconexão, descartes) para exibir sob a tabela.
    # As mensagens recebidas ficam só no arquivo de log, senão ocupariam todo o painel.

    def __init__(self, capacidade: int = 50) -> None:
        super().__init__(level=logging.INFO)
        self._linhas: Deque[str] = deque(maxlen=capacidade)
        self.addFilter(lambda registro: not registro.name.startswith(logger_mensagens.name))
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, registro: logging.LogRecord) -> None:
        try:
            self._linhas.append(self.format(registro))
        except Exception:
            self.handleError(registro)

    def recentes(self, quantidade: int) -> List[str]:
        return list(self._linhas)[-quantidade:]


def _codigo_indica_falha(codigo: Any) -> bool:
    if hasattr(codigo, "is_failure"):
        return codigo.is_failure
    return codigo != 0


def _descrever_codigo(codigo: Any) -> str:
    if isinstance(codigo, int):
        return mqtt.connack_string(codigo)
    return str(codigo)


class MonitorCentral:
    def __init__(
        self,
        host: str = HOST_PADRAO,
        porta: int = PORTA_PADRAO,
        filtro: str = FILTRO_PADRAO,
        keepalive: int = KEEPALIVE_PADRAO,
        estado: Optional[EstadoCentral] = None,
        intervalo_tabela: float = INTERVALO_TABELA_PADRAO,
        eventos: Optional[HandlerEventos] = None,
    ) -> None:
        self.host = host
        self.porta = porta
        self.filtro = filtro
        self.keepalive = keepalive
        self.estado = estado or EstadoCentral()
        self.intervalo_tabela = intervalo_tabela
        self.eventos = eventos

        self.mensagens_recebidas = 0
        self.mensagens_descartadas = 0
        self.conectado = False

        self._executando = False
        self._cliente = self._criar_cliente()

    def _criar_cliente(self) -> mqtt.Client:
        id_cliente = "monitor-central"

        if hasattr(mqtt, "CallbackAPIVersion"):
            cliente = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=id_cliente,
            )
        else:
            cliente = mqtt.Client(client_id=id_cliente)

        cliente.on_connect = self._ao_conectar
        cliente.on_disconnect = self._ao_desconectar
        cliente.on_message = self._ao_receber

        cliente.reconnect_delay_set(min_delay=1, max_delay=30)
        return cliente

    def _ao_conectar(self, cliente, userdata, flags, codigo, *_args) -> None:
        if _codigo_indica_falha(codigo):
            self.conectado = False
            logger.error("Broker recusou a conexão: %s", _descrever_codigo(codigo))
            return
        self.conectado = True
        logger.info("Conectado ao broker %s:%d", self.host, self.porta)

        # Assinar aqui garante a reassinatura depois de uma reconexão
        resultado, _ = cliente.subscribe(self.filtro, qos=QOS)
        if resultado != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Falha ao assinar '%s': %s", self.filtro, mqtt.error_string(resultado))
            return
        logger.info("Assinatura ativa: %s (QoS %d)", self.filtro, QOS)

    def _ao_desconectar(self, cliente, userdata, *args) -> None:
        codigo = args[1] if len(args) >= 2 else (args[0] if args else 0)
        self.conectado = False
        if self._executando and _codigo_indica_falha(codigo):
            logger.warning(
                "Conexão com o broker perdida (%s). Tentando reconectar...",
                _descrever_codigo(codigo),
            )
        else:
            logger.info("Desconectado do broker.")

    def _ao_receber(self, cliente, userdata, msg) -> None:
        # Roda na thread de rede do paho: valida, atualiza o estado e registra no log.
        # A tabela é desenhada pela thread principal, então nada aqui espera por ela.
        self.mensagens_recebidas += 1

        validacao = validar_mensagem_mqtt(msg.topic, msg.payload)
        if not validacao.valido:
            self.mensagens_descartadas += 1
            logger.warning("Mensagem descartada em '%s': %s", msg.topic, validacao.erro)
            return

        id_maquina = validacao.dados["id_maquina"]
        metrica = validacao.dados["metrica"]
        try:
            maquina = self.estado.atualizar(id_maquina, metrica, validacao.dados["payload"])
        except ValueError as exc:
            self.mensagens_descartadas += 1
            logger.warning("Mensagem descartada em '%s': %s", msg.topic, exc)
            return

        logger_mensagens.info("%s", formatar_metrica(id_maquina, metrica, maquina.metricas[metrica]))

    def montar_tela(self, agora: Optional[datetime] = None) -> str:
        agora = agora or datetime.now().astimezone()
        linhas = self.estado.snapshot()

        situacao = "conectado" if self.conectado else "desconectado"
        partes = [
            f"Monitor central | broker {self.host}:{self.porta} ({situacao}) | filtro {self.filtro}",
            f"{agora.strftime('%d/%m/%Y %H:%M:%S')} | máquinas: {len(linhas)} | "
            f"mensagens: {self.mensagens_recebidas} recebidas, {self.mensagens_descartadas} descartadas",
            "",
            formatar_tabela(linhas, agora),
        ]

        recentes = self.eventos.recentes(EVENTOS_EXIBIDOS) if self.eventos else []
        if recentes:
            partes += ["", "Eventos recentes:", *(f"  {linha}" for linha in recentes)]
        return "\n".join(partes)

    def exibir_tabela(self, limpar: Optional[bool] = None) -> None:
        if limpar is None:
            limpar = sys.stdout.isatty()
        texto = self.montar_tela()
        sys.stdout.write((LIMPAR_TELA if limpar else "\n") + texto + "\n")
        sys.stdout.flush()

    def parar(self, *_args) -> None:
        if self._executando:
            logger.info("Encerrando o monitor...")
        self._executando = False

    def iniciar(self) -> None:
        self._executando = True
        logger.info("Monitor iniciado | broker %s:%d", self.host, self.porta)

        self._cliente.connect_async(self.host, self.porta, keepalive=self.keepalive)
        self._cliente.loop_start()

        try:
            proxima_exibicao = time.monotonic()
            while self._executando:
                if time.monotonic() >= proxima_exibicao:
                    self.exibir_tabela()
                    proxima_exibicao = time.monotonic() + self.intervalo_tabela
                time.sleep(min(0.2, max(proxima_exibicao - time.monotonic(), 0.01)))
        finally:
            self._executando = False
            self._cliente.disconnect()
            self._cliente.loop_stop()
            logger.info("Monitor finalizado.")
            print("\nÚltimo estado de cada máquina:")
            print(formatar_tabela(self.estado.snapshot(), datetime.now().astimezone()))


def configurar_logs(arquivo: Optional[str]) -> HandlerEventos:
    # Eventos de conexão e descartes vão para o painel da tabela e para o arquivo;
    # as mensagens recebidas vão só para o arquivo.
    eventos = HandlerEventos()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(eventos)

    if arquivo:
        handler_arquivo = logging.FileHandler(arquivo, encoding="utf-8")
        handler_arquivo.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler_arquivo)
    return eventos


def _habilitar_ansi_no_windows() -> None:
    if os.name == "nt":
        os.system("")


def _porta_valida(texto: str) -> int:
    try:
        valor = int(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"porta inválida: '{texto}'")
    if not 1 <= valor <= 65535:
        raise argparse.ArgumentTypeError("a porta deve estar entre 1 e 65535")
    return valor


def _intervalo_valido(texto: str) -> float:
    try:
        valor = float(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"intervalo inválido: '{texto}'")
    if valor <= 0:
        raise argparse.ArgumentTypeError("o intervalo deve ser maior que zero")
    return valor


def ler_argumentos(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor central que recebe métricas dos agentes via MQTT.",
    )
    parser.add_argument(
        "--host", default=HOST_PADRAO,
        help=f"endereço do broker MQTT (padrão: {HOST_PADRAO})",
    )
    parser.add_argument(
        "--porta", type=_porta_valida, default=PORTA_PADRAO,
        help=f"porta do broker MQTT (padrão: {PORTA_PADRAO})",
    )
    parser.add_argument(
        "--filtro", default=FILTRO_PADRAO,
        help=f"filtro de assinatura com wildcards (padrão: {FILTRO_PADRAO})",
    )
    parser.add_argument(
        "--keepalive", type=int, default=KEEPALIVE_PADRAO,
        help=f"keepalive MQTT em segundos (padrão: {KEEPALIVE_PADRAO})",
    )
    parser.add_argument(
        "--intervalo-tabela", type=_intervalo_valido, default=INTERVALO_TABELA_PADRAO,
        help=f"intervalo de atualização da tabela em segundos (padrão: {INTERVALO_TABELA_PADRAO:.0f})",
    )
    parser.add_argument(
        "--log", default=ARQUIVO_LOG_PADRAO, metavar="ARQUIVO",
        help=f"arquivo de log com conexões e mensagens recebidas (padrão: {ARQUIVO_LOG_PADRAO})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = ler_argumentos(argv)
    eventos = configurar_logs(args.log)
    _habilitar_ansi_no_windows()

    monitor = MonitorCentral(
        host=args.host,
        porta=args.porta,
        filtro=args.filtro,
        keepalive=args.keepalive,
        intervalo_tabela=args.intervalo_tabela,
        eventos=eventos,
    )

    signal.signal(signal.SIGINT, monitor.parar)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, monitor.parar)

    monitor.iniciar()
    return 0


if __name__ == "__main__":
    sys.exit(main())