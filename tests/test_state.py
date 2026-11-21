# Testes do estado central das máquinas (server/state.py)

# Rodar a partir da raiz do repositório com
#   python3 -m unittest tests.test_state -v
#   python3 -m pytest tests/test_state.py -v  (usar "python3 -m pytest", senão não acha server/common)

import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from server.state import EstadoCentral

T0 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
TS = "2026-11-21T12:00:00-03:00"


def cpu(valor=10.0, ts=TS, por_nucleo=None):
    payload = {"valor": valor, "unidade": "%", "timestamp": ts}
    if por_nucleo is not None:
        payload["detalhes"] = {"por_nucleo": por_nucleo}
    return payload


def mem(valor=4096.0, ts=TS, detalhes=None):
    payload = {"valor": valor, "unidade": "MB", "timestamp": ts}
    if detalhes is not None:
        payload["detalhes"] = detalhes
    return payload


class TestEstadoInicial(unittest.TestCase):
    def test_estado_vazio(self):
        estado = EstadoCentral()
        self.assertEqual(estado.total_maquinas(), 0)
        self.assertEqual(estado.listar(), [])
        self.assertEqual(estado.snapshot(), [])
        self.assertIsNone(estado.obter("maquina01"))
        self.assertIsNone(estado.obter_metrica("maquina01", "cpu"))

        # o subscriber faz "estado or EstadoCentral()", estado vazio não pode ser falso
        self.assertTrue(bool(estado))


class TestMetricas(unittest.TestCase):
    def setUp(self):
        self.estado = EstadoCentral()

    def test_cpu_e_memoria_sao_independentes(self):
        self.estado.atualizar("maquina01", "cpu", cpu(30.0), T0)
        self.assertEqual(set(self.estado.obter("maquina01").metricas), {"cpu"})  # memoria pendente

        self.estado.atualizar("maquina01", "memoria", mem(1000.0), T0)
        self.estado.atualizar("maquina01", "cpu", cpu(55.0), T0)
        self.estado.atualizar("maquina01", "memoria", mem(2000.0), T0)

        m = self.estado.obter("maquina01")
        self.assertEqual(m.metricas["cpu"].valor, 55.0)
        self.assertEqual(m.metricas["memoria"].valor, 2000.0)

    def test_leitura_nova_substitui_a_anterior_com_todos_os_campos(self):
        self.estado.atualizar("maquina01", "cpu", cpu(10.0, TS, [10.0, 10.0]), T0)
        self.estado.atualizar("maquina01", "cpu", cpu(90.0, "2026-11-21T12:00:05-03:00", [80.0, 100.0]), T0)

        leitura = self.estado.obter_metrica("maquina01", "cpu")
        self.assertEqual(leitura.valor, 90.0)
        self.assertEqual(leitura.unidade, "%")
        self.assertEqual(leitura.timestamp, "2026-11-21T12:00:05-03:00")
        self.assertEqual(leitura.detalhes, {"por_nucleo": [80.0, 100.0]})

    def test_hora_de_atualizacao_do_servidor_e_timestamp_do_agente(self):
        t_cpu, t_mem = T0, T0 + timedelta(seconds=3)
        self.estado.atualizar("maquina01", "cpu", cpu(ts="2020-01-01T00:00:00Z"), t_cpu)
        self.assertEqual(self.estado.obter("maquina01").ultima_atualizacao, t_cpu)

        # qualquer métrica válida atualiza a hora da máquina
        self.estado.atualizar("maquina01", "memoria", mem(), t_mem)
        m = self.estado.obter("maquina01")
        self.assertEqual(m.ultima_atualizacao, t_mem)

        # cada métrica guarda a própria hora e o timestamp original do agente
        self.assertEqual(m.metricas["cpu"].recebido_em, t_cpu)
        self.assertEqual(m.metricas["cpu"].timestamp, "2020-01-01T00:00:00Z")

    def test_hora_padrao_e_agora_com_fuso(self):
        antes = datetime.now().astimezone()
        self.estado.atualizar("maquina01", "cpu", cpu())
        depois = datetime.now().astimezone()
        self.assertTrue(antes <= self.estado.obter("maquina01").ultima_atualizacao <= depois)

    def test_entradas_invalidas_nao_alteram_o_estado(self):
        invalidas = [
            ("maquina01", "disco", cpu()),          # métrica não suportada
            ("a", "cpu", cpu()),                    # id curto demais
            ("maq/uina", "cpu", cpu()),             # id com caractere reservado
            (None, "cpu", cpu()),                   # id que não é string
            ("maquina01", "cpu", None),             # payload que não é dict
            ("maquina01", "cpu", {"valor": 1.0}),   # faltam campos obrigatórios
        ]
        for id_maquina, metrica, payload in invalidas:
            with self.subTest(id=id_maquina, metrica=metrica):
                with self.assertRaises(ValueError):
                    self.estado.atualizar(id_maquina, metrica, payload, T0)
        self.assertEqual(self.estado.total_maquinas(), 0)

        # rejeitar não pode mexer no último valor válido
        self.estado.atualizar("maquina01", "cpu", cpu(45.5), T0)
        antes = self.estado.obter("maquina01")
        with self.assertRaises(ValueError):
            self.estado.atualizar("maquina01", "cpu", {"valor": 1.0}, T0 + timedelta(seconds=5))
        self.assertEqual(self.estado.obter("maquina01"), antes)

    def test_mutar_o_payload_depois_nao_altera_o_estado(self):
        payload = mem(100.0, detalhes={"total": 200.0, "livre": 100.0, "percentual": 50.0})
        self.estado.atualizar("maquina01", "memoria", payload, T0)
        payload["valor"] = 999.0
        payload["detalhes"]["total"] = 999.0

        leitura = self.estado.obter_metrica("maquina01", "memoria")
        self.assertEqual(leitura.valor, 100.0)
        self.assertEqual(leitura.detalhes["total"], 200.0)


class TestMultiplasMaquinas(unittest.TestCase):
    def setUp(self):
        self.estado = EstadoCentral()
        self.horas = {
            "maquina01": T0,
            "maquina02": T0 + timedelta(seconds=10),
            "maquina03": T0 + timedelta(seconds=20),
        }
        # valores diferentes pra cada máquina: 11/1100, 22/2200, 33/3300
        for i, (id_maquina, hora) in enumerate(self.horas.items(), start=1):
            self.estado.atualizar(id_maquina, "cpu", cpu(i * 11.0, f"2026-11-21T12:00:0{i}-03:00"), hora)
            self.estado.atualizar(id_maquina, "memoria", mem(i * 1100.0), hora)

    def test_cada_maquina_tem_suas_metricas_e_horas(self):
        for i, (id_maquina, hora) in enumerate(self.horas.items(), start=1):
            with self.subTest(maquina=id_maquina):
                m = self.estado.obter(id_maquina)
                self.assertEqual(m.metricas["cpu"].valor, i * 11.0)
                self.assertEqual(m.metricas["memoria"].valor, i * 1100.0)
                self.assertEqual(m.metricas["cpu"].timestamp, f"2026-11-21T12:00:0{i}-03:00")
                self.assertEqual(m.ultima_atualizacao, hora)

    def test_atualizar_uma_maquina_nao_altera_as_outras(self):
        antes_1 = self.estado.obter("maquina01")
        antes_3 = self.estado.obter("maquina03")

        self.estado.atualizar("maquina02", "cpu", cpu(99.0), T0 + timedelta(minutes=5))

        self.assertEqual(self.estado.obter("maquina01"), antes_1)
        self.assertEqual(self.estado.obter("maquina03"), antes_3)
        self.assertEqual(self.estado.obter("maquina02").metricas["cpu"].valor, 99.0)

    def test_listar_ordenado_por_id_independente_da_chegada(self):
        estado = EstadoCentral()
        for id_maquina in ("zeta", "alfa", "maquina10", "maquina02"):
            estado.atualizar(id_maquina, "cpu", cpu(), T0)
        self.assertEqual([m.id_maquina for m in estado.listar()], ["alfa", "maquina02", "maquina10", "zeta"])
        self.assertEqual(estado.total_maquinas(), 4)


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self.estado = EstadoCentral()

    def test_ordem_e_formato(self):
        self.estado.atualizar("maquina02", "cpu", cpu(), T0)
        self.estado.atualizar("maquina01", "cpu", cpu(45.5, TS, [40.0, 51.0]), T0)
        self.estado.atualizar("maquina01", "memoria", mem(4096.0), T0 + timedelta(seconds=1))

        linha, outra = self.estado.snapshot()
        self.assertEqual([linha["id_maquina"], outra["id_maquina"]], ["maquina01", "maquina02"])
        self.assertEqual(set(linha), {"id_maquina", "cpu", "memoria", "ultima_atualizacao"})
        self.assertEqual(linha["cpu"], {
            "valor": 45.5, "unidade": "%", "timestamp": TS,
            "detalhes": {"por_nucleo": [40.0, 51.0]}, "recebido_em": T0,
        })
        self.assertEqual(linha["memoria"]["valor"], 4096.0)
        self.assertEqual(linha["ultima_atualizacao"], T0 + timedelta(seconds=1))

    def test_metrica_pendente_vem_como_none(self):
        self.estado.atualizar("maquina01", "cpu", cpu(), T0)
        self.estado.atualizar("maquina02", "memoria", mem(), T0)

        linha1, linha2 = self.estado.snapshot()
        self.assertIsNone(linha1["memoria"])
        self.assertIsNone(linha2["cpu"])
        self.assertEqual(linha1["ultima_atualizacao"], T0)  # mesmo com métrica pendente

    def test_mutar_retornos_nao_altera_o_estado(self):
        self.estado.atualizar("maquina01", "cpu", cpu(10.0, por_nucleo=[10.0]), T0)

        snap = self.estado.snapshot()
        snap[0]["cpu"]["valor"] = 999.0
        snap[0]["cpu"]["detalhes"]["por_nucleo"].append(1.0)
        snap[0]["id_maquina"] = "hackeada"
        snap.clear()

        copia = self.estado.obter("maquina01")
        copia.metricas["cpu"].valor = 999.0
        copia.metricas.clear()

        lista = self.estado.listar()
        lista[0].metricas["cpu"].detalhes["por_nucleo"].clear()

        real = self.estado.snapshot()
        self.assertEqual(len(real), 1)
        self.assertEqual(real[0]["id_maquina"], "maquina01")
        self.assertEqual(real[0]["cpu"]["valor"], 10.0)
        self.assertEqual(real[0]["cpu"]["detalhes"]["por_nucleo"], [10.0])


class TestConcorrencia(unittest.TestCase):
    # Exceção dentro de thread não derruba o teste, então rodar() guarda em self.erros e confere no final
    # Barrier faz todas as threads largarem juntas (senão uma terminaria antes da outra começar)
    # join com timeout detecta deadlock
    TIMEOUT_S = 60.0

    def setUp(self):
        self.estado = EstadoCentral()
        self.fim = threading.Event()  # escritores terminaram
        self.erros = []

        # troca de thread mais frequente (padrão 5 ms) pra expor falta de trava
        original = sys.getswitchinterval()
        sys.setswitchinterval(1e-5)
        self.addCleanup(sys.setswitchinterval, original)

    def rodar(self, escritores, leitores=()):
        largada = threading.Barrier(len(escritores) + len(leitores))

        def embrulhar(funcao):
            def alvo():
                try:
                    largada.wait()
                    funcao()
                except BaseException as exc:
                    self.erros.append(repr(exc))
            return threading.Thread(target=alvo)

        t_escritores = [embrulhar(f) for f in escritores]
        t_leitores = [embrulhar(f) for f in leitores]
        for t in t_escritores + t_leitores:
            t.start()
        for t in t_escritores:
            t.join(self.TIMEOUT_S)
        self.fim.set()
        for t in t_leitores:
            t.join(self.TIMEOUT_S)

        travadas = [t for t in t_escritores + t_leitores if t.is_alive()]
        self.assertEqual(travadas, [], "possível deadlock")
        self.assertEqual(self.erros, [])

    def test_agentes_escrevendo_enquanto_leitores_consultam(self):
        n_agentes, n_ciclos = 10, 100
        ids = [f"maquina{i:02d}" for i in range(n_agentes)]
        leituras = []  # quantas leituras cada leitor fez

        # cada escrita leva a origem e a sequência em detalhes, pra provar que não houve mistura
        def agente(id_maquina):
            def corpo():
                for seq in range(n_ciclos):
                    marca = {"origem": id_maquina, "seq": seq}
                    self.estado.atualizar(id_maquina, "cpu", {**cpu(float(seq)), "detalhes": dict(marca)})
                    self.estado.atualizar(id_maquina, "memoria", {**mem(float(seq)), "detalhes": dict(marca)})
            return corpo

        def leitor():
            feitas = 0
            while True:
                acabou = self.fim.is_set()  # lê antes, garante ao menos uma leitura completa
                snap = self.estado.snapshot()
                vistos = [linha["id_maquina"] for linha in snap]
                if vistos != sorted(vistos):
                    raise AssertionError(f"snapshot fora de ordem: {vistos}")
                for linha in snap:
                    for metrica in ("cpu", "memoria"):
                        leitura = linha[metrica]
                        if leitura is None:
                            continue
                        det = leitura["detalhes"]
                        if det["origem"] != linha["id_maquina"] or det["seq"] != int(leitura["valor"]):
                            raise AssertionError(f"dados misturados: {linha['id_maquina']}/{metrica} {leitura}")
                feitas += 1
                time.sleep(0)  # cede a vez pros escritores
                if acabou:
                    break
            leituras.append(feitas)

        self.rodar([agente(i) for i in ids], [leitor] * 2)

        self.assertEqual(len(leituras), 2)
        self.assertEqual(self.estado.total_maquinas(), n_agentes)
        for id_maquina in ids:
            m = self.estado.obter(id_maquina)
            for metrica in ("cpu", "memoria"):
                # sem perda: a última escrita de cada agente é a que ficou
                self.assertEqual(m.metricas[metrica].valor, float(n_ciclos - 1))
                self.assertEqual(m.metricas[metrica].detalhes, {"origem": id_maquina, "seq": n_ciclos - 1})

    def test_threads_diferentes_na_mesma_maquina_nao_apagam_uma_a_outra(self):
        n = 1000

        def escritor(metrica, unidade, base):
            def corpo():
                for seq in range(n):
                    self.estado.atualizar(
                        "maquina01", metrica, {"valor": base + seq, "unidade": unidade, "timestamp": TS}
                    )
            return corpo

        self.rodar([escritor("cpu", "%", 0.0), escritor("memoria", "MB", 100000.0)])

        m = self.estado.obter("maquina01")
        self.assertEqual(m.metricas["cpu"].valor, float(n - 1))
        self.assertEqual(m.metricas["memoria"].valor, 100000.0 + n - 1)

    def test_snapshot_e_um_retrato_atomico(self):
        n = 300

        def escritor():
            for seq in range(n):
                for id_maquina in ("maquina01", "maquina02"):
                    self.estado.atualizar(id_maquina, "cpu", cpu(float(seq)))

        def leitor():
            while True:
                acabou = self.fim.is_set()
                snap = self.estado.snapshot()
                if len(snap) == 2:
                    a, b = snap[0]["cpu"]["valor"], snap[1]["cpu"]["valor"]
                    if a - b not in (0.0, 1.0):
                        raise AssertionError(f"retrato inconsistente: maquina01={a}, maquina02={b}")
                if acabou:
                    break
                time.sleep(0)

        self.rodar([escritor], [leitor, leitor])

    def test_trava_e_reentrante(self):
        # com Lock simples isso trava (deadlock), com RLock passa
        def corpo():
            with self.estado._lock:
                self.estado.atualizar("maquina01", "cpu", cpu())
                self.estado.obter("maquina01")
                self.estado.snapshot()

        self.rodar([corpo])
        self.assertEqual(self.estado.total_maquinas(), 1)


if __name__ == "__main__":
    unittest.main()