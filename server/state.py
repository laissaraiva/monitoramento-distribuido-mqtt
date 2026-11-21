# Estado central das máquinas monitoradas (mantido em memória)

# É guardado, pra cada máquina (id_maquina), a ÚLTIMA métrica de
# cpu e a ÚLTIMA métrica de memoria recebidas, além da hora da última atualização

# Cada máquina tem sua entrada e dentro dela cada métrica tem sua chave. Atualizar cpu só troca metricas["cpu"]

import copy
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from common.validation import (
    CAMPOS_OBRIGATORIOS_PAYLOAD,
    METRICAS_SUPORTADAS,
    validar_id_maquina,
)

@dataclass
class MetricaRecebida:
    # Última leitura de uma métrica (cpu ou memoria) de uma máquina
    valor: float
    unidade: str

    # Hora informada pelo AGENTE (ISO 8601 com fuso)
    timestamp: str
    detalhes: Optional[Dict[str, Any]] = None

    # Hora em que o MONITOR recebeu a leitura (relógio do servidor)
    recebido_em: Optional[datetime] = None


@dataclass
class EstadoMaquina:
    id_maquina: str

    # Chave = nome da métrica ("cpu" ou "memoria"). 
    # Métrica que ainda não chegou nao tem chave (None)
    metricas: Dict[str, MetricaRecebida] = field(default_factory=dict)
    
    # Hora (relógio do servidor) da última métrica válida de qualquer tipo
    ultima_atualizacao: Optional[datetime] = None


class EstadoCentral:
    # Último estado conhecido de cada máquina, indexado por id_maquina

    def __init__(self) -> None:
        self._maquinas: Dict[str, EstadoMaquina] = {}
        self._lock = threading.RLock()

    def atualizar(
        self,
        id_maquina: str,
        metrica: str,
        payload: Dict[str, Any],
        recebido_em: Optional[datetime] = None,
    ) -> EstadoMaquina:
        # Registra a última leitura de metrica pra id_maquina
        
        # Validação e preparação, antes de pegar a trava
        if metrica not in METRICAS_SUPORTADAS:
            raise ValueError(f"Métrica não suportada: '{metrica}'.")

        resultado_id = validar_id_maquina(id_maquina)
        if not resultado_id.valido:
            raise ValueError(resultado_id.erro)

        if not isinstance(payload, dict):
            raise ValueError(
                f"Payload deve ser um dict, mas recebeu {type(payload).__name__}."
            )
        faltantes = sorted(CAMPOS_OBRIGATORIOS_PAYLOAD - set(payload))
        if faltantes:
            raise ValueError(
                f"Payload sem campos obrigatórios: {', '.join(faltantes)}."
            )

        # Hora de recebimento no monitor (não depende do relógio do agente)
        recebido_em = recebido_em or datetime.now().astimezone()

        leitura = MetricaRecebida(
            valor=payload["valor"],
            unidade=payload["unidade"],
            timestamp=payload["timestamp"],
            detalhes=copy.deepcopy(payload.get("detalhes")), # deepcopy pra não guardar referência ao dict do chamador
            recebido_em=recebido_em, 
        )

        # Busca a máquina, cria se não existir, grava a métrica
        with self._lock:
            maquina = self._maquinas.get(id_maquina)
            if maquina is None:
                maquina = EstadoMaquina(id_maquina=id_maquina)
                self._maquinas[id_maquina] = maquina

            # Só a chave dessa métrica é substituída
            maquina.metricas[metrica] = leitura
            maquina.ultima_atualizacao = recebido_em

            return copy.deepcopy(maquina)

    def obter(self, id_maquina: str) -> Optional[EstadoMaquina]:
        #Cópia do estado de uma máquina, ou None se ela é desconhecida
        with self._lock:
            maquina = self._maquinas.get(id_maquina)
            return copy.deepcopy(maquina) if maquina else None

    def obter_metrica(
        self, id_maquina: str, metrica: str
    ) -> Optional[MetricaRecebida]:
        # Cópia da última leitura de uma métrica, ou None se não existe
        with self._lock:
            maquina = self._maquinas.get(id_maquina)
            if maquina is None:
                return None
            leitura = maquina.metricas.get(metrica)
            return copy.deepcopy(leitura) if leitura else None

    def listar(self) -> List[EstadoMaquina]:
        # Cópias de todas as máquinas, ordenadas por id_maquina
        with self._lock:
            return [copy.deepcopy(self._maquinas[i]) for i in sorted(self._maquinas)]

    def total_maquinas(self) -> int:
        #Quantidade de máquinas conhecidas
        with self._lock:
            return len(self._maquinas)
