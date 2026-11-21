import json
import unittest
from unittest.mock import patch

from agent.publisher import AgenteMonitoramento, QOS


class TestPublisherEntrega2(unittest.TestCase):
    def setUp(self):
        patcher = patch("agent.publisher.mqtt.Client")
        self.classe_cliente = patcher.start()
        self.addCleanup(patcher.stop)
        self.cliente = self.classe_cliente.return_value
        self.cliente.is_connected.return_value = True
        self.cliente.publish.return_value.rc = 0

    def test_agentes_usam_ids_mqtt_diferentes(self):
        AgenteMonitoramento("maquina01")
        AgenteMonitoramento("maquina02")
        ids = [chamada.kwargs["client_id"] for chamada in self.classe_cliente.call_args_list]
        self.assertEqual(ids, ["agente-maquina01", "agente-maquina02"])

    def test_publica_cpu_e_memoria_no_mesmo_ciclo(self):
        agente = AgenteMonitoramento("maquina01")
        cpu = {"percentual": 20.0, "por_nucleo": [20.0]}
        memoria = {"utilizada": 4096.0, "total": 8192.0,
                   "livre": 4096.0, "percentual": 50.0}
        timestamp = "2026-11-21T12:00:00-03:00"

        with patch("agent.publisher.coletar_cpu", return_value=cpu), \
             patch("agent.publisher.coletar_memoria", return_value=memoria), \
             patch("agent.publisher.timestamp_atual", return_value=timestamp):
            agente.executar_ciclo()

        chamadas = self.cliente.publish.call_args_list
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(chamadas[0].args[0], "monitoramento/maquina01/cpu")
        self.assertEqual(chamadas[1].args[0], "monitoramento/maquina01/memoria")
        for chamada in chamadas:
            payload = json.loads(chamada.args[1])
            self.assertIn("valor", payload)
            self.assertIn("unidade", payload)
            self.assertEqual(payload["timestamp"], timestamp)
            self.assertEqual(chamada.kwargs["qos"], QOS)

    def test_nao_publica_quando_desconectado(self):
        agente = AgenteMonitoramento("maquina01")
        self.cliente.is_connected.return_value = False
        payload = {"valor": 15.0, "unidade": "%",
                   "timestamp": "2026-11-21T12:00:00-03:00"}
        self.assertFalse(agente.publicar("monitoramento/maquina01/cpu", payload))
        self.cliente.publish.assert_not_called()

    def test_reconexao_automatica_esta_configurada(self):
        AgenteMonitoramento("maquina01")
        self.cliente.reconnect_delay_set.assert_called_once_with(
            min_delay=1, max_delay=30
        )


if __name__ == "__main__":
    unittest.main()
