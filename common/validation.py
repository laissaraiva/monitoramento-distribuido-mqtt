# Módulo de validação do protocolo de comunicação MQTT

# Implementa todas as regras definidas em docs/protocol.md com portabilidade
# entre os ambientes dos agentes (publishers) e do monitor central (subscriber)

from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import re
from typing import Any, Dict, Optional, Union

# CONSTANTES DO PROTOCOLO (definidas em docs/architecture.md e docs/protocol.md)
PREFIXO_TOPICO: str = "monitoramento"
METRICAS_SUPORTADAS = frozenset({"cpu", "memoria"})

UNIDADES_POR_METRICA: Dict[str, str] = {
    "cpu": "%",
    "memoria": "MB",
}

CAMPOS_OBRIGATORIOS_PAYLOAD = frozenset({"valor", "unidade", "timestamp"})
CAMPOS_PERMITIDOS_PAYLOAD = frozenset({"valor", "unidade", "timestamp", "detalhes"})
CAMPOS_DETALHES_CPU = frozenset({"por_nucleo"})
CAMPOS_DETALHES_MEMORIA = frozenset({"total", "livre", "percentual"})

# Regex oficial para id_maquina:
# - Deve começar com caractere alfanumérico: [a-zA-Z0-9]
# - Pode conter de 0 a 62 caracteres intermediários: [a-zA-Z0-9_-]
# - Deve terminar com caractere alfanumérico: [a-zA-Z0-9]
# - Resultado é comprimento total entre 2 e 64 caracteres
REGEX_ID_MAQUINA = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}[a-zA-Z0-9]$")


# ESTRUTURAS DE RETORNO E EXCEÇÃO
class ErroValidacaoProtocolo(ValueError):
    """Exceção lançada quando uma mensagem viola o contrato do protocolo MQTT."""

@dataclass(frozen=True)
class ResultadoValidacao:
    # Desfecho de qualquer operação de validação

    # Por que usar um objeto de resultado em vez de apenas retornar bool?
    # - Permite que o subscriber registre o motivo exato da rejeição no log sem precisar capturar exceções a cada pacote recebido
    # - Transporta em dados os valores já extraídos e normalizados (ex: id_maquina, metrica, datetime convertido), evitando reprocessamento
    
    valido: bool
    erro: Optional[str] = None
    dados: Dict[str, Any] = field(default_factory=dict)


# FUNÇÕES AUXILIARES INTERNAS
def _eh_numero_valido(valor: Any) -> bool:
    # Verifica se valor é um número finito (int ou float)    
    if isinstance(valor, bool): # Em Python a classe bool herda de int (issubclass(bool, int) == True)
        return False            # isinstance(True, int) retorna True! se não bloquar bool
    if not isinstance(valor, (int, float)):
        return False
    if math.isnan(valor) or math.isinf(valor): # bloqueia NaN e Infinity - aceitos pelo parser JSON padrão do Python, mas são inválidos na especificação JSON (RFC 8259)
        return False
    return True

def _rejeitar_constante_json(constante: str) -> None:
    # Callback para `json.loads(..., parse_constant=...)` bloquear NaN/Infinity
    raise ValueError(f"Constante numérica não permitida em JSON: '{constante}'.")


# VALIDADORES DE IDENTIFICADOR, TÓPICO E TIMESTAMP
def validar_id_maquina(id_maquina: Any) -> ResultadoValidacao:
    # Valida o identificador de uma máquina monitorada (id_maquina)

    # Deve ser string (str) não vazia;
    if not isinstance(id_maquina, str): 
        return ResultadoValidacao(
            valido=False,
            erro=f"id_maquina deve ser string, mas recebeu {type(id_maquina).__name__}.",
        )

    # Não pode conter curingas MQTT (+, #), separador (/) ou espaços;
    if not id_maquina:
        return ResultadoValidacao(
            valido=False,
            erro="id_maquina não pode ser uma string vazia.",
        )

    # Verificações explícitas antes do regex para gerar mensagens didáticas
    if any(caractere in id_maquina for caractere in ("+", "#", "/")):
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"id_maquina '{id_maquina}' contém caracteres reservados do MQTT "
                "('+', '#' ou '/')."
            ),
        )

    if any(caractere.isspace() for caractere in id_maquina):
        return ResultadoValidacao(
            valido=False,
            erro=f"id_maquina '{id_maquina}' não pode conter espaços em branco.",
        )

    # Deve ter entre 2 e 64 caracteres, iniciando e terminando com alfanumérico
    if not REGEX_ID_MAQUINA.match(id_maquina):
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"id_maquina '{id_maquina}' inválido. Deve ter entre 2 e 64 caracteres "
                "(letras ASCII, números, '-' ou '_'), iniciando e terminando com "
                "caractere alfanumérico."
            ),
        )

    return ResultadoValidacao(
        valido=True,
        dados={"id_maquina": id_maquina},
    )


def validar_topico(topico: Any) -> ResultadoValidacao:
    # Valida um tópico concreto de publicação MQTT e extrai seus componentes

    # Formato esperado: monitoramento/<id_maquina>/<metrica>
    
    if not isinstance(topico, str) or not topico:
        return ResultadoValidacao(
            valido=False,
            erro="O tópico MQTT deve ser uma string não vazia.",
        )

    if "+" in topico or "#" in topico:
        return ResultadoValidacao(
            valido=False,
            erro=f"Tópico publicado '{topico}' não pode conter wildcards MQTT ('+' ou '#').", # são válidos apenas em filtros de assinatura (SUBSCRIBE)
        )

    partes = topico.split("/")
    if len(partes) != 3:
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Tópico '{topico}' deve possuir exatamente 3 níveis no formato "
                f"'{PREFIXO_TOPICO}/<id_maquina>/<metrica>' (encontrados {len(partes)} níveis)."
            ),
        )

    prefixo, id_maquina, metrica = partes

    if prefixo != PREFIXO_TOPICO:
        return ResultadoValidacao(
            valido=False,
            erro=f"Prefixo de tópico inválido: esperado '{PREFIXO_TOPICO}', recebido '{prefixo}'.",
        )

    resultado_id = validar_id_maquina(id_maquina)
    if not resultado_id.valido:
        return ResultadoValidacao(
            valido=False,
            erro=f"Tópico '{topico}' possui id_maquina inválido: {resultado_id.erro}",
        )

    if metrica not in METRICAS_SUPORTADAS:
        metricas_ordenadas = ", ".join(sorted(METRICAS_SUPORTADAS))
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Métrica '{metrica}' não suportada no tópico '{topico}'. "
                f"Valores aceitos: {metricas_ordenadas}."
            ),
        )

    return ResultadoValidacao(
        valido=True,
        dados={
            "topico": topico,
            "prefixo": prefixo,
            "id_maquina": id_maquina,
            "metrica": metrica,
        },
    )


def validar_timestamp(timestamp: Any) -> ResultadoValidacao:
    # Valida se timestamp é uma string ISO 8601 completa com fuso horário

    # Exemplos aceitos:
    # - "2026-11-16T22:00:00-03:00"
    # - "2026-11-17T01:00:00Z"

    # Exemplos rejeitados:
    # - "2026-11-16T22:00:00" (sem fuso horário — ambíguo entre máquinas)
    # - "2026-11-16" (só data, sem horário)
    # - "16/11/2026 22:00:00" (fora do padrão ISO 8601)
   
    if not isinstance(timestamp, str) or not timestamp:
        return ResultadoValidacao(
            valido=False,
            erro="O campo 'timestamp' deve ser uma string não vazia no padrão ISO 8601.",
        )

    if timestamp != timestamp.strip():
        return ResultadoValidacao(
            valido=False,
            erro="O campo 'timestamp' não pode conter espaços no início ou no fim.",
        )

    # Garante que contém separador de hora ('T' ou 't'), rejeitando strings só com data
    if "T" not in timestamp.upper():
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Timestamp '{timestamp}' inválido: deve incluir data e hora "
                "separados por 'T' (ex.: '2026-11-16T22:00:00-03:00')."
            ),
        )

    # Normaliza o sufixo UTC 'Z'/'z' para '+00:00' para manter compatibilidade tanto com Python 3.9/3.10 quanto com Python 3.11+
    timestamp_normalizado = (
        f"{timestamp[:-1]}+00:00" if timestamp[-1] in ("Z", "z") else timestamp
    )

    try:
        dt = datetime.fromisoformat(timestamp_normalizado)
    except ValueError:
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Timestamp '{timestamp}' não está no formato ISO 8601 válido "
                "(ex.: '2026-11-16T22:00:00-03:00')."
            ),
        )

    # Exige objeto timezone-aware (offset explícito)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Timestamp '{timestamp}' deve informar o fuso horário "
                "(ex.: '-03:00' ou 'Z')."
            ),
        )

    return ResultadoValidacao(
        valido=True,
        dados={
            "timestamp_iso": timestamp,
            "datetime": dt,
        },
    )

# VALIDADORES DE PAYLOAD (BASE, CPU E MEMÓRIA RAM)
def _validar_estrutura_base_payload(payload: Any, metrica: str) -> ResultadoValidacao:
    # Valida a estrutura comum a qualquer payload de métrica (CPU ou Memória)
    
    # Checa se payload é um dicionário JSON (dict)
    if not isinstance(payload, dict):
        return ResultadoValidacao(
            valido=False,
            erro=f"Payload deve ser um objeto JSON (dict), mas recebeu {type(payload).__name__}.",
        )

    # Checa se todos os campos obrigatórios (valor, unidade, timestamp) estão presentes
    campos_presentes = set(payload.keys())
    campos_faltantes = sorted(CAMPOS_OBRIGATORIOS_PAYLOAD - campos_presentes)
    if campos_faltantes:
        return ResultadoValidacao(
            valido=False,
            erro=f"Campos obrigatórios ausentes no payload: {', '.join(campos_faltantes)}.",
        )

    # Checa se não existem campos desconhecidos na raiz do payload
    campos_desconhecidos = sorted(campos_presentes - CAMPOS_PERMITIDOS_PAYLOAD)
    if campos_desconhecidos:
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Campos não permitidos na raiz do payload: {', '.join(campos_desconhecidos)}. "
                "Campos aceitos: valor, unidade, timestamp, detalhes."
            ),
        )

    # Checa se valor é numérico finito, unidade corresponde à métrica e timestamp é ISO 8601
    valor = payload["valor"]
    if not _eh_numero_valido(valor):
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Campo 'valor' deve ser numérico finito (int ou float), "
                f"mas recebeu {type(valor).__name__} ({valor!r})."
            ),
        )

    unidade = payload["unidade"]
    unidade_esperada = UNIDADES_POR_METRICA[metrica]
    if not isinstance(unidade, str) or unidade != unidade_esperada:
        return ResultadoValidacao(
            valido=False,
            erro=(
                f"Unidade inválida para a métrica '{metrica}': "
                f"esperado '{unidade_esperada}', recebido {unidade!r}."
            ),
        )

    resultado_ts = validar_timestamp(payload["timestamp"])
    if not resultado_ts.valido:
        return ResultadoValidacao(
            valido=False,
            erro=resultado_ts.erro,
        )

    return ResultadoValidacao(
        valido=True,
        dados={
            "payload": payload,
            "datetime": resultado_ts.dados["datetime"],
        },
    )


def validar_payload_cpu(payload: Any) -> ResultadoValidacao:
    # Valida um dicionário de payload para a métrica cpu

    # Regras de CPU:
    # - unidade deve ser "%"
    # - 0.0 <= valor <= 100.0
    # - Se detalhes estiver presente, deve ser um dict contendo opcionalmente por_nucleo (lista não vazia de números entre 0.0 e 100.0)
    base = _validar_estrutura_base_payload(payload, metrica="cpu")
    if not base.valido:
        return base

    valor_cpu = float(payload["valor"])
    if not (0.0 <= valor_cpu <= 100.0):
        return ResultadoValidacao(
            valido=False,
            erro=f"Valor de CPU fora da faixa válida [0.0, 100.0]: recebido {valor_cpu}.",
        )

    if "detalhes" in payload and payload["detalhes"] is not None:
        detalhes = payload["detalhes"]
        if not isinstance(detalhes, dict):
            return ResultadoValidacao(
                valido=False,
                erro=f"Campo 'detalhes' deve ser um objeto JSON, mas recebeu {type(detalhes).__name__}.",
            )

        chaves_invalidas = sorted(set(detalhes.keys()) - CAMPOS_DETALHES_CPU)
        if chaves_invalidas:
            return ResultadoValidacao(
                valido=False,
                erro=(
                    f"Campos não permitidos em 'detalhes' para CPU: {', '.join(chaves_invalidas)}. "
                    "Campos aceitos: por_nucleo."
                ),
            )

        if "por_nucleo" in detalhes and detalhes["por_nucleo"] is not None:
            por_nucleo = detalhes["por_nucleo"]
            if not isinstance(por_nucleo, list) or len(por_nucleo) == 0:
                return ResultadoValidacao(
                    valido=False,
                    erro="Campo 'detalhes.por_nucleo' deve ser uma lista não vazia de percentuais.",
                )

            for indice, uso_nucleo in enumerate(por_nucleo):
                if not _eh_numero_valido(uso_nucleo):
                    return ResultadoValidacao(
                        valido=False,
                        erro=(
                            f"Elemento 'detalhes.por_nucleo[{indice}]' deve ser numérico, "
                            f"mas recebeu {type(uso_nucleo).__name__} ({uso_nucleo!r})."
                        ),
                    )
                if not (0.0 <= float(uso_nucleo) <= 100.0):
                    return ResultadoValidacao(
                        valido=False,
                        erro=(
                            f"Elemento 'detalhes.por_nucleo[{indice}]' ({uso_nucleo}) "
                            "fora da faixa válida [0.0, 100.0]."
                        ),
                    )

    return ResultadoValidacao(
        valido=True,
        dados=base.dados,
    )

