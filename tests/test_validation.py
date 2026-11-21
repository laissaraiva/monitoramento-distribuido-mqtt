import json
import unittest
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

from agent.publisher import montar_payload_cpu, montar_payload_memoria, montar_topico
from common.validation import (
    TAMANHO_MAXIMO_PAYLOAD_BYTES,
    ErroValidacaoProtocolo,
    validar_id_maquina,
    validar_mensagem_mqtt,
    validar_payload_cpu,
    validar_payload_memoria,
    validar_timestamp,
    validar_topico,
)
from server.subscriber import MonitorCentral

TS = "2026-11-21T12:00:00-03:00"
TOPICO_CPU = "monitoramento/maquina01/cpu"
TOPICO_MEMORIA = "monitoramento/maquina01/memoria"


def cpu(valor=25.5, timestamp=TS, **extras):
    return {"valor": valor, "unidade": "%", "timestamp": timestamp, **extras}


def memoria(valor=4096.0, timestamp=TS, **extras):
    return {"valor": valor, "unidade": "MB", "timestamp": timestamp, **extras}


def memoria_completa(valor=4096.0, total=8192.0, livre=4096.0, percentual=50.0):
    return memoria(valor, detalhes={"total": total, "livre": livre, "percentual": percentual})


def como_bytes(payload):
    return json.dumps(payload).encode("utf-8")


class TestIdMaquina(unittest.TestCase):
    def test_ids_validos(self):
        for id_maquina in ("maquina01", "pc-lab-02", "ubuntu_node_1", "m1", "A9", "a" * 64):
            with self.subTest(id_maquina=id_maquina):
                resultado = validar_id_maquina(id_maquina)
                self.assertTrue(resultado.valido, resultado.erro)
                self.assertEqual(resultado.dados["id_maquina"], id_maquina)

    def test_ids_invalidos(self):
        casos = [
            "",
            "a",
            "a" * 65,
            "maquina/01",
            "maquina+1",
            "#",
            "maquina#1",
            "maquina 01",
            "maquina01\n",
            "\tmaquina01",
            "-maquina01",
            "maquina01-",
            "_maquina01",
            "maquina01_",
            "máquina01",
            "maquina.01",
            "maquina\x0001",
            "maquina٠١",
        ]
        for id_maquina in casos:
            with self.subTest(id_maquina=id_maquina):
                resultado = validar_id_maquina(id_maquina)
                self.assertFalse(resultado.valido)
                self.assertTrue(resultado.erro)

    def test_id_com_tipo_incorreto(self):
        for id_maquina in (None, 1, 1.5, True, b"maquina01", ["maquina01"], {"id": "maquina01"}):
            with self.subTest(id_maquina=id_maquina):
                resultado = validar_id_maquina(id_maquina)
                self.assertFalse(resultado.valido)
                self.assertIn("string", resultado.erro)


class TestTopico(unittest.TestCase):
    def test_topicos_validos(self):
        for topico, id_maquina, metrica in (
            ("monitoramento/maquina01/cpu", "maquina01", "cpu"),
            ("monitoramento/pc-lab-02/memoria", "pc-lab-02", "memoria"),
        ):
            with self.subTest(topico=topico):
                resultado = validar_topico(topico)
                self.assertTrue(resultado.valido, resultado.erro)
                self.assertEqual(resultado.dados["id_maquina"], id_maquina)
                self.assertEqual(resultado.dados["metrica"], metrica)

    def test_topicos_fora_do_padrao(self):
        casos = [
            "",
            "monitoramento",
            "monitoramento/maquina01",
            "monitoramento/maquina01/cpu/extra",
            "monitoramento/maquina01/cpu/",
            "/monitoramento/maquina01/cpu",
            "Monitoramento/maquina01/cpu",
            "monitor/maquina01/cpu",
            "monitoramento//cpu",
            "monitoramento/maquina01/",
            "monitoramento/maquina01/CPU",
            "monitoramento/maquina01/disco",
            "monitoramento/maquina01/cpu ",
            "monitoramento/+/cpu",
            "monitoramento/maquina01/#",
            "monitoramento/#",
            "monitoramento/maquina 01/cpu",
            "monitoramento/-maquina/cpu",
            "$SYS/maquina01/cpu",
        ]
        for topico in casos:
            with self.subTest(topico=topico):
                resultado = validar_topico(topico)
                self.assertFalse(resultado.valido)
                self.assertTrue(resultado.erro)

    def test_topico_com_tipo_incorreto(self):
        for topico in (None, 123, b"monitoramento/maquina01/cpu"):
            with self.subTest(topico=topico):
                self.assertFalse(validar_topico(topico).valido)


class TestTimestamp(unittest.TestCase):
    def test_timestamps_validos(self):
        casos = {
            "2026-11-16T22:00:00-03:00": datetime(2026, 11, 16, 22, tzinfo=timezone(timedelta(hours=-3))),
            "2026-11-17T01:00:00Z": datetime(2026, 11, 17, 1, tzinfo=timezone.utc),
            "2026-11-17T01:00:00+00:00": datetime(2026, 11, 17, 1, tzinfo=timezone.utc),
            "2026-11-16T22:00:00.5-03:00": datetime(
                2026, 11, 16, 22, 0, 0, 500000, tzinfo=timezone(timedelta(hours=-3))
            ),
            "2026-11-16T22:00:00.123456+05:30": datetime(
                2026, 11, 16, 22, 0, 0, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30))
            ),
            "2024-02-29T23:59:59+14:00": datetime(
                2024, 2, 29, 23, 59, 59, tzinfo=timezone(timedelta(hours=14))
            ),
            "2026-01-01T00:00:00-12:00": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-12))),
        }
        for timestamp, esperado in casos.items():
            with self.subTest(timestamp=timestamp):
                resultado = validar_timestamp(timestamp)
                self.assertTrue(resultado.valido, resultado.erro)
                self.assertEqual(resultado.dados["datetime"], esperado)
                self.assertEqual(resultado.dados["datetime"].utcoffset(), esperado.utcoffset())

    def test_timestamps_invalidos(self):
        casos = [
            "",
            " ",
            "2026-11-16T22:00:00",
            "2026-11-16",
            "22:00:00-03:00",
            "16/11/2026 22:00:00",
            "2026-11-16 22:00:00-03:00",
            "2026-11-16t22:00:00Z",
            "2026-11-16T22:00:00z",
            " 2026-11-16T22:00:00Z",
            "2026-11-16T22:00:00Z ",
            "2026-11-16T22:00Z",
            "2026-11-16T22Z",
            "2026-11-16T22:00:00-0300",
            "2026-11-16T22:00:00-03",
            "2026-11-16T22:00:00,5Z",
            "2026-11-16T22:00:00.1234567Z",
            "20261116T220000Z",
            "2026-W47-1T22:00:00Z",
            "2026-13-01T00:00:00Z",
            "2026-00-10T00:00:00Z",
            "2026-02-30T00:00:00Z",
            "2025-02-29T00:00:00Z",
            "2026-11-16T24:00:00Z",
            "2026-11-16T22:60:00Z",
            "2026-11-16T22:00:60Z",
            "2026-11-16T22:00:00+15:00",
            "2026-11-16T22:00:00-03:60",
            "0000-01-01T00:00:00Z",
            "٢٠٢٦-11-16T22:00:00Z",
            "agora",
        ]
        for timestamp in casos:
            with self.subTest(timestamp=timestamp):
                resultado = validar_timestamp(timestamp)
                self.assertFalse(resultado.valido)
                self.assertTrue(resultado.erro)

    def test_timestamp_com_tipo_incorreto(self):
        for timestamp in (None, 1763337600, 1763337600.0, True, ["2026-11-16T22:00:00Z"]):
            with self.subTest(timestamp=timestamp):
                self.assertFalse(validar_timestamp(timestamp).valido)


class TestPayloadCpu(unittest.TestCase):
    def test_formatos_minimo_e_estendido(self):
        for payload in (
            cpu(),
            cpu(25),
            cpu(32.4, detalhes={"por_nucleo": [28.0, 35.2, 31.4, 35.0]}),
            cpu(detalhes={}),
            cpu(detalhes=None),
            cpu(detalhes={"por_nucleo": None}),
        ):
            with self.subTest(payload=payload):
                resultado = validar_payload_cpu(payload)
                self.assertTrue(resultado.valido, resultado.erro)

    def test_limites_da_faixa(self):
        for valor in (0, 0.0, 100, 100.0, 0.1, 99.9):
            with self.subTest(valor=valor):
                self.assertTrue(validar_payload_cpu(cpu(valor)).valido)

    def test_cpu_negativa_ou_acima_de_100(self):
        for valor in (-0.1, -1, -100, 100.1, 101, 112.5, 1e9):
            with self.subTest(valor=valor):
                resultado = validar_payload_cpu(cpu(valor))
                self.assertFalse(resultado.valido)
                self.assertIn("fora da faixa", resultado.erro)

    def test_valor_com_tipo_incorreto(self):
        for valor in ("25.5", "", None, True, False, [25.5], {"v": 25.5}, float("nan"), float("inf"), -float("inf"), 10 ** 400):
            with self.subTest(valor=valor):
                resultado = validar_payload_cpu(cpu(valor))
                self.assertFalse(resultado.valido)
                self.assertIn("valor", resultado.erro)

    def test_unidade_incorreta(self):
        for unidade in ("MB", "%%", " %", "percent", "", None, 1):
            with self.subTest(unidade=unidade):
                payload = cpu()
                payload["unidade"] = unidade
                resultado = validar_payload_cpu(payload)
                self.assertFalse(resultado.valido)
                self.assertIn("Unidade", resultado.erro)

    def test_campos_obrigatorios_ausentes(self):
        for campo in ("valor", "unidade", "timestamp"):
            with self.subTest(campo=campo):
                payload = cpu()
                del payload[campo]
                resultado = validar_payload_cpu(payload)
                self.assertFalse(resultado.valido)
                self.assertIn(campo, resultado.erro)

    def test_campo_desconhecido_na_raiz(self):
        resultado = validar_payload_cpu(cpu(id_maquina="maquina01"))
        self.assertFalse(resultado.valido)
        self.assertIn("id_maquina", resultado.erro)

    def test_payload_que_nao_e_objeto(self):
        for payload in (None, [], [cpu()], "texto", 25.5):
            with self.subTest(payload=payload):
                self.assertFalse(validar_payload_cpu(payload).valido)

    def test_detalhes_invalidos(self):
        casos = [
            cpu(detalhes=[10.0]),
            cpu(detalhes="por_nucleo"),
            cpu(detalhes={"total": 10}),
            cpu(detalhes={"por_nucleo": []}),
            cpu(detalhes={"por_nucleo": 25.5}),
            cpu(detalhes={"por_nucleo": [25.5, "30"]}),
            cpu(detalhes={"por_nucleo": [25.5, None]}),
            cpu(detalhes={"por_nucleo": [25.5, True]}),
            cpu(50.0, detalhes={"por_nucleo": [-1.0, 101.0]}),
            cpu(50.0, detalhes={"por_nucleo": [50.0, 100.5]}),
        ]
        for payload in casos:
            with self.subTest(detalhes=payload["detalhes"]):
                self.assertFalse(validar_payload_cpu(payload).valido)

    def test_media_dos_nucleos_incompativel_com_valor(self):
        self.assertTrue(validar_payload_cpu(cpu(30.0, detalhes={"por_nucleo": [20.0, 40.0]})).valido)
        self.assertTrue(validar_payload_cpu(cpu(31.0, detalhes={"por_nucleo": [20.0, 40.0]})).valido)
        resultado = validar_payload_cpu(cpu(5.0, detalhes={"por_nucleo": [90.0, 95.0]}))
        self.assertFalse(resultado.valido)
        self.assertIn("Inconsistência", resultado.erro)
        self.assertFalse(validar_payload_cpu(cpu(31.5, detalhes={"por_nucleo": [20.0, 40.0]})).valido)


class TestPayloadMemoria(unittest.TestCase):
    def test_formatos_minimo_e_estendido(self):
        for payload in (
            memoria(8192),
            memoria(0),
            memoria(6144.5, detalhes={"total": 16384.0, "livre": 10239.5, "percentual": 37.5}),
            memoria(4096.0, detalhes={"total": 8192.0}),
            memoria(4096.0, detalhes={"livre": 4096.0}),
            memoria(4096.0, detalhes={"percentual": 50.0}),
            memoria(4096.0, detalhes={}),
            memoria_completa(8192.0, 8192.0, 0.0, 100.0),
            memoria_completa(0.0, 8192.0, 8192.0, 0.0),
        ):
            with self.subTest(payload=payload):
                resultado = validar_payload_memoria(payload)
                self.assertTrue(resultado.valido, resultado.erro)

    def test_valores_invalidos(self):
        casos = [
            memoria(-0.1),
            memoria(-512),
            memoria("4096"),
            memoria(None),
            memoria(True),
            memoria(float("nan")),
            memoria(float("inf")),
            memoria(10 ** 400),
        ]
        for payload in casos:
            with self.subTest(valor=payload["valor"]):
                self.assertFalse(validar_payload_memoria(payload).valido)

    def test_unidade_incorreta(self):
        for unidade in ("%", "mb", "Mb", "GB", "KB", "B", "MiB", "", None):
            with self.subTest(unidade=unidade):
                payload = memoria()
                payload["unidade"] = unidade
                resultado = validar_payload_memoria(payload)
                self.assertFalse(resultado.valido)
                self.assertIn("Unidade", resultado.erro)

    def test_detalhes_invalidos(self):
        casos = [
            memoria(detalhes=[8192]),
            memoria(detalhes={"por_nucleo": [10.0]}),
            memoria(detalhes={"total": 0}),
            memoria(detalhes={"total": -8192}),
            memoria(detalhes={"total": "8192"}),
            memoria(detalhes={"total": True}),
            memoria(detalhes={"livre": -1}),
            memoria(detalhes={"livre": "100"}),
            memoria(detalhes={"percentual": -0.1}),
            memoria(detalhes={"percentual": 100.1}),
            memoria(detalhes={"percentual": "50"}),
        ]
        for payload in casos:
            with self.subTest(detalhes=payload["detalhes"]):
                self.assertFalse(validar_payload_memoria(payload).valido)

    def test_dados_incompativeis_entre_si(self):
        casos = [
            memoria(18000, detalhes={"total": 16384, "livre": 0}),
            memoria(100, detalhes={"total": 8192, "livre": 9000}),
            memoria_completa(6000.0, 8192.0, 6000.0, 73.2),
            memoria_completa(1000.0, 8000.0, 7000.0, 99.0),
            memoria_completa(4096.0, 8192.0, 4096.0, 51.1),
        ]
        for payload in casos:
            with self.subTest(detalhes=payload["detalhes"]):
                resultado = validar_payload_memoria(payload)
                self.assertFalse(resultado.valido)
                self.assertIn("Inconsistência", resultado.erro)

    def test_tolerancia_de_arredondamento(self):
        self.assertTrue(validar_payload_memoria(memoria_completa(4096.0, 8192.0, 4096.0, 51.0)).valido)
        self.assertTrue(validar_payload_memoria(memoria_completa(474.6, 16087.6, 15613.0, 3.0)).valido)
        self.assertTrue(validar_payload_memoria(memoria_completa(4096.0, 8192.0, 4177.0, 50.0)).valido)


class TestMensagemMqtt(unittest.TestCase):
    def test_mensagens_validas_em_todos_os_formatos(self):
        payload = cpu(42.0)
        for bruto in (payload, json.dumps(payload), como_bytes(payload), bytearray(como_bytes(payload))):
            with self.subTest(tipo=type(bruto).__name__):
                resultado = validar_mensagem_mqtt(TOPICO_CPU, bruto)
                self.assertTrue(resultado.valido, resultado.erro)
                self.assertEqual(resultado.dados["id_maquina"], "maquina01")
                self.assertEqual(resultado.dados["metrica"], "cpu")
                self.assertEqual(resultado.dados["payload"]["valor"], 42.0)
                self.assertIsInstance(resultado.dados["datetime"], datetime)

    def test_payload_utf8_com_acentos(self):
        bruto = '{"valor": 1, "unidade": "%", "timestamp": "%s"}'.replace("%s", TS).encode("utf-8")
        self.assertTrue(validar_mensagem_mqtt(TOPICO_CPU, bruto).valido)
        acentuado = json.dumps({**cpu(), "observação": "ç"}, ensure_ascii=False).encode("utf-8")
        resultado = validar_mensagem_mqtt(TOPICO_CPU, acentuado)
        self.assertFalse(resultado.valido)
        self.assertIn("observação", resultado.erro)

    def test_metrica_do_topico_define_regras_do_payload(self):
        self.assertFalse(validar_mensagem_mqtt(TOPICO_CPU, como_bytes(memoria())).valido)
        self.assertFalse(validar_mensagem_mqtt(TOPICO_MEMORIA, como_bytes(cpu())).valido)
        self.assertTrue(validar_mensagem_mqtt(TOPICO_MEMORIA, como_bytes(memoria())).valido)

    def test_topico_invalido_rejeita_antes_do_payload(self):
        resultado = validar_mensagem_mqtt("monitoramento/-maquina01/cpu", b"{malformado")
        self.assertFalse(resultado.valido)
        self.assertIn("id_maquina", resultado.erro)
        resultado = validar_mensagem_mqtt("monitoramento/maquina+01/cpu", b"{malformado")
        self.assertFalse(resultado.valido)
        self.assertIn("wildcards", resultado.erro)

    def test_json_malformado(self):
        casos = [
            b"",
            b" ",
            b"{",
            b'{"valor": 25.5, "unidade": "%", "timestamp":',
            b"{'valor': 25.5}",
            b'{"valor": 25.5,}',
            b"valor=25.5",
            b"\xef\xbb\xbf" + como_bytes(cpu()),
            como_bytes(cpu()) + b" lixo",
        ]
        for bruto in casos:
            with self.subTest(bruto=bruto[:40]):
                resultado = validar_mensagem_mqtt(TOPICO_CPU, bruto)
                self.assertFalse(resultado.valido)
                self.assertIn("JSON", resultado.erro)

    def test_payload_que_nao_e_utf8(self):
        resultado = validar_mensagem_mqtt(TOPICO_CPU, b"\xff\xfe\x00{")
        self.assertFalse(resultado.valido)
        self.assertIn("UTF-8", resultado.erro)

    def test_raiz_json_que_nao_e_objeto(self):
        for bruto in (b"null", b"25.5", b'"texto"', b"[]", b"true", como_bytes([cpu()])):
            with self.subTest(bruto=bruto):
                self.assertFalse(validar_mensagem_mqtt(TOPICO_CPU, bruto).valido)

    def test_constantes_nao_padronizadas(self):
        for constante in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(constante=constante):
                bruto = b'{"valor": ' + constante + b', "unidade": "%", "timestamp": "' + TS.encode() + b'"}'
                resultado = validar_mensagem_mqtt(TOPICO_CPU, bruto)
                self.assertFalse(resultado.valido)
                self.assertIn("JSON", resultado.erro)

    def test_numero_acima_da_precisao_de_float(self):
        for literal in (b"1e400", b"1" + b"0" * 400):
            with self.subTest(literal=literal[:10]):
                bruto = b'{"valor": ' + literal + b', "unidade": "%", "timestamp": "' + TS.encode() + b'"}'
                self.assertFalse(validar_mensagem_mqtt(TOPICO_CPU, bruto).valido)

    def test_chaves_duplicadas(self):
        casos = [
            b'{"valor": 99, "valor": 10, "unidade": "%", "timestamp": "' + TS.encode() + b'"}',
            b'{"valor": 30, "unidade": "%", "timestamp": "' + TS.encode()
            + b'", "detalhes": {"por_nucleo": [30], "por_nucleo": [30]}}',
        ]
        for bruto in casos:
            with self.subTest(bruto=bruto[:30]):
                resultado = validar_mensagem_mqtt(TOPICO_CPU, bruto)
                self.assertFalse(resultado.valido)
                self.assertIn("duplicada", resultado.erro)

    def test_json_aninhado_em_profundidade(self):
        bruto = b'{"valor": ' + b"[" * 20000 + b"]" * 20000 + b"}"
        resultado = validar_mensagem_mqtt(TOPICO_CPU, bruto)
        self.assertFalse(resultado.valido)
        self.assertIn("JSON", resultado.erro)

    def test_payload_acima_do_tamanho_maximo(self):
        nucleos = [1.0] * (TAMANHO_MAXIMO_PAYLOAD_BYTES // 4)
        bruto = como_bytes(cpu(1.0, detalhes={"por_nucleo": nucleos}))
        for formato in (bruto, bruto.decode("utf-8")):
            with self.subTest(tipo=type(formato).__name__):
                resultado = validar_mensagem_mqtt(TOPICO_CPU, formato)
                self.assertFalse(resultado.valido)
                self.assertIn("tamanho máximo", resultado.erro)

    def test_tipo_de_payload_nao_suportado(self):
        for bruto in (None, 25.5, [cpu()]):
            with self.subTest(bruto=bruto):
                self.assertFalse(validar_mensagem_mqtt(TOPICO_CPU, bruto).valido)

    def test_lancar_excecao(self):
        self.assertTrue(validar_mensagem_mqtt(TOPICO_CPU, cpu(), lancar_excecao=True).valido)
        for topico, bruto in (
            ("monitoramento/maquina01/disco", cpu()),
            (TOPICO_CPU, b"\xff"),
            (TOPICO_CPU, b"{"),
            (TOPICO_CPU, b"[" * 20000),
            (TOPICO_CPU, b" " * (TAMANHO_MAXIMO_PAYLOAD_BYTES + 1)),
            (TOPICO_CPU, cpu(150)),
            (TOPICO_CPU, None),
        ):
            with self.subTest(topico=topico, bruto=repr(bruto)[:30]):
                with self.assertRaises(ErroValidacaoProtocolo):
                    validar_mensagem_mqtt(topico, bruto, lancar_excecao=True)

    def test_entradas_hostis_nunca_lancam_excecao(self):
        casos = [
            b"\x00" * 64,
            b"[" * 60000,
            b"{" * 60000,
            b'{"valor": ' + b"9" * 4000 + b', "unidade": "%", "timestamp": "' + TS.encode() + b'"}',
            b'{"valor": ' + b"9" * 5000 + b"}",
            b'{"valor": 1e999999, "unidade": "%", "timestamp": "' + TS.encode() + b'"}',
            como_bytes({"valor": 1, "unidade": "%", "timestamp": TS, "detalhes": {"por_nucleo": [[1]]}}),
            como_bytes({"valor": {}, "unidade": {}, "timestamp": {}}),
            como_bytes({"valor": 1, "unidade": "%", "timestamp": "9" * 1000}),
            "\ud800".encode("utf-8", errors="surrogatepass"),
        ]
        for bruto in casos:
            for topico in (TOPICO_CPU, TOPICO_MEMORIA):
                with self.subTest(topico=topico, bruto=bruto[:20]):
                    try:
                        resultado = validar_mensagem_mqtt(topico, bruto)
                    except Exception as exc:
                        self.fail(f"validar_mensagem_mqtt lançou {type(exc).__name__}: {exc}")
                    self.assertFalse(resultado.valido)

    def test_mensagem_de_erro_resume_valores_extensos(self):
        resultado = validar_mensagem_mqtt(TOPICO_CPU, cpu("x" * 5000))
        self.assertFalse(resultado.valido)
        self.assertLess(len(resultado.erro), 300)


class TestCompatibilidadeComAgente(unittest.TestCase):
    def test_payloads_montados_pelo_publisher(self):
        cpu_coletada = {"percentual": 37.5, "por_nucleo": [30.0, 45.0, 35.0, 40.0]}
        memoria_coletada = {"utilizada": 6144.5, "total": 16384.0, "livre": 10239.5, "percentual": 37.5}
        for metrica, payload in (
            ("cpu", montar_payload_cpu(cpu_coletada, TS)),
            ("memoria", montar_payload_memoria(memoria_coletada, TS)),
        ):
            with self.subTest(metrica=metrica):
                bruto = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                resultado = validar_mensagem_mqtt(montar_topico("pc-lab-02", metrica), bruto)
                self.assertTrue(resultado.valido, resultado.erro)

    def test_timestamp_gerado_pelo_coletor(self):
        from agent.collector import timestamp_atual

        resultado = validar_timestamp(timestamp_atual())
        self.assertTrue(resultado.valido, resultado.erro)


class TestRejeicaoSemAlterarEstado(unittest.TestCase):
    def setUp(self):
        self.monitor = MonitorCentral()

    def receber(self, topico, payload):
        mensagem = mqtt.MQTTMessage(topic=topico.encode("utf-8"))
        mensagem.payload = payload if isinstance(payload, bytes) else como_bytes(payload)
        self.monitor._ao_receber(None, None, mensagem)

    def receber_invalida(self, topico, payload):
        with self.assertLogs("monitor", level="WARNING") as registros:
            self.receber(topico, payload)
        self.assertTrue(any("descartada" in linha for linha in registros.output))

    def popular_estado(self):
        self.receber("monitoramento/maquina01/cpu", cpu(30.0, detalhes={"por_nucleo": [25.0, 35.0]}))
        self.receber("monitoramento/maquina01/memoria", memoria_completa())
        self.receber("monitoramento/maquina02/cpu", cpu(70.0))
        return self.monitor.estado.snapshot()

    def mensagens_invalidas(self):
        return [
            ("monitoramento/maquina01/cpu", cpu(-5.0)),
            ("monitoramento/maquina01/cpu", cpu(150.0)),
            ("monitoramento/maquina01/cpu", cpu("50")),
            ("monitoramento/maquina01/cpu", cpu(True)),
            ("monitoramento/maquina01/cpu", cpu(50.0, timestamp="2026-11-21T12:00:00")),
            ("monitoramento/maquina01/cpu", cpu(50.0, timestamp="21/11/2026 12:00")),
            ("monitoramento/maquina01/cpu", {"valor": 50.0, "unidade": "%"}),
            ("monitoramento/maquina01/cpu", {"unidade": "%", "timestamp": TS}),
            ("monitoramento/maquina01/cpu", cpu(50.0, detalhes={"por_nucleo": [90.0, 95.0]})),
            ("monitoramento/maquina01/cpu", memoria()),
            ("monitoramento/maquina01/memoria", memoria(-1.0)),
            ("monitoramento/maquina01/memoria", memoria(9000.0, detalhes={"total": 8192.0})),
            ("monitoramento/maquina01/memoria", memoria_completa(4096.0, 8192.0, 4096.0, 90.0)),
            ("monitoramento/maquina01/memoria", cpu()),
            ("monitoramento/maquina01/cpu", b"{malformado"),
            ("monitoramento/maquina01/cpu", b""),
            ("monitoramento/maquina01/cpu", b"\xff\xfe"),
            ("monitoramento/maquina01/cpu", b'{"valor": 99, "valor": 10, "unidade": "%", "timestamp": "' + TS.encode() + b'"}'),
            ("monitoramento/maquina01/cpu", b'{"valor": 1' + b"0" * 400 + b', "unidade": "%", "timestamp": "' + TS.encode() + b'"}'),
            ("monitoramento/maquina01/cpu", b"[" * 60000),
            ("monitoramento/maquina01/disco", cpu()),
            ("monitoramento/maquina01/cpu/extra", cpu()),
            ("monitoramento/maquina 03/cpu", cpu()),
            ("monitoramento/-maquina03/cpu", cpu()),
            ("monitoramento/maquina03", cpu()),
            ("outro/maquina03/cpu", cpu()),
        ]

    def test_mensagens_invalidas_nao_alteram_estado(self):
        antes = self.popular_estado()
        invalidas = self.mensagens_invalidas()
        for topico, payload in invalidas:
            with self.subTest(topico=topico, payload=repr(payload)[:40]):
                self.receber_invalida(topico, payload)
                self.assertEqual(self.monitor.estado.snapshot(), antes)
        self.assertEqual(self.monitor.estado.total_maquinas(), 2)
        self.assertEqual(self.monitor.mensagens_recebidas, 3 + len(invalidas))
        self.assertEqual(self.monitor.mensagens_descartadas, len(invalidas))

    def test_mensagem_invalida_nao_registra_maquina_nova(self):
        for topico, payload in (
            ("monitoramento/maquina09/cpu", cpu(101.0)),
            ("monitoramento/maquina09/memoria", b"{"),
            ("monitoramento/maquina09/cpu", cpu(timestamp="")),
        ):
            with self.subTest(topico=topico):
                self.receber_invalida(topico, payload)
        self.assertEqual(self.monitor.estado.total_maquinas(), 0)
        self.assertIsNone(self.monitor.estado.obter("maquina09"))

    def test_mensagem_valida_apos_invalidas_continua_sendo_aplicada(self):
        self.popular_estado()
        for topico, payload in self.mensagens_invalidas():
            with self.subTest(topico=topico, payload=repr(payload)[:40]):
                self.receber_invalida(topico, payload)
        self.receber("monitoramento/maquina01/cpu", cpu(55.0))
        leitura = self.monitor.estado.obter_metrica("maquina01", "cpu")
        self.assertEqual(leitura.valor, 55.0)
        self.assertEqual(self.monitor.estado.obter_metrica("maquina01", "memoria").valor, 4096.0)


if __name__ == "__main__":
    unittest.main()
