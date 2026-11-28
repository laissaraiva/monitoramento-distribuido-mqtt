import logging
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import paho.mqtt.client as mqtt

from server.subscriber import HandlerEventos, MonitorCentral, logger

OK = (mqtt.MQTT_ERR_SUCCESS, 1)


def instalar_painel(teste: unittest.TestCase) -> HandlerEventos:
    # Liga um HandlerEventos ao logger "monitor" pelo tempo do teste (como o configurar_logs faz).
    # Não dá para usar assertLogs junto: ele substitui os handlers do logger enquanto está aberto.
    eventos = HandlerEventos()
    logger.addHandler(eventos)
    teste.addCleanup(logger.removeHandler, eventos)
    nivel = logger.level
    teste.addCleanup(logger.setLevel, nivel)
    logger.setLevel(logging.INFO)
    return eventos


class BaseMonitor(unittest.TestCase):
    # Cliente MQTT substituído por um mock: nenhum teste abre conexão de rede
    def setUp(self):
        patcher = patch("server.subscriber.mqtt.Client")
        self.classe_cliente = patcher.start()
        self.addCleanup(patcher.stop)
        self.cliente = self.classe_cliente.return_value
        self.cliente.subscribe.return_value = OK
        self.cliente.unsubscribe.return_value = OK
        self.monitor = MonitorCentral(filtro="monitoramento/+/+")

    def conectar(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.cliente.subscribe.reset_mock()


class TestSegundoPlano(BaseMonitor):
    def test_iniciar_em_segundo_plano_conecta_e_volta_logo(self):
        monitor = MonitorCentral(host="broker.local", porta=1999)
        with self.assertLogs(logger, level="INFO"):
            monitor.iniciar_em_segundo_plano()
        self.cliente.connect_async.assert_called_once_with("broker.local", 1999, keepalive=60)
        self.cliente.loop_start.assert_called_once()

    def test_iniciar_em_segundo_plano_duas_vezes_conecta_uma_vez(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.iniciar_em_segundo_plano()
            self.monitor.iniciar_em_segundo_plano()
        self.cliente.connect_async.assert_called_once()
        self.cliente.loop_start.assert_called_once()

    def test_encerrar_para_o_cliente(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.iniciar_em_segundo_plano()
            self.monitor.conectado = True
            self.monitor.encerrar()
        self.cliente.disconnect.assert_called_once()
        self.cliente.loop_stop.assert_called_once()
        self.assertFalse(self.monitor.conectado)

    def test_encerrar_repetido_nao_repete_nada(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.iniciar_em_segundo_plano()
            self.monitor.encerrar()
            self.monitor.encerrar()
        self.cliente.disconnect.assert_called_once()
        self.cliente.loop_stop.assert_called_once()

    def test_encerrar_sem_ter_iniciado_nao_faz_nada(self):
        self.monitor.encerrar()
        self.cliente.disconnect.assert_not_called()
        self.cliente.loop_stop.assert_not_called()

    def test_desconexao_ao_encerrar_nao_vira_erro_de_conexao(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.iniciar_em_segundo_plano()
            self.monitor.encerrar()
            self.monitor._ao_desconectar(self.cliente, None, None, 7, None)
        self.assertIsNone(self.monitor.erro_conexao)

    def test_nao_escreve_no_terminal(self):
        with patch("sys.stdout") as saida, self.assertLogs(logger, level="INFO"):
            self.monitor.iniciar_em_segundo_plano()
            self.monitor.encerrar()
        saida.write.assert_not_called()


class TestEstadoBroker(BaseMonitor):
    def test_estado_inicial(self):
        self.assertEqual(
            self.monitor.estado_broker(),
            {"conectado": False, "host": "127.0.0.1", "porta": 1883, "erro": None},
        )

    def test_falha_ao_conectar_registra_o_motivo(self):
        monitor = MonitorCentral(host="192.168.0.10", porta=1884)
        with self.assertLogs(logger, level="WARNING"):
            monitor._ao_falhar_conexao(self.cliente, None)
        estado = monitor.estado_broker()
        self.assertFalse(estado["conectado"])
        self.assertEqual(estado["erro"], "Não foi possível conectar a 192.168.0.10:1884")

    def test_falha_repetida_nao_enche_o_painel_de_eventos(self):
        eventos = instalar_painel(self)
        for _ in range(5):
            self.monitor._ao_falhar_conexao(self.cliente, None)
        self.assertEqual(len(eventos.recentes(50)), 1)
        self.assertIn("Não foi possível conectar", eventos.recentes(1)[0])

    def test_conectar_apaga_o_erro(self):
        with self.assertLogs(logger, level="WARNING"):
            self.monitor._ao_falhar_conexao(self.cliente, None)
        self.conectar()
        estado = self.monitor.estado_broker()
        self.assertTrue(estado["conectado"])
        self.assertIsNone(estado["erro"])

    def test_conexao_recusada_guarda_o_motivo(self):
        with self.assertLogs(logger, level="ERROR"):
            self.monitor._ao_conectar(self.cliente, None, None, 5)
        estado = self.monitor.estado_broker()
        self.assertFalse(estado["conectado"])
        self.assertIn("authorised", estado["erro"])

    def test_queda_inesperada_guarda_o_motivo(self):
        self.conectar()
        self.monitor._executando = True
        with self.assertLogs(logger, level="WARNING"):
            self.monitor._ao_desconectar(self.cliente, None, None, 7, None)
        estado = self.monitor.estado_broker()
        self.assertFalse(estado["conectado"])
        self.assertIn("perdida", estado["erro"])

    def test_desconexao_limpa_nao_gera_erro(self):
        self.conectar()
        with self.assertLogs(logger, level="INFO"):
            self.monitor._ao_desconectar(self.cliente, None, None, 0, None)
        self.assertIsNone(self.monitor.erro_conexao)

    def test_falha_de_conexao_registra_o_callback_no_cliente(self):
        self.assertEqual(self.cliente.on_connect_fail, self.monitor._ao_falhar_conexao)


class TestAlterarFiltro(BaseMonitor):
    def test_valido_conectado_troca_a_assinatura(self):
        self.conectar()
        with self.assertLogs(logger, level="INFO") as capturado:
            self.monitor.alterar_filtro("monitoramento/+/cpu")
        self.cliente.unsubscribe.assert_called_once_with("monitoramento/+/+")
        self.cliente.subscribe.assert_called_once_with("monitoramento/+/cpu", qos=0)
        self.assertEqual(self.monitor.filtro, "monitoramento/+/cpu")
        self.assertTrue(
            any("Filtro alterado de monitoramento/+/+ para monitoramento/+/cpu" in l for l in capturado.output)
        )

    def test_desanexa_antes_de_assinar(self):
        self.conectar()
        ordem = []
        self.cliente.unsubscribe.side_effect = lambda *a, **k: ordem.append("unsubscribe") or OK
        self.cliente.subscribe.side_effect = lambda *a, **k: ordem.append("subscribe") or OK
        with self.assertLogs(logger, level="INFO"):
            self.monitor.alterar_filtro("monitoramento/+/cpu")
        self.assertEqual(ordem, ["unsubscribe", "subscribe"])

    def test_invalido_levanta_valueerror_e_nao_mexe_na_assinatura(self):
        self.conectar()
        for filtro in ["x", "", "#", "monitoramento/ma+/cpu", "monitoramento/#/cpu", None, 123]:
            with self.subTest(filtro=filtro):
                with self.assertRaises(ValueError) as ctx:
                    self.monitor.alterar_filtro(filtro)
                self.assertTrue(str(ctx.exception))
        self.cliente.unsubscribe.assert_not_called()
        self.cliente.subscribe.assert_not_called()
        self.assertEqual(self.monitor.filtro, "monitoramento/+/+")

    def test_mensagem_de_erro_e_a_da_validacao(self):
        with self.assertRaises(ValueError) as ctx:
            self.monitor.alterar_filtro("x")
        self.assertIn("monitoramento", str(ctx.exception))

    def test_desconectado_so_guarda_e_a_reconexao_assina_o_novo(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.alterar_filtro("monitoramento/maquina01/+")
        self.cliente.unsubscribe.assert_not_called()
        self.cliente.subscribe.assert_not_called()
        self.assertEqual(self.monitor.filtro, "monitoramento/maquina01/+")

        with self.assertLogs(logger, level="INFO"):
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.cliente.subscribe.assert_called_once_with("monitoramento/maquina01/+", qos=0)

    def test_filtro_novo_vale_depois_de_uma_reconexao(self):
        self.conectar()
        with self.assertLogs(logger, level="INFO"):
            self.monitor.alterar_filtro("monitoramento/+/memoria")
            self.monitor._ao_desconectar(self.cliente, None, None, 7, None)
            self.cliente.subscribe.reset_mock()
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.cliente.subscribe.assert_called_once_with("monitoramento/+/memoria", qos=0)

    def test_mesmo_filtro_nao_faz_nada(self):
        self.conectar()
        self.monitor.alterar_filtro("monitoramento/+/+")
        self.cliente.unsubscribe.assert_not_called()
        self.cliente.subscribe.assert_not_called()

    def test_falha_ao_assinar_o_novo_devolve_o_antigo(self):
        self.conectar()
        self.cliente.subscribe.side_effect = [(mqtt.MQTT_ERR_QUEUE_SIZE, None), OK]
        with self.assertRaises(ValueError) as ctx:
            self.monitor.alterar_filtro("monitoramento/+/cpu")
        self.assertIn("monitoramento/+/cpu", str(ctx.exception))
        self.assertEqual(self.monitor.filtro, "monitoramento/+/+")
        # 1ª chamada: tentativa do novo; 2ª: reassinatura do antigo
        self.assertEqual(
            [c.args[0] for c in self.cliente.subscribe.call_args_list],
            ["monitoramento/+/cpu", "monitoramento/+/+"],
        )

    def test_falha_ao_cancelar_o_antigo_nao_muda_o_filtro(self):
        self.conectar()
        self.cliente.unsubscribe.return_value = (mqtt.MQTT_ERR_QUEUE_SIZE, None)
        with self.assertRaises(ValueError):
            self.monitor.alterar_filtro("monitoramento/+/cpu")
        self.cliente.subscribe.assert_not_called()
        self.assertEqual(self.monitor.filtro, "monitoramento/+/+")

    def test_conexao_caiu_no_meio_da_troca_guarda_o_filtro(self):
        self.conectar()
        self.cliente.unsubscribe.return_value = (mqtt.MQTT_ERR_NO_CONN, None)
        with self.assertLogs(logger, level="INFO"):
            self.monitor.alterar_filtro("monitoramento/+/cpu")
        self.assertEqual(self.monitor.filtro, "monitoramento/+/cpu")


class TestReconectar(BaseMonitor):
    def test_valido_refaz_a_conexao_no_novo_destino(self):
        self.conectar()
        self.monitor.erro_conexao = "erro antigo"
        with self.assertLogs(logger, level="INFO") as capturado:
            self.monitor.reconectar("192.168.0.10", 1884)

        self.assertEqual((self.monitor.host, self.monitor.porta), ("192.168.0.10", 1884))
        self.assertFalse(self.monitor.conectado)
        self.assertIsNone(self.monitor.erro_conexao)
        self.cliente.loop_stop.assert_called_once()
        self.cliente.disconnect.assert_called_once()
        self.cliente.connect_async.assert_called_once_with("192.168.0.10", 1884, keepalive=60)
        self.cliente.loop_start.assert_called_once()
        self.assertTrue(any("Broker alterado para 192.168.0.10:1884" in l for l in capturado.output))

    def test_para_a_thread_antes_de_trocar_o_destino(self):
        self.conectar()
        vistos = []
        self.cliente.loop_stop.side_effect = lambda: vistos.append(("loop_stop", self.monitor.host))
        self.cliente.connect_async.side_effect = lambda *a, **k: vistos.append(("connect_async", self.monitor.host))
        with self.assertLogs(logger, level="INFO"):
            self.monitor.reconectar("novo.local", 1883)
        self.assertEqual(vistos, [("loop_stop", "127.0.0.1"), ("connect_async", "novo.local")])

    def test_assinatura_e_refeita_com_o_filtro_atual(self):
        self.conectar()
        with self.assertLogs(logger, level="INFO"):
            self.monitor.alterar_filtro("monitoramento/+/cpu")
            self.monitor.reconectar("novo.local", 1883)
            self.cliente.subscribe.reset_mock()
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.cliente.subscribe.assert_called_once_with("monitoramento/+/cpu", qos=0)

    def test_aceita_porta_como_texto_e_apara_o_host(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.reconectar("  novo.local  ", "1999")
        self.assertEqual((self.monitor.host, self.monitor.porta), ("novo.local", 1999))

    def test_host_invalido(self):
        for host in ["", "   ", "dois palavras", "a\tb", None, 123, "x" * 300]:
            with self.subTest(host=host):
                with self.assertRaises(ValueError) as ctx:
                    self.monitor.reconectar(host, 1883)
                self.assertIn("broker", str(ctx.exception))

    def test_porta_invalida(self):
        for porta in [0, -1, 65536, 99999, "abc", "", "18.83", "1_883", 1883.5, True, None, [1883]]:
            with self.subTest(porta=porta):
                with self.assertRaises(ValueError) as ctx:
                    self.monitor.reconectar("novo.local", porta)
                self.assertIn("porta", str(ctx.exception).lower())

    def test_limites_da_porta(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.reconectar("novo.local", 1)
            self.monitor.reconectar("novo.local", 65535)
        self.assertEqual(self.monitor.porta, 65535)

    def test_invalido_nao_mexe_na_conexao_atual(self):
        self.conectar()
        with self.assertRaises(ValueError):
            self.monitor.reconectar("novo.local", 99999)
        self.assertEqual((self.monitor.host, self.monitor.porta), ("127.0.0.1", 1883))
        self.assertTrue(self.monitor.conectado)
        self.cliente.loop_stop.assert_not_called()
        self.cliente.disconnect.assert_not_called()
        self.cliente.connect_async.assert_not_called()

    def test_encerrar_depois_de_reconectar_para_o_cliente(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor.reconectar("novo.local", 1883)
            self.cliente.disconnect.reset_mock()
            self.cliente.loop_stop.reset_mock()
            self.monitor.encerrar()
        self.cliente.disconnect.assert_called_once()
        self.cliente.loop_stop.assert_called_once()


class TestContadoresEEventos(BaseMonitor):
    def test_contadores(self):
        self.assertEqual(self.monitor.contadores(), {"recebidas": 0, "descartadas": 0})
        self.monitor.mensagens_recebidas = 40
        self.monitor.mensagens_descartadas = 2
        self.assertEqual(self.monitor.contadores(), {"recebidas": 40, "descartadas": 2})

    def test_eventos_recentes_sem_handler_devolve_lista_vazia(self):
        self.assertEqual(self.monitor.eventos_recentes(), [])

    def test_eventos_recentes_traz_os_ultimos_do_mais_antigo_ao_mais_novo(self):
        eventos = instalar_painel(self)
        monitor = MonitorCentral(eventos=eventos)
        for i in range(40):
            logger.info("evento %d", i)
        recentes = monitor.eventos_recentes(3)
        self.assertEqual(len(recentes), 3)
        self.assertTrue(recentes[0].endswith("evento 37"))
        self.assertTrue(recentes[-1].endswith("evento 39"))
        self.assertEqual(len(monitor.eventos_recentes()), 30)

    def test_descarte_entra_nos_eventos_e_nos_contadores(self):
        eventos = instalar_painel(self)
        monitor = MonitorCentral(eventos=eventos)
        monitor._ao_receber(None, None, SimpleNamespace(topic="monitoramento/m1/cpu", payload=b"lixo"))
        self.assertEqual(monitor.contadores(), {"recebidas": 1, "descartadas": 1})
        self.assertTrue(any("descartada" in linha for linha in monitor.eventos_recentes()))


class TestConcorrencia(BaseMonitor):
    def test_alterar_filtro_em_varias_threads_termina_com_um_filtro_valido(self):
        self.conectar()
        filtros = ["monitoramento/+/cpu", "monitoramento/+/memoria", "monitoramento/#", "monitoramento/+/+"]
        erros = []

        def trocar(filtro):
            try:
                for _ in range(20):
                    self.monitor.alterar_filtro(filtro)
            except Exception as exc:  # pragma: no cover - só aparece se der errado
                erros.append(exc)

        with self.assertLogs(logger, level="INFO"):
            threads = [threading.Thread(target=trocar, args=(f,)) for f in filtros]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
        self.assertEqual(erros, [])
        self.assertIn(self.monitor.filtro, filtros)
        # a última assinatura pedida ao broker é a do filtro que ficou valendo
        self.assertEqual(self.cliente.subscribe.call_args.args[0], self.monitor.filtro)


if __name__ == "__main__":
    unittest.main()