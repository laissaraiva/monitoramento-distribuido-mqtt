# Módulo de validação do protocolo de comunicação MQTT

# Implementa todas as regras definidas em `docs/protocol.md` com portabilidade
# entre os ambientes dos agentes (publishers) e do monitor central (subscriber)

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Any, Dict, Optional

# CONSTANTES DO PROTOCOLO (definidas em docs/architecture.md e docs/protocol.md)
PREFIXO_TOPICO: str = "monitoramento"
METRICAS_SUPORTADAS = frozenset({"cpu", "memoria"})

UNIDADES_POR_METRICA: Dict[str, str] = {
    "cpu": "%",
    "memoria": "MB",
}

# Regex oficial para `id_maquina`:
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

    # Por que usar um objeto de resultado em vez de apenas retornar `bool`?
    # - Permite que o subscriber registre o motivo exato da rejeição no log sem precisar capturar exceções a cada pacote recebido
    # - Transporta em `dados` os valores já extraídos e normalizados (ex: `id_maquina`, `metrica`, `datetime` convertido), evitando reprocessamento
    
    valido: bool
    erro: Optional[str] = None
    dados: Dict[str, Any] = field(default_factory=dict)


# FUNÇÕES AUXILIARES INTERNAS
def _eh_numero_valido(valor: Any) -> bool:
    # Verifica se `valor` é um número finito (`int` ou `float`)    
    if isinstance(valor, bool): # Em Python a classe `bool` herda de `int` (`issubclass(bool, int) == True`)
        return False            # `isinstance(True, int)` retorna `True`! se não bloquar `bool`
    if not isinstance(valor, (int, float)):
        return False
    if math.isnan(valor) or math.isinf(valor): # bloqueia `NaN` e `Infinity` - aceitos pelo parser JSON padrão do Python, mas são inválidos na especificação JSON (RFC 8259)
        return False
    return True


# VALIDADORES DE IDENTIFICADOR, TÓPICO E TIMESTAMP
def validar_id_maquina(id_maquina: Any) -> ResultadoValidacao:
    # Valida o identificador de uma máquina monitorada (`id_maquina`)

    # Deve ser string (`str`) não vazia;
    if not isinstance(id_maquina, str): 
        return ResultadoValidacao(
            valido=False,
            erro=f"id_maquina deve ser string, mas recebeu {type(id_maquina).__name__}.",
        )

    # Não pode conter curingas MQTT (`+`, `#`), separador (`/`) ou espaços;
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

    # Formato esperado: `monitoramento/<id_maquina>/<metrica>`
    
    if not isinstance(topico, str) or not topico:
        return ResultadoValidacao(
            valido=False,
            erro="O tópico MQTT deve ser uma string não vazia.",
        )

    if "+" in topico or "#" in topico:
        return ResultadoValidacao(
            valido=False,
            erro=f"Tópico publicado '{topico}' não pode conter wildcards MQTT ('+' ou '#').", # são válidos apenas em filtros de assinatura (`SUBSCRIBE`)
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

