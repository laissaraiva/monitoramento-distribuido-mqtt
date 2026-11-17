
import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

from server.subscriber import MonitorCentral


class TestIntegracao(unittest.TestCase):

    def setUp(self):
        """Cria um monitor central para cada teste."""
        self.monitor = MonitorCentral()

    def enviar_mensagem(self, topico, payload):
        """Simula o recebimento de uma mensagem MQTT."""
        mensagem = SimpleNamespace(
            topic=topico,
            payload=json.dumps(payload).encode("utf-8")
        )

        # Evita imprimir mensagens durante os testes.
        with patch("builtins.print"):
            self.monitor._ao_receber(None, None, mensagem)

    def test_filtro_wildcard(self):
        """Verifica se o subscriber utiliza o wildcard esperado."""
        self.assertEqual(
            self.monitor.filtro,
            "monitoramento/+/+"
        )

    def test_recebimento_cpu_valida(self):
        """Verifica se uma mensagem válida de CPU atualiza o estado."""
        payload = {
            "valor": 45.5,
            "unidade": "%",
            "timestamp": "2026-11-17T14:30:00-03:00"
        }

        self.enviar_mensagem(
            "monitoramento/maquina01/cpu",
            payload
        )

        maquina = self.monitor.estado.obter("maquina01")

        self.assertIsNotNone(maquina)
        self.assertEqual(maquina.metricas["cpu"].valor, 45.5)
        self.assertEqual(maquina.metricas["cpu"].unidade, "%")
        self.assertIsNotNone(maquina.ultima_atualizacao)

    def test_recebimento_memoria_valida(self):
        """Verifica se uma mensagem válida de RAM atualiza o estado."""
        payload = {
            "valor": 4096,
            "unidade": "MB",
            "timestamp": "2026-11-17T14:30:00-03:00"
        }

        self.enviar_mensagem(
            "monitoramento/maquina01/memoria",
            payload
        )

        maquina = self.monitor.estado.obter("maquina01")

        self.assertIsNotNone(maquina)
        self.assertEqual(maquina.metricas["memoria"].valor, 4096)
        self.assertEqual(maquina.metricas["memoria"].unidade, "MB")

    def test_mensagem_invalida_nao_atualiza_estado(self):
        """Verifica se uma mensagem inválida é rejeitada."""
        payload_valido = {
            "valor": 45.5,
            "unidade": "%",
            "timestamp": "2026-11-17T14:30:00-03:00"
        }

        payload_invalido = {
            "valor": 112.5,
            "unidade": "%",
            "timestamp": "2026-11-17T14:30:05-03:00"
        }

        topico = "monitoramento/maquina01/cpu"

        self.enviar_mensagem(topico, payload_valido)
        self.enviar_mensagem(topico, payload_invalido)

        maquina = self.monitor.estado.obter("maquina01")

        self.assertIsNotNone(maquina)

        # O valor inválido não deve substituir o último valor válido.
        self.assertEqual(maquina.metricas["cpu"].valor, 45.5)


if __name__ == "__main__":
    unittest.main()
