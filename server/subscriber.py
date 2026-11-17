import argparse
import logging
import signal
import sys
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt

from common.validation import PREFIXO_TOPICO, validar_mensagem_mqtt
from server.state import EstadoCentral, EstadoMaquina, MetricaRecebida

HOST_PADRAO: str = "127.0.0.1"
PORTA_PADRAO: int = 1883
KEEPALIVE_PADRAO: int = 60
FILTRO_PADRAO: str = f"{PREFIXO_TOPICO}/+/+"
QOS: int = 0

logger = logging.getLogger("monitor")


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


def formatar_resumo(maquinas: list) -> str:
    if not maquinas:
        return "Nenhuma máquina registrada."

    linhas = []
    for m in maquinas:
        cpu = m.metricas.get("cpu")
        mem = m.metricas.get("memoria")
        linhas.append(
            f"{m.id_maquina:<20} "
            f"CPU: {f'{cpu.valor} {cpu.unidade}' if cpu else '-':<10} "
            f"RAM: {f'{mem.valor} {mem.unidade}' if mem else '-':<14} "
            f"atualizado em {m.ultima_atualizacao.isoformat(timespec='seconds')}"
        )
    return "\n".join(linhas)


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
    ) -> None:
        self.host = host
        self.porta = porta
        self.filtro = filtro
        self.keepalive = keepalive
        self.estado = estado or EstadoCentral()

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
            logger.error("Broker recusou a conexão: %s", _descrever_codigo(codigo))
            return
        logger.info("Conectado ao broker %s:%d", self.host, self.porta)

        # Assinar aqui garante a reassinatura depois de uma reconexão
        resultado, _ = cliente.subscribe(self.filtro, qos=QOS)
        if resultado != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Falha ao assinar '%s': %s", self.filtro, mqtt.error_string(resultado))
            return
        logger.info("Assinatura ativa: %s (QoS %d)", self.filtro, QOS)

    def _ao_desconectar(self, cliente, userdata, *args) -> None:
        codigo = args[1] if len(args) >= 2 else (args[0] if args else 0)
        if not self._executando:
            logger.info("Desconectado do broker.")
        elif _codigo_indica_falha(codigo):
            logger.warning(
                "Conexão com o broker perdida (%s). Tentando reconectar...",
                _descrever_codigo(codigo),
            )

    def _ao_receber(self, cliente, userdata, msg) -> None:
        validacao = validar_mensagem_mqtt(msg.topic, msg.payload)
        if not validacao.valido:
            logger.warning("Mensagem descartada em '%s': %s", msg.topic, validacao.erro)
            return

        id_maquina = validacao.dados["id_maquina"]
        metrica = validacao.dados["metrica"]
        self.estado.atualizar(id_maquina, metrica, validacao.dados["payload"])

        leitura = self.estado.obter(id_maquina).metricas[metrica]
        print(formatar_metrica(id_maquina, metrica, leitura), flush=True)

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
            while self._executando:
                time.sleep(0.5)
        finally:
            self._executando = False
            self._cliente.disconnect()
            self._cliente.loop_stop()
            print("\nÚltimo estado de cada máquina:")
            print(formatar_resumo(self.estado.listar()))
            logger.info("Monitor finalizado.")


def _porta_valida(texto: str) -> int:
    try:
        valor = int(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"porta inválida: '{texto}'")
    if not 1 <= valor <= 65535:
        raise argparse.ArgumentTypeError("a porta deve estar entre 1 e 65535")
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
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    args = ler_argumentos(argv)

    monitor = MonitorCentral(
        host=args.host,
        porta=args.porta,
        filtro=args.filtro,
        keepalive=args.keepalive,
    )

    signal.signal(signal.SIGINT, monitor.parar)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, monitor.parar)

    monitor.iniciar()
    return 0


if __name__ == "__main__":
    sys.exit(main())