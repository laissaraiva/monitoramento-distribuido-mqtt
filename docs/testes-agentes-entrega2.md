# Entrega 2 — Testes dos Agentes Publisher

**Disciplina:** CIN0143 — Introdução aos Sistemas Distribuídos e Redes de Computadores  
**Equipe:** 06  

## 1. Objetivo

Validar o funcionamento dos agentes Publisher MQTT, incluindo coleta periódica de CPU e memória RAM, execução simultânea de múltiplos agentes, independência entre processos e recuperação automática da comunicação após interrupção do broker Mosquitto.

## 2. Ambiente de testes

- Sistema operacional: macOS
- Linguagem: Python
- Broker: Eclipse Mosquitto 2.1.2
- Protocolo: MQTT
- Porta: 1883
- QoS: 0
- Intervalo de amostragem: 5 segundos
- Métricas: CPU e memória RAM
- Bibliotecas: `psutil` e `paho-mqtt`

## 3. Teste com três agentes simultâneos

Foram executadas três instâncias do Publisher, com identificadores distintos:

```bash
python3 -m agent.publisher --id maquina01 --intervalo 5
python3 -m agent.publisher --id maquina02 --intervalo 5
python3 -m agent.publisher --id maquina03 --intervalo 5
```

O Subscriber central foi executado com:

```bash
python3 -m server.subscriber
```

**Resultado:** as três instâncias publicaram métricas de CPU e memória RAM simultaneamente. O Subscriber recebeu as leituras das três máquinas, com atualizações aproximadamente a cada cinco segundos.

**Status:** APROVADO.

## 4. Teste de interrupção individual

O processo correspondente à `maquina02` foi encerrado com `Control + C`.

Durante sua interrupção, `maquina01` e `maquina03` continuaram publicando normalmente.

Em seguida, a `maquina02` foi iniciada novamente e voltou a publicar suas métricas.

**Status:** APROVADO.

## 5. Teste de reconexão ao broker

O broker Mosquitto foi encerrado por meio de um sinal `SIGTERM` e posteriormente reiniciado.

Após o reinício, os registros do Mosquitto confirmaram:

- Reconexão de `agente-maquina01`.
- Reconexão de `agente-maquina02`.
- Reconexão de `agente-maquina03`.
- Reconexão do `monitor-central`.
- Restabelecimento da assinatura `monitoramento/+/+`.
- Retomada das publicações de CPU e memória RAM.

As publicações voltaram a ser encaminhadas ao Subscriber sem reiniciar os processos Python.

**Status:** APROVADO.

## 6. Testes automatizados

Comando executado:

```bash
python3 -m unittest discover -s tests -p "test*.py" -v
```

Foram executados oito testes automatizados:

| Teste | Resultado |
|---|---|
| Assinatura com wildcard correto | Aprovado |
| Rejeição de mensagem inválida | Aprovado |
| Recebimento de CPU válida | Aprovado |
| Recebimento de memória válida | Aprovado |
| Identificadores MQTT diferentes | Aprovado |
| Bloqueio de publicação quando desconectado | Aprovado |
| Publicação de CPU e memória no mesmo ciclo | Aprovado |
| Configuração de reconexão automática | Aprovado |

Resultado final:

```text
Ran 8 tests in 0.003s

OK
```

Os testes específicos do Publisher utilizam simulação do cliente MQTT para verificar comportamentos isolados. Os testes manuais complementam essa verificação com comunicação real pelo Mosquitto.

## 7. Conclusão

Os testes realizados comprovaram o funcionamento de três agentes MQTT simultâneos, com coleta real de CPU e memória RAM, publicação periódica, independência entre os processos e recuperação da comunicação após reinício do broker.

Os oito testes automatizados foram concluídos com sucesso.

Não foram identificadas falhas nos cenários executados.