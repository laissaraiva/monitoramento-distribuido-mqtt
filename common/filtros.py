# Validação do filtro de assinatura MQTT digitado na interface

# O dashboard deixa o usuário trocar o filtro com wildcards (ex.: monitoramento/+/cpu)
# Esta função confere o texto ANTES de ele chegar ao broker e devolve o motivo do erro, que é mostrado direto na tela

# Segue o mesmo padrão de common/validation.py: devolve ResultadoValidacao em vez de
# lançar exceção, pra quem chama (subscriber/dashboard) poder repassar o motivo exato

# O módulo é importado como "from common.filtros import validar_filtro_assinatura"

from typing import Any

from common.validation import PREFIXO_TOPICO, ResultadoValidacao

# Limites de segurança do filtro
TAMANHO_MAXIMO_FILTRO: int = 128
NIVEIS_MAXIMOS_FILTRO: int = 8


def _erro(mensagem: str) -> ResultadoValidacao:
    # Atalho pra montar um resultado de rejeição
    return ResultadoValidacao(valido=False, erro=mensagem)


def validar_filtro_assinatura(filtro: Any) -> ResultadoValidacao:
    # Regras:
    # - texto não vazio, sem espaços nem caracteres de controle, até 128 caracteres
    # - níveis separados por "/" e nenhum nível vazio
    # - primeiro nível igual a PREFIXO_TOPICO ("monitoramento") e pelo menos mais um nível
    # - no máximo 8 níveis
    # - "#" só pode ser o último nível e deve ocupar o nível inteiro
    # - "+" deve ocupar o nível inteiro

    # Aceita: monitoramento/#, monitoramento/+/+, monitoramento/+/cpu, monitoramento/maquina01/+
    # Rejeita: x, #, monitoramento/ma+/cpu, monitoramento/#/cpu, monitoramento//cpu

    # 1) Tipo e conteúdo geral
    if not isinstance(filtro, str):
        return _erro(f"O filtro deve ser um texto, mas recebeu {type(filtro).__name__}.")

    if not filtro.strip():
        return _erro("O filtro não pode ficar vazio.")

    if len(filtro) > TAMANHO_MAXIMO_FILTRO:
        return _erro(
            f"O filtro é longo demais ({len(filtro)} caracteres); "
            f"o máximo é {TAMANHO_MAXIMO_FILTRO}."
        )

    # isspace() cobre espaço, tab e quebra de linha; o resto cobre os demais caracteres de controle
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in filtro):
        return _erro("O filtro não pode conter espaços nem caracteres de controle.")

    # 2) Estrutura em níveis
    niveis = filtro.split("/")

    if any(nivel == "" for nivel in niveis):
        return _erro("O filtro não pode ter nível vazio (verifique barras '/' duplicadas ou nas pontas).")

    if niveis[0] != PREFIXO_TOPICO:
        return _erro(f"O filtro deve começar com '{PREFIXO_TOPICO}/', por exemplo '{PREFIXO_TOPICO}/+/cpu'.")

    if len(niveis) < 2:
        return _erro(f"Informe ao menos um nível depois de '{PREFIXO_TOPICO}/', por exemplo '{PREFIXO_TOPICO}/#'.")

    if len(niveis) > NIVEIS_MAXIMOS_FILTRO:
        return _erro(f"O filtro tem níveis demais ({len(niveis)}); o máximo é {NIVEIS_MAXIMOS_FILTRO}.")

    # 3) Curingas, nível por nível
    ultimo = len(niveis) - 1
    for posicao, nivel in enumerate(niveis):
        if "#" in nivel:
            if nivel != "#":
                return _erro("O curinga '#' deve ocupar um nível inteiro (não pode estar misturado com outras letras).")
            if posicao != ultimo:
                return _erro("O curinga '#' só pode ser o último nível do filtro.")
        if "+" in nivel and nivel != "+":
            return _erro("O curinga '+' deve ocupar um nível inteiro (não pode estar misturado com outras letras).")

    return ResultadoValidacao(valido=True, dados={"filtro": filtro})