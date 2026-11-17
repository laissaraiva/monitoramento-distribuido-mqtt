import copy
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from common.validation import METRICAS_SUPORTADAS


@dataclass
class MetricaRecebida:
    valor: float
    unidade: str
    timestamp: str
    detalhes: Optional[Dict[str, Any]] = None


@dataclass
class EstadoMaquina:
    id_maquina: str
    metricas: Dict[str, MetricaRecebida] = field(default_factory=dict)
    ultima_atualizacao: Optional[datetime] = None


class EstadoCentral:
    """Último estado conhecido de cada máquina, indexado por id_maquina.

    O callback do MQTT roda em outra thread, por isso o acesso é protegido
    por lock e as leituras devolvem cópias.
    """

    def __init__(self) -> None:
        self._maquinas: Dict[str, EstadoMaquina] = {}
        self._lock = threading.Lock()

    def atualizar(
        self,
        id_maquina: str,
        metrica: str,
        payload: Dict[str, Any],
        recebido_em: Optional[datetime] = None,
    ) -> EstadoMaquina:
        if metrica not in METRICAS_SUPORTADAS:
            raise ValueError(f"Métrica não suportada: '{metrica}'.")

        leitura = MetricaRecebida(
            valor=payload["valor"],
            unidade=payload["unidade"],
            timestamp=payload["timestamp"],
            detalhes=payload.get("detalhes"),
        )
        # Horário de recebimento no monitor, para não depender do relógio do agente
        recebido_em = recebido_em or datetime.now().astimezone()

        with self._lock:
            maquina = self._maquinas.get(id_maquina)
            if maquina is None:
                maquina = EstadoMaquina(id_maquina=id_maquina)
                self._maquinas[id_maquina] = maquina
            maquina.metricas[metrica] = leitura
            maquina.ultima_atualizacao = recebido_em
            return copy.deepcopy(maquina)

    def obter(self, id_maquina: str) -> Optional[EstadoMaquina]:
        with self._lock:
            maquina = self._maquinas.get(id_maquina)
            return copy.deepcopy(maquina) if maquina else None

    def listar(self) -> List[EstadoMaquina]:
        with self._lock:
            return [copy.deepcopy(self._maquinas[i]) for i in sorted(self._maquinas)]