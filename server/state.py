# Estado central das máquinas monitoradas (mantido em memória)

# É guardado, pra cada máquina (id_maquina), a última métrica de
# cpu e a última métrica de memoria recebidas, além da hora da última atualização

# Cada máquina tem sua entrada e dentro dela cada métrica tem sua chave. Atualizar cpu só troca metricas["cpu"]

import copy
import logging
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from common.validation import (
    CAMPOS_OBRIGATORIOS_PAYLOAD,
    METRICAS_SUPORTADAS,
    validar_id_maquina,
)

logger = logging.getLogger("monitor.estado")

# constantes do dashboard
# Tempo (s) sem receber leitura de uma máquina até ela ser considerada indisponível
TIMEOUT_AGENTE_PADRAO: float = 15.0 # 15 s = 3x o intervalo padrão de publicação do agente (5 s)

# Quantidade máxima de pontos guardados por máquina e métrica (120 pontos a 5 s = ~10 min)
HISTORICO_MAXIMO: int = 120

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

    def __init__(
        self,
        timeout_agente: float = TIMEOUT_AGENTE_PADRAO,
        historico_maximo: int = HISTORICO_MAXIMO,
    ) -> None:
        # os dois parâmetros têm padrão, então EstadoCentral() continua valendo pros testes e pro monitor atuais
        if (
            isinstance(timeout_agente, bool)
            or not isinstance(timeout_agente, (int, float))
            or not (timeout_agente > 0)
        ):
            raise ValueError(
                f"O timeout de indisponibilidade deve ser um número maior que zero, mas recebeu {timeout_agente!r}."
            )
        if (
            isinstance(historico_maximo, bool)
            or not isinstance(historico_maximo, int)
            or historico_maximo < 1
        ):
            raise ValueError(
                f"O tamanho máximo do histórico deve ser um inteiro maior ou igual a 1, mas recebeu {historico_maximo!r}."
            )

        self._maquinas: Dict[str, EstadoMaquina] = {}
        self._lock = threading.RLock()

        # usado pra decidir se uma máquina está indisponível (calculado ao montar o dashboard)
        self._timeout_agente: float = float(timeout_agente)
        self._historico_maximo: int = historico_maximo

        # histórico de cada métrica por máquina, indexado por (id_maquina, metrica)
        # Cada deque guarda no máximo historico_maximo pontos: {"t": ISO 8601, "valor": percentual}
        # Quando enche, o ponto mais antigo sai sozinho
        self._historico: Dict[Tuple[str, str], Deque[Dict[str, Any]]] = {}

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

        # valor em % de uso que vai pro gráfico de evolução (ainda sem a trava)
        percentual = self._percentual_para_historico(metrica, payload)

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
            nova_maquina = maquina is None  # Guarda se a máquina é nova pro log
            if nova_maquina:
                maquina = EstadoMaquina(id_maquina=id_maquina)
                self._maquinas[id_maquina] = maquina

            # Só a chave dessa métrica é substituída
            maquina.metricas[metrica] = leitura
            maquina.ultima_atualizacao = recebido_em

            # grava o ponto no histórico dentro da mesma trava, então a última leitura e o histórico nunca ficam inconsistentes entre si pra quem lê
            # Sem percentual (memória no formato mínimo, sem detalhes) não há o que plotar: o ponto não é gravado,
            # pra o gráfico nunca receber "valor": null (o contrato da API promete número)
            if percentual is not None:
                serie = self._historico.get((id_maquina, metrica))
                if serie is None:
                    serie = deque(maxlen=self._historico_maximo)
                    self._historico[(id_maquina, metrica)] = serie
                serie.append(
                    {"t": recebido_em.isoformat(timespec="seconds"), "valor": percentual}
                )

            copia = copy.deepcopy(maquina)
            total = len(self._maquinas)

        # Logs fora da trava
        if nova_maquina:
            # INFO só uma vez por máquina
            logger.info(
                "Nova máquina registrada: %s (total: %d)", id_maquina, total
            )

        # Debug a cada leitura
        logger.debug(
            "Estado atualizado: %s/%s = %s %s (payload %s, recebido %s)",
            id_maquina, metrica, leitura.valor, leitura.unidade,
            leitura.timestamp, recebido_em.isoformat(timespec="seconds"),
        )
        return copia

    @staticmethod
    def _percentual_para_historico(metrica: str, payload: Dict[str, Any]) -> Optional[float]:
        # devolve o valor em % de uso pro gráfico (os dois gráficos usam a mesma escala 0-100)
        # - cpu: o próprio valor já é percentual
        # - memoria: o valor é MB usados; o percentual vem em detalhes["percentual"]
        # Se a memória veio no formato mínimo (sem detalhes), o percentual é desconhecido e vira None
        if metrica == "cpu":
            return payload["valor"]
        detalhes = payload.get("detalhes")
        if isinstance(detalhes, dict):
            percentual = detalhes.get("percentual")
            if isinstance(percentual, (int, float)) and not isinstance(percentual, bool):
                return percentual
        return None

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

    # Listagem de dicts ordenada por id_maquina
    def snapshot(self) -> List[Dict[str, Any]]:
        # Formato de cada item:
        # { "id_maquina": "maquina01",
        #   "cpu": {"valor", "unidade", "timestamp", "detalhes", "recebido_em"} ou None,
        #   "memoria": {mesmos campos} ou None,
        #   "ultima_atualizacao": datetime (relógio do servidor) }
        with self._lock:
            return [
                self._linha_snapshot(self._maquinas[i])
                for i in sorted(self._maquinas)
            ]

    # Transforma uma EstadoMaquina em dict independente (cópia)
    # Só é chamada de dentro do snapshot, com a trava já adquirida
    @staticmethod
    def _linha_snapshot(maquina: EstadoMaquina) -> Dict[str, Any]:
        def como_dict(leitura: Optional[MetricaRecebida]) -> Optional[Dict[str, Any]]:
            return asdict(leitura) if leitura is not None else None

        return {
            "id_maquina": maquina.id_maquina,
            "cpu": como_dict(maquina.metricas.get("cpu")),
            "memoria": como_dict(maquina.metricas.get("memoria")),
            "ultima_atualizacao": maquina.ultima_atualizacao,
        }

    # dashboard: histórico e disponibilidade

    @property
    def timeout_agente(self) -> float:
        # Segundos sem dados a partir dos quais uma máquina é considerada indisponível (o dashboard mostra esse valor como "limite X s")
        return self._timeout_agente

    # Histórico de todas as máquinas, do ponto mais antigo ao mais novo
    # Formato: { "maquina01": {"cpu": [{"t": "<ISO>", "valor": 12.5}, ...], "memoria": [...]}, ... }
    # Toda máquina conhecida traz as duas chaves, com lista vazia se a métrica ainda não tem pontos
    # Devolve cópias, então quem chamar pode mexer no retorno sem afetar o estado
    def historico_todas(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        with self._lock:
            return {
                id_maquina: {
                    metrica: [
                        dict(ponto)
                        for ponto in self._historico.get((id_maquina, metrica), ())
                    ]
                    for metrica in ("cpu", "memoria")
                }
                for id_maquina in sorted(self._maquinas)
            }

    # Retrato pro dashboard, no formato do campo "maquinas" de GET /api/estado
    
    # O status é calculado na hora da chamada: indisponivel se agora - ultima_atualizacao > timeout_agente, senão online
    # Não precisa de thread nem callback e quando chega leitura nova a máquina volta a online sozinha
    def snapshot_dashboard(self, agora: Optional[datetime] = None) -> List[Dict[str, Any]]:
        agora = agora or datetime.now().astimezone()
        with self._lock:
            return [
                self._linha_dashboard(self._maquinas[i], agora)
                for i in sorted(self._maquinas)
            ]

    # Monta o item do dashboard de uma máquina. Só é chamada de dentro do snapshot_dashboard, com a trava já adquirida
    def _linha_dashboard(self, maquina: EstadoMaquina, agora: datetime) -> Dict[str, Any]:
        sem_dados = max(0.0, (agora - maquina.ultima_atualizacao).total_seconds()) # max(0, ...) evita valor negativo se o relógio do servidor andar pra trás
        cpu = maquina.metricas.get("cpu")
        memoria = maquina.metricas.get("memoria")
        return {
            "id_maquina": maquina.id_maquina,
            "status": "indisponivel" if sem_dados > self._timeout_agente else "online", # exatamente no limite ainda é online, só passa de indisponível acima dele
            "segundos_sem_dados": int(sem_dados),
            "cpu": {"valor": cpu.valor} if cpu is not None else None,
            "memoria": (
                {
                    "valor": memoria.valor,
                    "unidade": memoria.unidade,
                    "percentual": self._percentual_para_historico( # mesmo cálculo do histórico (detalhes["percentual"]), None se a leitura não trouxe detalhes
                        "memoria", {"detalhes": memoria.detalhes}
                    ),
                }
                if memoria is not None
                else None
            ),
        }

    def total_maquinas(self) -> int:
        #Quantidade de máquinas conhecidas
        with self._lock:
            return len(self._maquinas)
        