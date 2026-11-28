import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import paho.mqtt.client as mqtt

from server.dashboard import _urls_de_acesso, criar_app, ler_argumentos
from server.state import EstadoCentral
from server.subscriber import HandlerEventos, MonitorCentral, logger

FUSO = timezone(timedelta(hours=-3))
AGORA = datetime.now(FUSO)
TS = "2026-11-28T12:00:00-03:00"
OK = (mqtt.MQTT_ERR_SUCCESS, 1)

CHAVES_ESTADO = ["servidor_hora", "broker", "filtro", "timeout_agente", "contadores", "maquinas", "eventos"]


def cpu(valor=12.5):
    return {"valor": valor, "unidade": "%", "timestamp": TS}


def mem(valor=4096.0, percentual=51.2):
    return {
        "valor": valor, "unidade": "MB", "timestamp": TS,
        "detalhes": {"total": 8000.0, "livre": 3904.0, "percentual": percentual},
    }


class BaseApi(unittest.TestCase):
    def setUp(self):
        patcher = patch("server.subscriber.mqtt.Client")
        self.classe_cliente = patcher.start()
        self.addCleanup(patcher.stop)
        self.cliente = self.classe_cliente.return_value
        self.cliente.subscribe.return_value = OK
        self.cliente.unsubscribe.return_value = OK

        # Painel de eventos ligado ao logger, como o configurar_logs faz no dashboard real
        self.eventos = HandlerEventos()
        logger.addHandler(self.eventos)
        self.addCleanup(logger.removeHandler, self.eventos)
        nivel = logger.level
        self.addCleanup(logger.setLevel, nivel)
        logger.setLevel(logging.INFO)

        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        web = Path(self.pasta.name)
        (web / "index.html").write_text("<!doctype html><title>Painel</title>", encoding="utf-8")
        (web / "app.js").write_text("console.log('ok');", encoding="utf-8")
        (web / "vendor").mkdir()
        (web / "vendor" / "lib.js").write_text("var lib = 1;", encoding="utf-8")
        (web.parent / "segredo.txt").write_text("fora da pasta web", encoding="utf-8")
        self.addCleanup((web.parent / "segredo.txt").unlink)

        self.estado = EstadoCentral(timeout_agente=15.0)
        self.monitor = MonitorCentral(estado=self.estado, eventos=self.eventos)
        self.app = criar_app(self.monitor, self.pasta.name)
        self.http = self.app.test_client()

    def estado_json(self):
        resposta = self.http.get("/api/estado")
        self.assertEqual(resposta.status_code, 200)
        return resposta.get_json()

    def postar(self, rota, corpo):
        return self.http.post(rota, json=corpo)


class TestApiEstado(BaseApi):
    def test_formato_do_contrato_sem_maquinas(self):
        dados = self.estado_json()
        self.assertEqual(list(dados), CHAVES_ESTADO)
        self.assertEqual(dados["maquinas"], [])
        self.assertEqual(dados["eventos"], [])
        self.assertEqual(dados["contadores"], {"recebidas": 0, "descartadas": 0})
        self.assertEqual(dados["filtro"], "monitoramento/+/+")
        self.assertEqual(dados["timeout_agente"], 15.0)
        self.assertEqual(dados["broker"], {"conectado": False, "host": "127.0.0.1", "porta": 1883, "erro": None})
        self.assertIsNotNone(datetime.fromisoformat(dados["servidor_hora"]).utcoffset())

    def test_maquinas_com_as_duas_metricas(self):
        self.estado.atualizar("maquina01", "cpu", cpu(12.5), AGORA - timedelta(seconds=3))
        self.estado.atualizar("maquina01", "memoria", mem(4096.0, 51.2), AGORA - timedelta(seconds=3))
        maquina = self.estado_json()["maquinas"][0]
        self.assertEqual(maquina["id_maquina"], "maquina01")
        self.assertEqual(maquina["status"], "online")
        self.assertIn(maquina["segundos_sem_dados"], range(3, 6))
        self.assertEqual(maquina["cpu"], {"valor": 12.5})
        self.assertEqual(maquina["memoria"], {"valor": 4096.0, "unidade": "MB", "percentual": 51.2})

    def test_metrica_que_nao_chegou_vem_null(self):
        self.estado.atualizar("maquina01", "cpu", cpu(), AGORA)
        maquina = self.estado_json()["maquinas"][0]
        self.assertIsNone(maquina["memoria"])

    def test_memoria_sem_detalhes_tem_percentual_null(self):
        payload = {"valor": 4096.0, "unidade": "MB", "timestamp": TS}
        self.estado.atualizar("maquina01", "memoria", payload, AGORA)
        memoria = self.estado_json()["maquinas"][0]["memoria"]
        self.assertIsNone(memoria["percentual"])

    def test_maquina_sem_dados_alem_do_timeout_fica_indisponivel(self):
        self.estado.atualizar("maquina01", "cpu", cpu(), AGORA - timedelta(seconds=30))
        self.estado.atualizar("maquina02", "cpu", cpu(), AGORA)
        status = {m["id_maquina"]: m["status"] for m in self.estado_json()["maquinas"]}
        self.assertEqual(status, {"maquina01": "indisponivel", "maquina02": "online"})

    def test_timeout_vem_do_estado(self):
        monitor = MonitorCentral(estado=EstadoCentral(timeout_agente=7))
        dados = criar_app(monitor, self.pasta.name).test_client().get("/api/estado").get_json()
        self.assertEqual(dados["timeout_agente"], 7)

    def test_broker_fora_traz_o_erro(self):
        with self.assertLogs(logger, level="WARNING"):
            self.monitor._ao_falhar_conexao(self.cliente, None)
        broker = self.estado_json()["broker"]
        self.assertFalse(broker["conectado"])
        self.assertEqual(broker["erro"], "Não foi possível conectar a 127.0.0.1:1883")

    def test_broker_conectado(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        broker = self.estado_json()["broker"]
        self.assertTrue(broker["conectado"])
        self.assertIsNone(broker["erro"])

    def test_mensagem_invalida_vira_evento_e_conta_como_descartada(self):
        from types import SimpleNamespace

        self.monitor._ao_receber(None, None, SimpleNamespace(topic="monitoramento/maquina01/cpu", payload=b"{lixo"))
        dados = self.estado_json()
        self.assertEqual(dados["contadores"], {"recebidas": 1, "descartadas": 1})
        self.assertEqual(len(dados["eventos"]), 1)
        self.assertIn("descartada", dados["eventos"][0])
        self.assertIn("monitoramento/maquina01/cpu", dados["eventos"][0])

    def test_eventos_limitados_a_30_do_mais_antigo_ao_mais_novo(self):
        for i in range(40):
            logger.info("evento %d", i)
        eventos = self.estado_json()["eventos"]
        self.assertEqual(len(eventos), 30)
        self.assertTrue(eventos[0].endswith("evento 10"))
        self.assertTrue(eventos[-1].endswith("evento 39"))

    def test_sem_cache(self):
        self.assertEqual(self.http.get("/api/estado").headers["Cache-Control"], "no-store")
        self.assertEqual(self.http.get("/api/historico").headers["Cache-Control"], "no-store")

    def test_json_em_utf8_sem_escapar_acentos(self):
        with self.assertLogs(logger, level="WARNING"):
            self.monitor._ao_falhar_conexao(self.cliente, None)
        resposta = self.http.get("/api/estado")
        # JSON é UTF-8 por definição; o acento tem de ir como caractere, não como \u00e3
        self.assertIn("Não foi possível".encode("utf-8"), resposta.get_data())


class TestApiHistorico(BaseApi):
    def test_sem_maquinas_devolve_objeto_vazio(self):
        resposta = self.http.get("/api/historico")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json(), {})

    def test_formato_do_contrato(self):
        self.estado.atualizar("maquina01", "cpu", cpu(10.0), AGORA - timedelta(seconds=10))
        self.estado.atualizar("maquina01", "cpu", cpu(20.0), AGORA)
        self.estado.atualizar("maquina01", "memoria", mem(percentual=55.5), AGORA)
        historico = self.http.get("/api/historico").get_json()
        self.assertEqual(list(historico), ["maquina01"])
        self.assertEqual([p["valor"] for p in historico["maquina01"]["cpu"]], [10.0, 20.0])
        self.assertEqual([p["valor"] for p in historico["maquina01"]["memoria"]], [55.5])
        self.assertEqual(set(historico["maquina01"]["cpu"][0]), {"t", "valor"})
        datetime.fromisoformat(historico["maquina01"]["cpu"][0]["t"])


class TestApiFiltro(BaseApi):
    def conectar(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.cliente.subscribe.reset_mock()

    def test_filtro_invalido_devolve_400_em_portugues_e_nao_muda_a_assinatura(self):
        self.conectar()
        resposta = self.postar("/api/filtro", {"filtro": "x"})
        self.assertEqual(resposta.status_code, 400)
        corpo = resposta.get_json()
        self.assertIs(corpo["ok"], False)
        self.assertIn("monitoramento", corpo["erro"])
        self.cliente.unsubscribe.assert_not_called()
        self.cliente.subscribe.assert_not_called()
        self.assertEqual(self.estado_json()["filtro"], "monitoramento/+/+")

    def test_filtro_valido_devolve_200_e_reassina(self):
        self.conectar()
        resposta = self.postar("/api/filtro", {"filtro": "monitoramento/+/cpu"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json(), {"ok": True, "filtro": "monitoramento/+/cpu"})
        self.cliente.unsubscribe.assert_called_once_with("monitoramento/+/+")
        self.cliente.subscribe.assert_called_once_with("monitoramento/+/cpu", qos=0)
        self.assertEqual(self.estado_json()["filtro"], "monitoramento/+/cpu")

    def test_falha_do_broker_ao_assinar_tambem_e_400(self):
        self.conectar()
        self.cliente.subscribe.side_effect = [(mqtt.MQTT_ERR_QUEUE_SIZE, None), OK]
        resposta = self.postar("/api/filtro", {"filtro": "monitoramento/+/cpu"})
        self.assertEqual(resposta.status_code, 400)
        self.assertIs(resposta.get_json()["ok"], False)
        self.assertEqual(self.estado_json()["filtro"], "monitoramento/+/+")

    def test_corpo_invalido_devolve_400_em_json(self):
        casos = {
            "sem corpo": {},
            "texto que não é JSON": {"data": "isto nao e json", "content_type": "application/json"},
            "JSON que não é objeto": {"json": ["monitoramento/#"]},
            "objeto sem o campo": {"json": {"outro": 1}},
            "filtro que não é texto": {"json": {"filtro": 123}},
            "filtro nulo": {"json": {"filtro": None}},
            "filtro vazio": {"json": {"filtro": ""}},
        }
        for nome, argumentos in casos.items():
            with self.subTest(nome):
                resposta = self.http.post("/api/filtro", **argumentos)
                self.assertEqual(resposta.status_code, 400)
                self.assertTrue(resposta.is_json)
                self.assertIs(resposta.get_json()["ok"], False)
                self.assertTrue(resposta.get_json()["erro"])
        self.assertEqual(self.monitor.filtro, "monitoramento/+/+")

    def test_aceita_json_sem_cabecalho_content_type(self):
        resposta = self.http.post("/api/filtro", data=json.dumps({"filtro": "monitoramento/#"}))
        self.assertEqual(resposta.status_code, 200)

    def test_desconectado_o_filtro_novo_vale_na_reconexao(self):
        resposta = self.postar("/api/filtro", {"filtro": "monitoramento/maquina01/+"})
        self.assertEqual(resposta.status_code, 200)
        self.cliente.subscribe.assert_not_called()
        with self.assertLogs(logger, level="INFO"):
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.cliente.subscribe.assert_called_once_with("monitoramento/maquina01/+", qos=0)


class TestApiBroker(BaseApi):
    def test_porta_invalida_devolve_400_em_portugues(self):
        resposta = self.postar("/api/broker", {"host": "192.168.0.10", "porta": 99999})
        self.assertEqual(resposta.status_code, 400)
        corpo = resposta.get_json()
        self.assertIs(corpo["ok"], False)
        self.assertIn("porta", corpo["erro"].lower())
        self.cliente.connect_async.assert_not_called()
        self.assertEqual(self.estado_json()["broker"]["host"], "127.0.0.1")

    def test_host_invalido_devolve_400(self):
        for host in ["", "   ", "dois nomes", None, 5]:
            with self.subTest(host=host):
                resposta = self.postar("/api/broker", {"host": host, "porta": 1883})
                self.assertEqual(resposta.status_code, 400)
                self.assertIn("broker", resposta.get_json()["erro"])

    def test_campos_ausentes_devolvem_400(self):
        for corpo in [{}, {"host": "x"}, {"porta": 1883}]:
            with self.subTest(corpo=corpo):
                resposta = self.postar("/api/broker", corpo)
                self.assertEqual(resposta.status_code, 400)
                self.assertIs(resposta.get_json()["ok"], False)

    def test_corpo_que_nao_e_json_devolve_400(self):
        resposta = self.http.post("/api/broker", data="host=x&porta=1", content_type="application/x-www-form-urlencoded")
        self.assertEqual(resposta.status_code, 400)
        self.assertTrue(resposta.is_json)

    def test_valido_devolve_200_e_reconecta(self):
        with self.assertLogs(logger, level="INFO"):
            resposta = self.postar("/api/broker", {"host": "192.168.0.10", "porta": 1884})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.get_json(), {"ok": True, "host": "192.168.0.10", "porta": 1884})
        self.cliente.connect_async.assert_called_once_with("192.168.0.10", 1884, keepalive=60)
        self.cliente.loop_start.assert_called_once()
        broker = self.estado_json()["broker"]
        self.assertEqual((broker["host"], broker["porta"], broker["erro"]), ("192.168.0.10", 1884, None))

    def test_reconectar_mantem_o_filtro_atual_na_nova_assinatura(self):
        with self.assertLogs(logger, level="INFO"):
            self.postar("/api/filtro", {"filtro": "monitoramento/+/memoria"})
            self.postar("/api/broker", {"host": "novo.local", "porta": 1883})
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.cliente.subscribe.assert_called_with("monitoramento/+/memoria", qos=0)


class TestErrosSempreJson(BaseApi):
    def confere_envelope(self, resposta, codigo):
        self.assertEqual(resposta.status_code, codigo)
        self.assertTrue(resposta.is_json, resposta.get_data(as_text=True))
        corpo = resposta.get_json()
        self.assertIs(corpo["ok"], False)
        self.assertIsInstance(corpo["erro"], str)
        self.assertTrue(corpo["erro"])
        self.assertNotIn("<html", resposta.get_data(as_text=True).lower())
        return corpo

    def test_404_em_rota_inexistente(self):
        corpo = self.confere_envelope(self.http.get("/api/nao-existe"), 404)
        self.assertIn("/api/nao-existe", corpo["erro"])

    def test_404_em_subrota_e_em_post(self):
        self.confere_envelope(self.http.get("/api/estado/extra"), 404)
        self.confere_envelope(self.http.post("/api/nao-existe", json={}), 404)
        self.confere_envelope(self.http.get("/api/"), 404)

    def test_405_em_metodo_errado(self):
        self.confere_envelope(self.http.post("/api/estado", json={}), 405)
        self.confere_envelope(self.http.delete("/api/historico"), 405)
        self.confere_envelope(self.http.get("/api/filtro"), 405)
        self.confere_envelope(self.http.put("/api/broker", json={}), 405)

    def test_500_em_erro_inesperado_tambem_e_json(self):
        with patch.object(self.monitor, "contadores", side_effect=RuntimeError("quebrou")):
            with self.assertLogs(logger, level="ERROR") as capturado, self.assertLogs(self.app.logger, level="ERROR"):
                resposta = self.http.get("/api/estado")
        corpo = self.confere_envelope(resposta, 500)
        self.assertNotIn("quebrou", corpo["erro"])  # detalhes internos não vão para a tela
        self.assertTrue(any("quebrou" in linha for linha in capturado.output))

    def test_500_em_post_tambem_e_json(self):
        with patch.object(self.monitor, "alterar_filtro", side_effect=RuntimeError("quebrou")):
            with self.assertLogs(logger, level="ERROR"), self.assertLogs(self.app.logger, level="ERROR"):
                resposta = self.postar("/api/filtro", {"filtro": "monitoramento/#"})
        self.confere_envelope(resposta, 500)

    def test_500_tambem_com_modo_de_teste_ligado(self):
        # Com app.testing = True o Flask costuma repassar a exceção; a API não pode depender disso
        self.app.testing = True
        with patch.object(self.monitor, "contadores", side_effect=RuntimeError("quebrou")):
            with self.assertLogs(logger, level="ERROR"), self.assertLogs(self.app.logger, level="ERROR"):
                resposta = self.http.get("/api/estado")
        self.confere_envelope(resposta, 500)

    def test_erro_de_validacao_no_estado_nao_e_mascarado_como_400(self):
        # ValueError só vira 400 nas rotas POST; num GET é bug e deve ser 500
        with patch.object(self.monitor, "contadores", side_effect=ValueError("bug")):
            with self.assertLogs(logger, level="ERROR"), self.assertLogs(self.app.logger, level="ERROR"):
                resposta = self.http.get("/api/estado")
        self.confere_envelope(resposta, 500)

    def test_metodo_errado_em_pagina_nao_e_json(self):
        resposta = self.http.post("/index.html")
        self.assertEqual(resposta.status_code, 405)
        self.assertFalse(resposta.is_json)

    def test_404_de_pagina_fora_da_api_nao_e_json(self):
        resposta = self.http.get("/nao-existe.html")
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(resposta.is_json)


class TestArquivosEstaticos(BaseApi):
    def obter(self, url, cliente=None):
        # Lê e fecha a resposta, senão o arquivo servido fica aberto até o fim do teste
        resposta = (cliente or self.http).get(url)
        resposta.get_data()
        resposta.close()
        return resposta

    def test_raiz_devolve_index_html_sem_cache(self):
        resposta = self.obter("/")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Painel", resposta.get_data(as_text=True))
        self.assertIn("text/html", resposta.headers["Content-Type"])
        self.assertEqual(resposta.headers["Cache-Control"], "no-store")

    def test_index_html_direto(self):
        self.assertEqual(self.obter("/index.html").status_code, 200)

    def test_arquivos_da_pasta_web_e_subpastas(self):
        js = self.obter("/app.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("javascript", js.headers["Content-Type"])
        self.assertEqual(self.obter("/vendor/lib.js").status_code, 200)

    def test_nao_sai_da_pasta_web(self):
        for caminho in ["/../segredo.txt", "/%2e%2e/segredo.txt", "/vendor/../../segredo.txt", "/..%2fsegredo.txt"]:
            with self.subTest(caminho=caminho):
                resposta = self.http.get(caminho)
                self.assertEqual(resposta.status_code, 404)
                self.assertNotIn("fora da pasta web", resposta.get_data(as_text=True))

    def test_pasta_web_relativa_e_procurada_na_raiz_do_projeto(self):
        # O repositório tem web/vendor/chart.umd.min.js (Pessoa 1); index.html é da Pessoa 3
        app = criar_app(self.monitor)
        resposta = self.obter("/vendor/chart.umd.min.js", app.test_client())
        self.assertEqual(resposta.status_code, 200)

    def test_sem_index_html_a_raiz_da_404(self):
        with tempfile.TemporaryDirectory() as vazia:
            resposta = self.obter("/", criar_app(self.monitor, vazia).test_client())
        self.assertEqual(resposta.status_code, 404)


class TestLinhaDeComando(unittest.TestCase):
    def test_padroes(self):
        args = ler_argumentos([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.porta, 1883)
        self.assertEqual(args.web_host, "0.0.0.0")
        self.assertEqual(args.web_porta, 8080)
        self.assertEqual(args.filtro, "monitoramento/+/+")
        self.assertEqual(args.timeout_agente, 15.0)
        self.assertEqual(args.log, "monitor.log")

    def test_valores_informados(self):
        args = ler_argumentos([
            "--host", "192.168.0.10", "--porta", "1884", "--web-host", "127.0.0.1",
            "--web-porta", "9000", "--filtro", "monitoramento/+/cpu",
            "--timeout-agente", "30", "--log", "x.log",
        ])
        self.assertEqual((args.host, args.porta), ("192.168.0.10", 1884))
        self.assertEqual((args.web_host, args.web_porta), ("127.0.0.1", 9000))
        self.assertEqual(args.filtro, "monitoramento/+/cpu")
        self.assertEqual(args.timeout_agente, 30.0)

    def test_timeout_minimo_e_dois_segundos(self):
        self.assertEqual(ler_argumentos(["--timeout-agente", "2"]).timeout_agente, 2.0)
        for valor in ["1.9", "0", "-5", "abc"]:
            with self.subTest(valor=valor), self.assertRaises(SystemExit):
                with patch("sys.stderr"):
                    ler_argumentos(["--timeout-agente", valor])

    def test_porta_invalida(self):
        for opcao in ["--porta", "--web-porta"]:
            for valor in ["0", "70000", "abc"]:
                with self.subTest(opcao=opcao, valor=valor), self.assertRaises(SystemExit):
                    with patch("sys.stderr"):
                        ler_argumentos([opcao, valor])

    def test_filtro_inicial_invalido_e_rejeitado_ao_subir(self):
        with self.assertRaises(SystemExit), patch("sys.stderr") as erro:
            ler_argumentos(["--filtro", "x"])
        escrito = "".join(c.args[0] for c in erro.write.call_args_list)
        self.assertIn("--filtro", escrito)

    def test_urls_de_acesso(self):
        self.assertEqual(_urls_de_acesso("127.0.0.1", 8080), ["http://127.0.0.1:8080"])
        with patch("server.dashboard._ip_da_rede", return_value="192.168.0.5"):
            self.assertEqual(
                _urls_de_acesso("0.0.0.0", 8080),
                ["http://localhost:8080", "http://192.168.0.5:8080"],
            )
        with patch("server.dashboard._ip_da_rede", return_value=None):
            self.assertEqual(_urls_de_acesso("0.0.0.0", 9000), ["http://localhost:9000"])


if __name__ == "__main__":
    unittest.main()