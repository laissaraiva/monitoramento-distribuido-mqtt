from datetime import datetime
from typing import Any, Dict, List

import psutil

BYTES_POR_MB: int = 1024 * 1024
JANELA_CPU_PADRAO: float = 1.0


class ErroColeta(RuntimeError):
    pass


def _limitar_percentual(valor: float) -> float:
    return round(min(max(float(valor), 0.0), 100.0), 1)


def _bytes_para_mb(valor_bytes: float) -> float:
    return round(valor_bytes / BYTES_POR_MB, 1)


def timestamp_atual() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def coletar_cpu(janela: float = JANELA_CPU_PADRAO) -> Dict[str, Any]:
    if janela <= 0:
        raise ValueError("A janela de medição da CPU deve ser maior que zero.")

    try:
        uso_nucleos: List[float] = psutil.cpu_percent(interval=janela, percpu=True)
    except (psutil.Error, OSError) as exc:
        raise ErroColeta(f"Falha ao coletar o uso de CPU: {exc}") from exc

    if not uso_nucleos:
        raise ErroColeta("psutil não retornou dados de uso por núcleo da CPU.")

    por_nucleo = [_limitar_percentual(uso) for uso in uso_nucleos]
    percentual_geral = _limitar_percentual(sum(uso_nucleos) / len(uso_nucleos))

    return {
        "percentual": percentual_geral,
        "por_nucleo": por_nucleo,
    }


def coletar_memoria() -> Dict[str, float]:
    try:
        memoria = psutil.virtual_memory()
    except (psutil.Error, OSError) as exc:
        raise ErroColeta(f"Falha ao coletar o uso de memória RAM: {exc}") from exc

    if memoria.total <= 0:
        raise ErroColeta("psutil retornou memória RAM total inválida.")

    disponivel = min(max(memoria.available, 0), memoria.total)
    utilizada = memoria.total - disponivel

    return {
        "utilizada": _bytes_para_mb(utilizada),
        "total": _bytes_para_mb(memoria.total),
        "livre": _bytes_para_mb(disponivel),
        "percentual": _limitar_percentual(memoria.percent),
    }


if __name__ == "__main__":
    print(f"Timestamp: {timestamp_atual()}")

    cpu = coletar_cpu()
    print(f"CPU geral: {cpu['percentual']}%")
    print(f"CPU por núcleo ({len(cpu['por_nucleo'])} núcleos): {cpu['por_nucleo']}")

    ram = coletar_memoria()
    print(
        f"RAM: {ram['utilizada']} MB utilizados de {ram['total']} MB "
        f"({ram['percentual']}%), {ram['livre']} MB livres"
    )