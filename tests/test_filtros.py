# Testes da validação do filtro de assinatura MQTT (common/filtros.py)

# Rodar a partir da raiz do repositório com
#   python3 -m unittest tests.test_filtros -v
#   python3 -m pytest tests/test_filtros.py -v

import unittest

from common.filtros import (
    NIVEIS_MAXIMOS_FILTRO,
    TAMANHO_MAXIMO_FILTRO,
    validar_filtro_assinatura,
)


class TestFiltrosAceitos(unittest.TestCase):
    def test_filtros_validos(self):
        aceitos = [
            "monitoramento/+/+",             # todas as máquinas e métricas (padrão)
            "monitoramento/#",               # tudo abaixo do prefixo
            "monitoramento/+/cpu",           # só CPU
            "monitoramento/+/memoria",       # só memória
            "monitoramento/maquina01/+",     # uma máquina, todas as métricas
            "monitoramento/maquina01/cpu",   # tópico exato, sem curinga
            "monitoramento/maquina01/#",     # '#' como último nível
        ]
        for filtro in aceitos:
            with self.subTest(filtro=filtro):
                resultado = validar_filtro_assinatura(filtro)
                self.assertTrue(resultado.valido, resultado.erro)
                self.assertIsNone(resultado.erro)
                self.assertEqual(resultado.dados, {"filtro": filtro})

    def test_limites_exatos_ainda_sao_aceitos(self):
        # exatamente 8 níveis
        self.assertTrue(validar_filtro_assinatura("/".join(["monitoramento"] + ["+"] * (NIVEIS_MAXIMOS_FILTRO - 1))).valido)
        # exatamente 128 caracteres
        filtro = "monitoramento/" + "a" * (TAMANHO_MAXIMO_FILTRO - len("monitoramento/"))
        self.assertEqual(len(filtro), TAMANHO_MAXIMO_FILTRO)
        self.assertTrue(validar_filtro_assinatura(filtro).valido)


class TestFiltrosRejeitados(unittest.TestCase):
    def test_rejeitados_com_erro_em_portugues(self):
        rejeitados = [
            "x",                         # prefixo errado
            "#",                         # '#' sozinho: não começa com o prefixo
            "monitoramento/ma+/cpu",     # '+' misturado com texto
            "monitoramento/#/cpu",       # '#' fora do último nível
            "monitoramento/maq#",        # '#' misturado com texto
            "monitoramento//cpu",        # nível vazio no meio
            "monitoramento/",            # nível vazio no fim
            "/monitoramento/+/+",        # nível vazio no começo
            "monitoramento",             # sem nenhum nível depois do prefixo
            "outro/+/cpu",               # prefixo diferente
            "Monitoramento/+/cpu",       # maiúscula: o prefixo é sensível a caixa
            "",                          # vazio
            "   ",                       # só espaços
            "monitoramento/+/ cpu",      # espaço no meio
            " monitoramento/+/+",        # espaço no começo
            "monitoramento/+/cpu\n",     # quebra de linha
            "monitoramento/\x00/cpu",    # caractere de controle
        ]
        for filtro in rejeitados:
            with self.subTest(filtro=filtro):
                resultado = validar_filtro_assinatura(filtro)
                self.assertFalse(resultado.valido)
                self.assertTrue(resultado.erro)   # texto pronto pra ir pra tela
                self.assertEqual(resultado.dados, {})

    def test_acima_dos_limites(self):
        longo = "monitoramento/" + "a" * TAMANHO_MAXIMO_FILTRO
        self.assertFalse(validar_filtro_assinatura(longo).valido)
        niveis = "/".join(["monitoramento"] + ["+"] * NIVEIS_MAXIMOS_FILTRO)  # 9 níveis
        self.assertFalse(validar_filtro_assinatura(niveis).valido)

    def test_tipos_que_nao_sao_texto(self):
        for filtro in (None, 123, ["monitoramento/#"], b"monitoramento/#"):
            with self.subTest(filtro=filtro):
                resultado = validar_filtro_assinatura(filtro)
                self.assertFalse(resultado.valido)
                self.assertIn("texto", resultado.erro)

    def test_mensagens_especificas(self):
        self.assertIn("começar com", validar_filtro_assinatura("x").erro)
        self.assertIn("último nível", validar_filtro_assinatura("monitoramento/#/cpu").erro)
        self.assertIn("'+'", validar_filtro_assinatura("monitoramento/ma+/cpu").erro)
        self.assertIn("'#'", validar_filtro_assinatura("monitoramento/maq#").erro)
        self.assertIn("vazio", validar_filtro_assinatura("monitoramento//cpu").erro)
        self.assertIn("vazio", validar_filtro_assinatura("").erro)


if __name__ == "__main__":
    unittest.main()