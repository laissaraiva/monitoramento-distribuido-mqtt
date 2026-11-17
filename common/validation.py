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


