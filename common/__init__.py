# Pacote compartilhado (common) do sistema de monitoramento distribuído via MQTT

# Ele centraliza o contrato de comunicação e as regras de validação utilizadas tanto 
# pelo agente (publisher) quanto pelo monitor central (subscriber)

from common.validation import (
    ErroValidacaoProtocolo,
    METRICAS_SUPORTADAS,
    PREFIXO_TOPICO,
    UNIDADES_POR_METRICA,
    ResultadoValidacao,
    validar_id_maquina,
    validar_mensagem_mqtt,
    validar_payload_cpu,
    validar_payload_memoria,
    validar_timestamp,
    validar_topico,
)

__all__ = [
    "ErroValidacaoProtocolo",
    "METRICAS_SUPORTADAS",
    "PREFIXO_TOPICO",
    "UNIDADES_POR_METRICA",
    "ResultadoValidacao",
    "validar_id_maquina",
    "validar_mensagem_mqtt",
    "validar_payload_cpu",
    "validar_payload_memoria",
    "validar_timestamp",
    "validar_topico",
]