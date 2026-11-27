# Testes das extensões do estado para o dashboard (server/state.py)
# histórico das métricas, status online/indisponivel por timeout e snapshot_dashboard

# Rodar a partir da raiz do repositório com
#   python3 -m unittest tests.test_state_dashboard -v
#   python3 -m pytest tests/test_state_dashboard.py -v

import unittest
from datetime import datetime, timedelta, timezone

from server.state import HISTORICO_MAXIMO, TIMEOUT_AGENTE_PADRAO, EstadoCentral

T0 = datetime(2026, 11, 28, 10, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
TS = "2026-11-28T10:00:00-03:00"
DET_MEM = {"total": 8000.0, "livre": 4000.0, "percentual": 50.0}


def cpu(valor=10.0):
    return {"valor": valor, "unidade": "%", "timestamp": TS}


def mem(valor=4000.0, detalhes=DET_MEM):
    payload = {"valor": valor, "unidade": "MB", "timestamp": TS}
    if detalhes is not None:
        payload["detalhes"] = dict(detalhes)
    return payload


def iso(segundos):
    # horário ISO (como o histórico grava) de T0 + segundos
    return (T0 + timedelta(seconds=segundos)).isoformat(timespec="seconds")


class TestConstrutor(unittest.TestCase):
    def test_padroes(self):
        estado = EstadoCentral()
        self.assertEqual(TIMEOUT_AGENTE_PADRAO, 15.0)
        self.assertEqual(HISTORICO_MAXIMO, 120)
        self.assertEqual(estado.timeout_agente, 15.0)

    def test_timeout_personalizado(self):
        self.assertEqual(EstadoCentral(timeout_agente=30).timeout_agente, 30.0)

    def test_timeout_invalido_levanta_value_error(self):
        for invalido in (0, -1, -0.5, True, "15", None, float("nan")):
            with self.subTest(timeout=invalido):
                with self.assertRaises(ValueError):
                    EstadoCentral(timeout_agente=invalido)

    def test_historico_maximo_invalido_levanta_value_error(self):
        for invalido in (0, -3, 2.5, True, "10", None):
            with self.subTest(historico_maximo=invalido):
                with self.assertRaises(ValueError):
                    EstadoCentral(historico_maximo=invalido)


class TestStatusPorTimeout(unittest.TestCase):
    def setUp(self):
        self.estado = EstadoCentral(timeout_agente=15.0)
        self.estado.atualizar("maquina01", "cpu", cpu(), T0)

    def status(self, agora):
        return self.estado.snapshot_dashboard(agora)[0]["status"]

    def test_fronteira_do_timeout(self):
        self.assertEqual(self.status(T0), "online")
        self.assertEqual(self.status(T0 + timedelta(seconds=14.9)), "online")
        # exatamente no limite ainda é online
        self.assertEqual(self.status(T0 + timedelta(seconds=15)), "online")
        # passou do limite
        self.assertEqual(self.status(T0 + timedelta(seconds=15.1)), "indisponivel")

    def test_volta_a_online_com_nova_leitura(self):
        agora = T0 + timedelta(seconds=60)
        self.assertEqual(self.status(agora), "indisponivel")

        # qualquer métrica nova devolve a máquina a online, sem ninguém "religar" nada
        self.estado.atualizar("maquina01", "memoria", mem(), agora)
        self.assertEqual(self.status(agora + timedelta(seconds=1)), "online")

    def test_so_a_maquina_silenciosa_fica_indisponivel(self):
        self.estado.atualizar("maquina02", "cpu", cpu(), T0 + timedelta(seconds=20))
        linhas = self.estado.snapshot_dashboard(T0 + timedelta(seconds=25))
        self.assertEqual(
            {linha["id_maquina"]: linha["status"] for linha in linhas},
            {"maquina01": "indisponivel", "maquina02": "online"},
        )

    def test_timeout_personalizado_muda_a_fronteira(self):
        estado = EstadoCentral(timeout_agente=2.0)
        estado.atualizar("maquina01", "cpu", cpu(), T0)
        self.assertEqual(estado.snapshot_dashboard(T0 + timedelta(seconds=2))[0]["status"], "online")
        self.assertEqual(estado.snapshot_dashboard(T0 + timedelta(seconds=2.1))[0]["status"], "indisponivel")

    def test_segundos_sem_dados(self):
        linha = self.estado.snapshot_dashboard(T0 + timedelta(seconds=3.7))[0]
        self.assertEqual(linha["segundos_sem_dados"], 3)
        # relógio andando pra trás nunca gera valor negativo
        linha = self.estado.snapshot_dashboard(T0 - timedelta(seconds=5))[0]
        self.assertEqual(linha["segundos_sem_dados"], 0)

    def test_agora_padrao_e_o_relogio_do_servidor(self):
        estado = EstadoCentral()
        estado.atualizar("maquina01", "cpu", cpu())  # recebido_em = agora
        linha = estado.snapshot_dashboard()[0]
        self.assertEqual(linha["status"], "online")
        self.assertLessEqual(linha["segundos_sem_dados"], 1)


class TestFormatoSnapshotDashboard(unittest.TestCase):
    def setUp(self):
        self.estado = EstadoCentral()

    def test_vazio(self):
        self.assertEqual(self.estado.snapshot_dashboard(T0), [])

    def test_formato_do_contrato(self):
        self.estado.atualizar("maquina02", "cpu", cpu(12.5), T0)
        self.estado.atualizar("maquina01", "cpu", cpu(12.5), T0)
        self.estado.atualizar(
            "maquina01", "memoria", mem(4096.0, {"total": 8000.0, "percentual": 51.2}), T0
        )

        linha1, linha2 = self.estado.snapshot_dashboard(T0 + timedelta(seconds=3))
        self.assertEqual(linha1, {
            "id_maquina": "maquina01",
            "status": "online",
            "segundos_sem_dados": 3,
            "cpu": {"valor": 12.5},
            "memoria": {"valor": 4096.0, "unidade": "MB", "percentual": 51.2},
        })
        # ordenado por id_maquina; métrica que ainda não chegou vem como None
        self.assertEqual(linha2["id_maquina"], "maquina02")
        self.assertIsNone(linha2["memoria"])

    def test_memoria_sem_detalhes_tem_percentual_none(self):
        self.estado.atualizar("maquina01", "memoria", mem(2000.0, None), T0)
        memoria = self.estado.snapshot_dashboard(T0)[0]["memoria"]
        self.assertEqual(memoria["valor"], 2000.0)
        self.assertIsNone(memoria["percentual"])

    def test_snapshot_antigo_nao_muda(self):
        # tests/test_state.py depende do formato do snapshot()
        self.estado.atualizar("maquina01", "cpu", cpu(), T0)
        self.assertEqual(
            set(self.estado.snapshot()[0]),
            {"id_maquina", "cpu", "memoria", "ultima_atualizacao"},
        )

    def test_retorno_e_copia(self):
        self.estado.atualizar("maquina01", "cpu", cpu(10.0), T0)
        linhas = self.estado.snapshot_dashboard(T0)
        linhas[0]["cpu"]["valor"] = 999.0
        linhas.clear()
        self.assertEqual(self.estado.snapshot_dashboard(T0)[0]["cpu"]["valor"], 10.0)


class TestHistorico(unittest.TestCase):
    def setUp(self):
        self.estado = EstadoCentral()

    def test_vazio(self):
        self.assertEqual(self.estado.historico_todas(), {})

    def test_formato_e_percentual_de_cada_metrica(self):
        self.estado.atualizar("maquina01", "cpu", cpu(12.5), T0)
        self.estado.atualizar("maquina01", "memoria", mem(4000.0), T0 + timedelta(seconds=1))

        self.assertEqual(self.estado.historico_todas(), {
            "maquina01": {
                "cpu": [{"t": iso(0), "valor": 12.5}],
                "memoria": [{"t": iso(1), "valor": 50.0}],  # percentual de uso, não MB
            }
        })

    def test_metrica_sem_pontos_vem_como_lista_vazia(self):
        self.estado.atualizar("maquina01", "cpu", cpu(), T0)
        self.assertEqual(self.estado.historico_todas()["maquina01"]["memoria"], [])

    def test_memoria_sem_percentual_nao_entra_no_historico(self):
        # formato mínimo (sem detalhes): sem percentual não há o que plotar, e nunca vai "valor": None
        self.estado.atualizar("maquina01", "memoria", mem(2000.0, None), T0)
        self.assertEqual(self.estado.historico_todas()["maquina01"]["memoria"], [])
        # a última leitura continua guardada normalmente
        self.assertEqual(self.estado.obter_metrica("maquina01", "memoria").valor, 2000.0)

    def test_ordem_do_mais_antigo_ao_mais_novo(self):
        for i in range(5):
            self.estado.atualizar("maquina01", "cpu", cpu(float(i)), T0 + timedelta(seconds=i * 5))
        pontos = self.estado.historico_todas()["maquina01"]["cpu"]
        self.assertEqual([p["valor"] for p in pontos], [0.0, 1.0, 2.0, 3.0, 4.0])

    def test_limite_do_historico(self):
        maximo = 120
        estado = EstadoCentral(historico_maximo=maximo)
        for i in range(maximo + 50):
            estado.atualizar("maquina01", "cpu", cpu(float(i % 100)), T0 + timedelta(seconds=i))

        pontos = estado.historico_todas()["maquina01"]["cpu"]
        self.assertEqual(len(pontos), maximo)  # exatamente o máximo, não mais
        # ficaram os mais novos: o ponto 50 virou o mais antigo
        self.assertEqual(pontos[0]["t"], iso(50))
        self.assertEqual(pontos[-1]["t"], iso(maximo + 49))

    def test_limite_padrao_e_120(self):
        for i in range(HISTORICO_MAXIMO + 50):
            self.estado.atualizar("maquina01", "cpu", cpu(), T0 + timedelta(seconds=i))
        self.assertEqual(len(self.estado.historico_todas()["maquina01"]["cpu"]), 120)

    def test_historicos_independentes_por_maquina_e_metrica(self):
        self.estado.atualizar("maquina01", "cpu", cpu(1.0), T0)
        self.estado.atualizar("maquina02", "cpu", cpu(2.0), T0)
        self.estado.atualizar("maquina02", "memoria", mem(), T0)
        h = self.estado.historico_todas()
        self.assertEqual([p["valor"] for p in h["maquina01"]["cpu"]], [1.0])
        self.assertEqual([p["valor"] for p in h["maquina02"]["cpu"]], [2.0])
        self.assertEqual(len(h["maquina02"]["memoria"]), 1)
        self.assertEqual(h["maquina01"]["memoria"], [])
        self.assertEqual(list(h), ["maquina01", "maquina02"])

    def test_leitura_invalida_nao_entra_no_historico(self):
        with self.assertRaises(ValueError):
            self.estado.atualizar("maquina01", "cpu", {"valor": 1.0}, T0)
        self.assertEqual(self.estado.historico_todas(), {})

    def test_retorno_e_copia(self):
        self.estado.atualizar("maquina01", "cpu", cpu(10.0), T0)
        h = self.estado.historico_todas()
        h["maquina01"]["cpu"][0]["valor"] = 999.0
        h["maquina01"]["cpu"].clear()
        self.assertEqual(self.estado.historico_todas()["maquina01"]["cpu"][0]["valor"], 10.0)


if __name__ == "__main__":
    unittest.main()