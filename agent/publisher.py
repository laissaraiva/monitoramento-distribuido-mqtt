import argparse
import json
import logging
import re
import signal
import socket
import sys
import time
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

from agent.collector import ErroColeta, coletar_cpu, coletar_memoria, timestamp_atual
from common.validation import (
    PREFIXO_TOPICO,
    UNIDADES_POR_METRICA,
    validar_id_maquina,
    validar_mensagem_mqtt,
)

HOST_PADRAO: str = "127.0.0.1"
PORTA_PADRAO: int = 1883
INTERVALO_PADRAO: float = 5.0
KEEPALIVE_PADRAO: int = 60
QOS: int = 0
INTERVALO_MINIMO: float = 1.0

logger = logging.getLogger("agente")


def id_maquina_padrao() -> str:
    nome = socket.gethostname().split(".")[0]
    nome = re.sub(r"[^a-zA-Z0-9_-]", "-", nome)[:64].strip("-_")
    return nome if validar_id_maquina(nome).valido else "maquina01"


def montar_topico(id_maquina: str, metrica: str) -> str:
    return f"{PREFIXO_TOPICO}/{id_maquina}/{metrica}"


def montar_payload_cpu(cpu: Dict[str, Any], timestamp: str) -> Dict[str, Any]:
    return {
        "valor": cpu["percentual"],
        "unidade": UNIDADES_POR_METRICA["cpu"],
        "timestamp": timestamp,
        "detalhes": {
            "por_nucleo": cpu["por_nucleo"],
        },
    }


def montar_payload_memoria(memoria: Dict[str, float], timestamp: str) -> Dict[str, Any]:
    return {
        "valor": memoria["utilizada"],
        "unidade": UNIDADES_POR_METRICA["memoria"],
        "timestamp": timestamp,
        "detalhes": {
            "total": memoria["total"],
            "livre": memoria["livre"],
            "percentual": memoria["percentual"],
        },
    }


class AgenteMonitoramento:
    def __init__(
        self,
        id_maquina: str,
        host: str = HOST_PADRAO,
        porta: int = PORTA_PADRAO,
        intervalo: float = INTERVALO_PADRAO,
        keepalive: int = KEEPALIVE_PADRAO,
    ) -> None:
        self.id_maquina = id_maquina
        self.host = host
        self.porta = porta
        self.intervalo = intervalo
        self.keepalive = keepalive

        self.topico_cpu = montar_topico(id_maquina, "cpu")
        self.topico_memoria = montar_topico(id_maquina, "memoria")

        self._executando = False
        self._cliente = self._criar_cliente()

    def _criar_cliente(self) -> mqtt.Client:
        id_cliente = f"agente-{self.id_maquina}"

        if hasattr(mqtt, "CallbackAPIVersion"):
            cliente = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=id_cliente,
            )
        else:
            cliente = mqtt.Client(client_id=id_cliente)

        cliente.on_connect = self._ao_conectar
        cliente.on_disconnect = self._ao_desconectar

        cliente.reconnect_delay_set(min_delay=1, max_delay=30)
        return cliente

    def _ao_conectar(self, cliente, userdata, flags, codigo, *_args) -> None:
        if _codigo_indica_falha(codigo):
            logger.error("Broker recusou a conexão: %s", _descrever_codigo(codigo))
            return
        logger.info("Conectado ao broker %s:%d", self.host, self.porta)

    def _ao_desconectar(self, cliente, userdata, *args) -> None:
        codigo = args[1] if len(args) >= 2 else (args[0] if args else 0)
        if not self._executando:
            logger.info("Desconectado do broker.")
        elif _codigo_indica_falha(codigo):
            logger.warning(
                "Conexão com o broker perdida (%s). Tentando reconectar...",
                _descrever_codigo(codigo),
            )

    def publicar(self, topico: str, payload: Dict[str, Any]) -> bool:
        validacao = validar_mensagem_mqtt(topico, payload)
        if not validacao.valido:
            logger.error("Mensagem descartada (fora do protocolo): %s", validacao.erro)
            return False

        if not self._cliente.is_connected():
            logger.warning("Sem conexão com o broker. Leitura de %s descartada.", topico)
            return False

        mensagem = json.dumps(payload, ensure_ascii=False)
        try:
            info = self._cliente.publish(topico, mensagem, qos=QOS, retain=False)
        except (ValueError, OSError) as exc:
            logger.error("Erro ao publicar em %s: %s", topico, exc)
            return False

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Falha ao publicar em %s: %s", topico, mqtt.error_string(info.rc))
            return False

        logger.info("Publicado em %s: %s", topico, mensagem)
        return True

    def executar_ciclo(self) -> None:
        try:
            cpu = coletar_cpu()
            self.publicar(self.topico_cpu, montar_payload_cpu(cpu, timestamp_atual()))
        except ErroColeta as exc:
            logger.error("%s", exc)

        try:
            memoria = coletar_memoria()
            self.publicar(self.topico_memoria, montar_payload_memoria(memoria, timestamp_atual()))
        except ErroColeta as exc:
            logger.error("%s", exc)

    def _aguardar(self, segundos: float) -> None:
        limite = time.monotonic() + segundos
        while self._executando:
            restante = limite - time.monotonic()
            if restante <= 0:
                break
            time.sleep(min(restante, 0.5))

    def _aguardar_conexao(self, tempo_maximo: float) -> bool:
        limite = time.monotonic() + tempo_maximo
        while self._executando and time.monotonic() < limite:
            if self._cliente.is_connected():
                return True
            time.sleep(0.1)
        return self._cliente.is_connected()

    def parar(self, *_args) -> None:
        if self._executando:
            logger.info("Encerrando o agente...")
        self._executando = False

    def iniciar(self) -> None:
        self._executando = True
        logger.info(
            "Agente '%s' iniciado | broker %s:%d | intervalo %.1fs | QoS %d",
            self.id_maquina, self.host, self.porta, self.intervalo, QOS,
        )
        logger.info("Tópicos: %s e %s", self.topico_cpu, self.topico_memoria)

        self._cliente.connect_async(self.host, self.porta, keepalive=self.keepalive)
        self._cliente.loop_start()

        try:
            if not self._aguardar_conexao(tempo_maximo=10):
                if self._executando:
                    logger.warning(
                        "Não foi possível conectar a %s:%d. Verifique se o Mosquitto está "
                        "em execução. Novas tentativas serão feitas automaticamente.",
                        self.host, self.porta,
                    )

            while self._executando:
                inicio = time.monotonic()
                self.executar_ciclo()
                self._aguardar(self.intervalo - (time.monotonic() - inicio))
        finally:
            self._executando = False
            self._cliente.disconnect()
            self._cliente.loop_stop()
            logger.info("Agente finalizado.")


def _codigo_indica_falha(codigo: Any) -> bool:
    if hasattr(codigo, "is_failure"):
        return codigo.is_failure
    return codigo != 0


def _descrever_codigo(codigo: Any) -> str:
    if isinstance(codigo, int):
        return mqtt.connack_string(codigo)
    return str(codigo)


def _intervalo_valido(texto: str) -> float:
    try:
        valor = float(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"intervalo inválido: '{texto}'")
    if valor < INTERVALO_MINIMO:
        raise argparse.ArgumentTypeError(
            f"o intervalo deve ser de pelo menos {INTERVALO_MINIMO:.0f} segundo(s)"
        )
    return valor


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
        description="Agente que publica métricas de CPU e memória RAM via MQTT.",
    )
    parser.add_argument(
        "--id", dest="id_maquina", default=None,
        help="identificador da máquina usado no tópico (padrão: hostname)",
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
        "--intervalo", type=_intervalo_valido, default=INTERVALO_PADRAO,
        help=f"intervalo entre publicações em segundos (padrão: {INTERVALO_PADRAO:.0f})",
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

    id_maquina = args.id_maquina or id_maquina_padrao()
    resultado_id = validar_id_maquina(id_maquina)
    if not resultado_id.valido:
        logger.error("%s", resultado_id.erro)
        return 2

    agente = AgenteMonitoramento(
        id_maquina=id_maquina,
        host=args.host,
        porta=args.porta,
        intervalo=args.intervalo,
        keepalive=args.keepalive,
    )

    signal.signal(signal.SIGINT, agente.parar)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, agente.parar)

    agente.iniciar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
