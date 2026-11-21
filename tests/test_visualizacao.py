import io
import json
import logging
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from server.state import EstadoCentral
from server.subscriber import (
    LIMPAR_TELA,
    HandlerEventos,
    MonitorCentral,
    configurar_logs,
    formatar_idade,
    formatar_tabela,
    ler_argumentos,
    logger,
    logger_mensagens,
)

FUSO = timezone(timedelta(hours=-3))
T0 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=FUSO)
TS = "2026-11-21T12:00:00-03:00"


def cpu(valor=10.0):
    return {"valor": valor, "unidade": "%", "timestamp": TS}


def mem(valor=4096.0, percentual=None):
    payload = {"valor": valor, "unidade": "MB", "timestamp": TS}
    if percentual is not None:
        payload["detalhes"] = {"total": 8192.0, "livre": 8192.0 - valor, "percentual": percentual}
    return payload


def mensagem(topico, payload):
    dados = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return SimpleNamespace(topic=topico, payload=dados)


class TestFormatarIdade(unittest.TestCase):
    def test_faixas(self):
        casos = {
            0: "há 0s",
            5: "há 5s",
            59: "há 59s",
            60: "há 1m00s",
            125: "há 2m05s",
            3599: "há 59m59s",
            3600: "há 1h00m",
            7500: "há 2h05m",
        }
        for segundos, esperado in casos.items():
            with self.subTest(segundos=segundos):
                self.assertEqual(formatar_idade(segundos), esperado)

    def test_relogio_adiantado_nao_gera_valor_negativo(self):
        self.assertEqual(formatar_idade(-3), "há 0s")


class TestFormatarTabela(unittest.TestCase):
    def setUp(self):
        self.estado = EstadoCentral()

    def tabela(self, agora=T0 + timedelta(seconds=5)):
        return formatar_tabela(self.estado.snapshot(), agora)

    def test_sem_maquinas(self):
        self.assertEqual(self.tabela(), "Nenhuma máquina registrada até o momento.")

    def test_linha_completa(self):
        self.estado.atualizar("maquina01", "cpu", cpu(25.5), T0)
        self.estado.atualizar("maquina01", "memoria", mem(4096, percentual=50.0), T0)

        cabecalho, separador, linha = self.tabela().splitlines()
        self.assertEqual(cabecalho.split(), ["MÁQUINA", "CPU", "RAM", "ÚLTIMA", "ATUALIZAÇÃO"])
        self.assertTrue(set(separador) <= {"-", " "})
        self.assertIn("maquina01", linha)
        self.assertIn("25.5 %", linha)
        self.assertIn("4096.0 MB (50.0%)", linha)
        self.assertIn("12:00:00 (há 5s)", linha)

    def test_metrica_pendente_aparece_como_traco(self):
        self.estado.atualizar("maquina01", "cpu", cpu(30.0), T0)
        self.estado.atualizar("maquina02", "memoria", mem(1024), T0)

        _, _, linha1, linha2 = self.tabela().splitlines()
        self.assertEqual(linha1.split()[:4], ["maquina01", "30.0", "%", "-"])
        self.assertEqual(linha2.split()[:3], ["maquina02", "-", "1024.0"])

    def test_memoria_sem_detalhes_nao_mostra_percentual(self):
        self.estado.atualizar("maquina01", "memoria", mem(2048), T0)
        self.assertIn("2048.0 MB", self.tabela())
        self.assertNotIn("%", self.tabela())

    def test_todas_as_maquinas_em_ordem_de_id(self):
        for id_maquina in ("zeta", "alfa", "maquina02"):
            self.estado.atualizar(id_maquina, "cpu", cpu(), T0)

        linhas = self.tabela().splitlines()[2:]
        self.assertEqual([l.split()[0] for l in linhas], ["alfa", "maquina02", "zeta"])

    def test_colunas_alinhadas_com_ids_de_tamanhos_diferentes(self):
        self.estado.atualizar("m1", "cpu", cpu(5.0), T0)
        self.estado.atualizar("maquina-com-nome-comprido", "cpu", cpu(100.0), T0)
        self.estado.atualizar("m1", "memoria", mem(512), T0)

        linhas = self.tabela().splitlines()
        coluna_cpu = linhas[0].index("CPU")
        for linha in linhas[2:]:
            self.assertEqual(linha[coluna_cpu - 2:coluna_cpu], "  ")
            self.assertNotEqual(linha[coluna_cpu], " ")

    def test_idade_cresce_com_o_tempo_sem_nova_mensagem(self):
        self.estado.atualizar("maquina01", "cpu", cpu(), T0)
        self.assertIn("há 5s", self.tabela(T0 + timedelta(seconds=5)))
        self.assertIn("há 1m30s", self.tabela(T0 + timedelta(seconds=90)))


class TestRecebimento(unittest.TestCase):
    def setUp(self):
        self.monitor = MonitorCentral()

    def test_contadores_de_recebidas_e_descartadas(self):
        with self.assertLogs(logger, level="WARNING"):
            self.monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", cpu(10.0)))
            self.monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", cpu(112.5)))
            self.monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", b"{quebrado"))
            self.monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/disco", cpu()))

        self.assertEqual(self.monitor.mensagens_recebidas, 4)
        self.assertEqual(self.monitor.mensagens_descartadas, 3)
        self.assertEqual(self.monitor.estado.obter("maquina01").metricas["cpu"].valor, 10.0)

    def test_receber_nao_escreve_no_terminal(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            self.monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", cpu()))
        self.assertEqual(saida.getvalue(), "")

    def test_mensagem_recebida_vai_para_o_log_de_mensagens(self):
        with self.assertLogs(logger_mensagens, level="INFO") as capturado:
            self.monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", cpu(25.5)))
        self.assertEqual(len(capturado.records), 1)
        self.assertIn("maquina01", capturado.output[0])
        self.assertIn("25.5 %", capturado.output[0])

    def test_descarte_gera_aviso_com_o_motivo(self):
        with self.assertLogs(logger, level="WARNING") as capturado:
            self.monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", cpu(112.5)))
        self.assertIn("descartada", capturado.output[0])
        self.assertIn("monitoramento/maquina01/cpu", capturado.output[0])


class TestConexao(unittest.TestCase):
    def setUp(self):
        self.monitor = MonitorCentral(filtro="monitoramento/#")
        self.cliente = SimpleNamespace(subscribe=lambda filtro, qos: self.assinaturas.append((filtro, qos)) or (0, 1))
        self.assinaturas = []

    def test_conectar_assina_o_filtro_e_registra(self):
        with self.assertLogs(logger, level="INFO") as capturado:
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.assertTrue(self.monitor.conectado)
        self.assertEqual(self.assinaturas, [("monitoramento/#", 0)])
        self.assertTrue(any("Conectado" in linha for linha in capturado.output))
        self.assertTrue(any("Assinatura ativa" in linha for linha in capturado.output))

    def test_reassina_a_cada_reconexao(self):
        with self.assertLogs(logger, level="INFO"):
            self.monitor._ao_conectar(self.cliente, None, None, 0)
            self.monitor._ao_desconectar(self.cliente, None, None, 7, None)
            self.monitor._ao_conectar(self.cliente, None, None, 0)
        self.assertEqual(len(self.assinaturas), 2)

    def test_conexao_recusada_nao_assina(self):
        with self.assertLogs(logger, level="ERROR"):
            self.monitor._ao_conectar(self.cliente, None, None, 5)
        self.assertFalse(self.monitor.conectado)
        self.assertEqual(self.assinaturas, [])

    def test_queda_inesperada_gera_aviso(self):
        self.monitor._executando = True
        self.monitor.conectado = True
        with self.assertLogs(logger, level="WARNING") as capturado:
            self.monitor._ao_desconectar(self.cliente, None, None, 7, None)
        self.assertFalse(self.monitor.conectado)
        self.assertIn("perdida", capturado.output[0])

    def test_desconexao_ao_encerrar_e_informativa(self):
        self.monitor.conectado = True
        with self.assertLogs(logger, level="INFO") as capturado:
            self.monitor._ao_desconectar(self.cliente, None, None, 0, None)
        self.assertFalse(self.monitor.conectado)
        self.assertEqual(capturado.records[0].levelno, logging.INFO)
        self.assertIn("Desconectado", capturado.output[0])


class TestPainelDeEventos(unittest.TestCase):
    def setUp(self):
        self.eventos = HandlerEventos(capacidade=3)
        self.addCleanup(logger.removeHandler, self.eventos)
        logger.addHandler(self.eventos)
        nivel = logger.level
        self.addCleanup(logger.setLevel, nivel)
        logger.setLevel(logging.INFO)

    def test_guarda_so_os_ultimos_eventos(self):
        for i in range(5):
            logger.info("evento %d", i)
        recentes = self.eventos.recentes(10)
        self.assertEqual(len(recentes), 3)
        self.assertTrue(recentes[0].endswith("evento 2"))
        self.assertTrue(recentes[-1].endswith("evento 4"))

    def test_mensagens_recebidas_nao_entram_no_painel(self):
        logger.info("conexão")
        logger_mensagens.info("maquina01 | cpu | 10 %")
        self.assertEqual(len(self.eventos.recentes(10)), 1)

    def test_eventos_do_estado_entram_no_painel(self):
        EstadoCentral().atualizar("maquina01", "cpu", cpu())
        self.assertTrue(any("Nova máquina" in linha for linha in self.eventos.recentes(10)))


class TestTela(unittest.TestCase):
    def test_cabecalho_com_situacao_e_contadores(self):
        monitor = MonitorCentral(host="10.0.0.5", porta=1884)
        monitor.estado.atualizar("maquina01", "cpu", cpu(40.0), T0)
        monitor.mensagens_recebidas, monitor.mensagens_descartadas = 12, 2

        tela = monitor.montar_tela(T0 + timedelta(seconds=3))
        self.assertIn("10.0.0.5:1884 (desconectado)", tela)
        self.assertIn("filtro monitoramento/+/+", tela)
        self.assertIn("21/11/2026 12:00:03", tela)
        self.assertIn("máquinas: 1", tela)
        self.assertIn("12 recebidas, 2 descartadas", tela)
        self.assertIn("maquina01", tela)

        monitor.conectado = True
        self.assertIn("(conectado)", monitor.montar_tela(T0))

    def test_painel_de_eventos_so_aparece_com_eventos(self):
        eventos = HandlerEventos()
        monitor = MonitorCentral(eventos=eventos)
        self.assertNotIn("Eventos recentes", monitor.montar_tela(T0))

        registro = logging.LogRecord("monitor", logging.INFO, __file__, 1, "Conectado ao broker", None, None)
        eventos.emit(registro)
        tela = monitor.montar_tela(T0)
        self.assertIn("Eventos recentes:", tela)
        self.assertIn("Conectado ao broker", tela)

    def test_exibir_tabela_limpa_a_tela_so_em_terminal(self):
        monitor = MonitorCentral()
        saida = io.StringIO()
        with redirect_stdout(saida):
            monitor.exibir_tabela(limpar=True)
            monitor.exibir_tabela(limpar=False)
        texto = saida.getvalue()
        self.assertTrue(texto.startswith(LIMPAR_TELA))
        self.assertEqual(texto.count(LIMPAR_TELA), 1)
        self.assertEqual(texto.count("Monitor central"), 2)


class TestAtualizacaoPeriodica(unittest.TestCase):
    def setUp(self):
        patcher = patch("server.subscriber.mqtt.Client")
        self.classe_cliente = patcher.start()
        self.addCleanup(patcher.stop)

    def iniciar_em_thread(self, monitor):
        thread = threading.Thread(target=monitor.iniciar, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(monitor.parar)
        return thread

    def esperar(self, condicao, limite=5.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            if condicao():
                return True
            time.sleep(0.01)
        return False

    def test_tabela_e_redesenhada_no_intervalo_configurado(self):
        monitor = MonitorCentral(intervalo_tabela=0.05)
        exibicoes = []
        with redirect_stdout(io.StringIO()), patch.object(
            monitor, "exibir_tabela", side_effect=lambda *a, **k: exibicoes.append(time.monotonic())
        ):
            thread = self.iniciar_em_thread(monitor)
            self.assertTrue(self.esperar(lambda: len(exibicoes) >= 4))
            monitor.parar()
            thread.join(5)

        self.assertFalse(thread.is_alive())
        intervalos = [b - a for a, b in zip(exibicoes, exibicoes[1:])]
        self.assertTrue(all(0.04 <= i <= 0.5 for i in intervalos), intervalos)

    def test_intervalo_padrao_e_cinco_segundos(self):
        self.assertEqual(MonitorCentral().intervalo_tabela, 5.0)
        self.assertEqual(ler_argumentos([]).intervalo_tabela, 5.0)

    def test_mensagens_chegando_durante_a_exibicao_aparecem_nas_telas_seguintes(self):
        monitor = MonitorCentral(intervalo_tabela=0.05)
        telas = []
        saida = io.StringIO()

        with redirect_stdout(saida):
            thread = self.iniciar_em_thread(monitor)
            with patch.object(monitor, "exibir_tabela", side_effect=lambda *a, **k: telas.append(monitor.montar_tela())):
                for i in range(1, 4):
                    monitor._ao_receber(None, None, mensagem(f"monitoramento/maquina0{i}/cpu", cpu(i * 10.0)))
                    quantidade = len(telas)
                    self.assertTrue(self.esperar(lambda: len(telas) > quantidade))
                monitor.parar()
                thread.join(5)

        for i in range(1, 4):
            self.assertTrue(any(f"maquina0{i}" in tela for tela in telas), f"maquina0{i} não apareceu")
        self.assertNotIn("maquina03", telas[0])

    def test_loop_da_tabela_nao_bloqueia_o_recebimento(self):
        monitor = MonitorCentral(intervalo_tabela=0.01)
        recebidas = 300

        def escritor():
            for i in range(recebidas):
                monitor._ao_receber(None, None, mensagem(f"monitoramento/m{i % 10:02d}/cpu", cpu(float(i % 100))))

        with redirect_stdout(io.StringIO()):
            thread = self.iniciar_em_thread(monitor)
            produtor = threading.Thread(target=escritor)
            inicio = time.monotonic()
            produtor.start()
            produtor.join(10)
            duracao = time.monotonic() - inicio
            monitor.parar()
            thread.join(5)

        self.assertFalse(produtor.is_alive())
        self.assertLess(duracao, 5.0)
        self.assertEqual(monitor.mensagens_recebidas, recebidas)
        self.assertEqual(monitor.estado.total_maquinas(), 10)

    def test_encerrar_imprime_o_ultimo_estado(self):
        monitor = MonitorCentral(intervalo_tabela=60)
        monitor.estado.atualizar("maquina01", "cpu", cpu(77.0), T0)
        saida = io.StringIO()
        with redirect_stdout(saida):
            thread = self.iniciar_em_thread(monitor)
            self.assertTrue(self.esperar(lambda: "maquina01" in saida.getvalue()))
            monitor.parar()
            thread.join(5)

        self.assertIn("Último estado de cada máquina:", saida.getvalue())
        self.assertGreaterEqual(saida.getvalue().count("77.0 %"), 2)

    def test_conexao_assincrona_com_o_broker(self):
        monitor = MonitorCentral(host="broker.local", porta=1999, intervalo_tabela=0.05)
        cliente = self.classe_cliente.return_value
        with redirect_stdout(io.StringIO()):
            thread = self.iniciar_em_thread(monitor)
            self.assertTrue(self.esperar(lambda: cliente.loop_start.called))
            monitor.parar()
            thread.join(5)

        cliente.connect_async.assert_called_once_with("broker.local", 1999, keepalive=60)
        cliente.disconnect.assert_called_once()
        cliente.loop_stop.assert_called_once()


class TestArgumentosELogs(unittest.TestCase):
    def test_argumentos_novos(self):
        args = ler_argumentos(["--intervalo-tabela", "2.5", "--log", "outro.log"])
        self.assertEqual(args.intervalo_tabela, 2.5)
        self.assertEqual(args.log, "outro.log")
        self.assertEqual(ler_argumentos([]).log, "monitor.log")

    def test_intervalo_invalido_e_rejeitado(self):
        for valor in ("0", "-1", "abc"):
            with self.subTest(valor=valor), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    ler_argumentos(["--intervalo-tabela", valor])

    def test_arquivo_de_log_recebe_conexoes_e_mensagens(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "monitor.log")
            antes = list(logger.handlers), logger.level, logger.propagate
            eventos = configurar_logs(caminho)
            try:
                monitor = MonitorCentral(eventos=eventos)
                logger.info("Conectado ao broker de teste")
                monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", cpu(33.3)))
                monitor._ao_receber(None, None, mensagem("monitoramento/maquina01/cpu", cpu(150.0)))
                for handler in logger.handlers:
                    handler.flush()
                with open(caminho, encoding="utf-8") as arquivo:
                    conteudo = arquivo.read()
            finally:
                for handler in list(logger.handlers):
                    if handler not in antes[0]:
                        logger.removeHandler(handler)
                        handler.close()
                logger.setLevel(antes[1])
                logger.propagate = antes[2]

        self.assertIn("Conectado ao broker de teste", conteudo)
        self.assertIn("maquina01 | cpu     | 33.3 %", conteudo)
        self.assertIn("descartada", conteudo)
        painel = "\n".join(eventos.recentes(10))
        self.assertIn("Conectado ao broker de teste", painel)
        self.assertNotIn("33.3", painel)


if __name__ == "__main__":
    unittest.main()
