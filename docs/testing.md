# Relatório de Testes ? Equipe 06

## 1. Objetivo

Este documento apresenta os testes realizados nas entregas do sistema distribuído de monitoramento utilizando MQTT.

Os testes têm como objetivo verificar a comunicação entre os Publishers, o broker Mosquitto e o Subscriber, além de conferir o funcionamento das validações do protocolo, do armazenamento das métricas em memória e da visualização consolidada de múltiplas máquinas.

Na segunda entrega, os testes também verificam a execução simultânea de múltiplos agentes, a atualização periódica da tabela e o comportamento dos componentes durante a comunicação MQTT.

## 2. Ambiente de testes

- Sistema operacional: Windows
- Linguagem: Python 3.13
- Broker MQTT: Eclipse Mosquitto 2.1.2
- Protocolo: MQTT
- Porta: 1883
- Endereço do broker: 127.0.0.1
- Métricas monitoradas: CPU e memória RAM
- Intervalo de publicação: 5 segundos
- QoS: 0
- Biblioteca de comunicação: Paho MQTT
- Biblioteca de coleta: psutil
- Framework de testes: unittest

## 3. Testes manuais realizados ? Primeira entrega

### 3.1. Inicialização do broker Mosquitto

**Procedimento:** inicialização do Mosquitto utilizando o arquivo de configuração `config/mosquitto.conf`.

**Resultado obtido:** o broker iniciou corretamente e ficou disponível na porta 1883.

**Status:** APROVADO.

### 3.2. Comunicação básica entre Publisher e Subscriber

**Procedimento:** utilização dos comandos `mosquitto_pub` e `mosquitto_sub` para publicar e receber uma mensagem de teste no tópico `teste/equipe06`, utilizando o wildcard `#`.

**Resultado obtido:** a mensagem "Teste de comunicacao MQTT" foi recebida corretamente pelo Subscriber.

**Status:** APROVADO.

### 3.3. Integração entre os componentes do sistema

**Procedimento:**

1. Inicialização do broker Mosquitto.
2. Execução do monitor central por meio de `server.subscriber`.
3. Execução do agente por meio de `agent.publisher`, utilizando o identificador `maquina01` e intervalo de 5 segundos.

**Resultado obtido:** o Publisher conectou-se ao broker e publicou as métricas de CPU e memória RAM. O Subscriber recebeu corretamente as mensagens, exibindo valores, unidades, timestamps e informações complementares.

Foram utilizados os tópicos:

- `monitoramento/maquina01/cpu`
- `monitoramento/maquina01/memoria`

**Status:** APROVADO.

### 3.4. Recebimento utilizando wildcard +

**Procedimento:** execução do Subscriber com o filtro `monitoramento/+/+`.

**Resultado obtido:** o monitor central recebeu corretamente as mensagens de CPU e memória RAM publicadas pelo agente.

**Status:** APROVADO.

### 3.5. Recebimento utilizando wildcard #

**Procedimento:** execução do Subscriber com o filtro `monitoramento/#`, seguida da publicação das métricas pelo agente.

**Resultado obtido:** as mensagens correspondentes aos tópicos de CPU e memória RAM foram recebidas corretamente.

**Status:** APROVADO.

### 3.6. Validação de mensagens válidas e inválidas

**Procedimento:** publicação de duas mensagens de CPU no tópico `monitoramento/maquina01/cpu`.

- Mensagem válida: CPU de 25,5%.
- Mensagem inválida: CPU de 112,5%.

**Resultado obtido:** a mensagem válida foi recebida e armazenada. A mensagem inválida foi rejeitada pela validação do protocolo, pois ultrapassava o limite de 100%.

Foi verificado que o valor inválido não substituiu a última leitura válida no estado em memória.

**Status:** APROVADO.

## 4. Testes automatizados ? Primeira entrega

Foi criado o arquivo `tests/test_integration.py`, utilizando a biblioteca `unittest` do Python.

Foram implementados quatro testes:

| Teste | Descrição | Resultado |
|---|---|---|
| `test_filtro_wildcard` | Verifica o filtro padrão do Subscriber. | APROVADO |
| `test_recebimento_cpu_valida` | Verifica o recebimento e armazenamento de CPU. | APROVADO |
| `test_recebimento_memoria_valida` | Verifica o recebimento e armazenamento de RAM. | APROVADO |
| `test_mensagem_invalida_nao_atualiza_estado` | Verifica a rejeição de mensagens inválidas. | APROVADO |

**Comando utilizado para execução:**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_integration.py" -v
```

**Resultado obtido:**

- Total de testes: 4.
- Testes aprovados: 4.
- Testes reprovados: 0.

**Status: APROVADO.**

Os testes automatizados verificam o processamento das mensagens pelo callback do Subscriber, incluindo validação e atualização do estado em memória. A comunicação real com o broker foi verificada separadamente nos testes manuais.

## 5. Testes automatizados ? Segunda entrega

Na segunda entrega, foram ampliados os testes dos componentes do sistema, contemplando armazenamento de múltiplas máquinas, validações adicionais, comportamento dos Publishers e visualização consolidada.

### 5.1. Testes gerais da equipe

**Procedimento:** execução da suíte geral de testes automatizados utilizando o comando:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Resultado obtido:**

- Total de testes executados: 104.
- Testes aprovados: 104.
- Testes reprovados: 0.
- Tempo de execução: aproximadamente 2,385 segundos.

Os testes abrangeram funcionalidades relacionadas a:

- Estado central e armazenamento de múltiplas máquinas.
- Atualização de métricas e horários.
- Segurança do acesso concorrente ao estado.
- Validação de identificadores e tópicos MQTT.
- Validação de mensagens JSON.
- Regras de CPU e memória RAM.
- Tratamento de mensagens inválidas.
- Visualização e atualização periódica da tabela.
- Registro de conexões, desconexões e mensagens recebidas.

**Status: APROVADO.**

### 5.2. Testes automatizados do Publisher

Foi executado o arquivo `tests/test_publisher.py`, responsável por verificar o comportamento dos agentes de monitoramento.

**Comando utilizado:**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_publisher.py" -v
```

Foram realizados quatro testes:

| Teste | Descrição | Resultado |
|---|---|---|
| `test_agentes_usam_ids_mqtt_diferentes` | Verifica se os agentes utilizam identificadores MQTT diferentes. | APROVADO |
| `test_nao_publica_quando_desconectado` | Verifica o comportamento quando o broker está desconectado. | APROVADO |
| `test_publica_cpu_e_memoria_no_mesmo_ciclo` | Verifica a publicação das duas métricas no mesmo ciclo. | APROVADO |
| `test_reconexao_automatica_esta_configurada` | Verifica a configuração de reconexão automática. | APROVADO |

**Resultado obtido:**

- Total de testes: 4.
- Testes aprovados: 4.
- Testes reprovados: 0.

**Status: APROVADO.**

### 5.3. Testes automatizados de integração

Foi executado novamente o arquivo `tests/test_integration.py` para verificar o recebimento das mensagens e a atualização do estado central.

**Comando utilizado:**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_integration.py" -v
```

Foram realizados quatro testes:

| Teste | Descrição | Resultado |
|---|---|---|
| `test_filtro_wildcard` | Verifica o filtro padrão utilizado pelo Subscriber. | APROVADO |
| `test_recebimento_cpu_valida` | Verifica o recebimento e armazenamento de CPU. | APROVADO |
| `test_recebimento_memoria_valida` | Verifica o recebimento e armazenamento de RAM. | APROVADO |
| `test_mensagem_invalida_nao_atualiza_estado` | Verifica a rejeição de mensagens inválidas sem alteração do último valor válido. | APROVADO |

**Resultado obtido:**

- Total de testes: 4.
- Testes aprovados: 4.
- Testes reprovados: 0.

Durante a execução, o sistema registrou a rejeição de uma mensagem com CPU de 112,5%, mantendo o último valor válido armazenado.

**Status: APROVADO.**

## 6. Testes manuais de integração ? Segunda entrega

### 6.1. Teste com múltiplos Publishers

**Objetivo:** verificar a execução simultânea de três agentes de monitoramento conectados ao mesmo broker MQTT.

**Procedimento:**

1. Inicialização do broker Mosquitto.
2. Execução do Subscriber utilizando o filtro `monitoramento/+/+`.
3. Execução simultânea de três Publishers com identificadores diferentes:
   - `maquina01`
   - `maquina02`
   - `maquina03`
4. Configuração do intervalo de publicação de 5 segundos.
5. Verificação das mensagens recebidas e da tabela consolidada.

**Resultado obtido:**

Os três agentes conectaram-se ao mesmo broker e publicaram continuamente suas métricas de CPU e memória RAM, utilizando identificadores distintos.

O Mosquitto confirmou as conexões dos clientes `agente-maquina01`, `agente-maquina02` e `agente-maquina03`, além do recebimento e encaminhamento das publicações ao monitor central.

O Subscriber registrou as três máquinas separadamente na tabela consolidada.

Na captura realizada às 18:52:08 de 21/11/2026, foram observados os seguintes dados:

| Máquina | CPU | RAM |
|---|---:|---:|
| maquina01 | 36,1% | 3320,8 MB |
| maquina02 | 35,3% | 3233,8 MB |
| maquina03 | 29,2% | 3298,2 MB |

O monitor central apresentou:

- Total de máquinas registradas: 3.
- Mensagens recebidas: 158.
- Mensagens descartadas: 0.

As métricas e os horários de atualização foram exibidos separadamente para cada máquina.

**Status: APROVADO.**

**Observação:** os três agentes foram executados no mesmo computador, utilizando identificadores diferentes e conectados ao broker local. A comunicação entre três computadores físicos distintos ainda não foi validada.

### 6.2. Teste da tabela consolidada

**Objetivo:** verificar se o monitor central apresenta as métricas de todas as máquinas em uma única tabela.

**Procedimento:** execução simultânea dos três Publishers e do Subscriber, observando a atualização periódica da tabela.

**Resultado obtido:** a tabela apresentou as três máquinas, com seus respectivos valores de CPU, memória RAM e horários da última atualização.

O monitor também apresentou o total de mensagens recebidas e descartadas.

**Status: APROVADO.**

## 7. Testes pendentes de execução


### 7.1. Desconexão e reconexão do broker

**Resultado obtido:**

Após a interrupção e reinicialização do broker Mosquitto, o Subscriber identificou a desconexão e iniciou automaticamente as tentativas de reconexão.

Após o restabelecimento do broker, o Subscriber conectou-se novamente e refez a assinatura do filtro `monitoramento/+/+`.

Os três Publishers também reconectaram automaticamente, sem necessidade de reiniciar os programas Python.

**Status: APROVADO.**

## 8. Evidências dos testes

As principais evidências são os registros dos terminais utilizados durante as execuções.

Devem ser reunidas capturas ou logs que demonstrem:

- Inicialização do broker Mosquitto.
- Conexão dos três Publishers.
- Conexão e assinatura do Subscriber.
- Publicação das métricas de CPU e memória RAM.
- Tabela consolidada com as três máquinas.
- Contadores de mensagens recebidas e descartadas.
- Rejeição de mensagens inválidas.
- Resultados da execução dos testes automatizados.
- Desconexão e reconexão do broker Mosquitto, incluindo os registros de reconexão automática dos três Publishers e do Subscriber.

## 9. Conclusão

Os testes realizados demonstraram o funcionamento dos principais componentes do sistema distribuído de monitoramento utilizando MQTT.

Na primeira entrega, foi validada a comunicação básica entre Publisher, broker Mosquitto e Subscriber, além do funcionamento das validações do protocolo e do armazenamento das métricas em memória.

Na segunda entrega, foram ampliados os testes automatizados e realizada a integração prática de três agentes de monitoramento conectados simultaneamente ao mesmo broker.

O monitor central conseguiu registrar as três máquinas, apresentar suas métricas de CPU e memória RAM separadamente e atualizar os respectivos horários de recebimento.

Durante o teste com múltiplos agentes, foram recebidas 158 mensagens, sem registros de mensagens descartadas.

Os testes automatizados gerais e os testes específicos de Publisher e integração também apresentaram resultados aprovados nas execuções registradas neste documento.

O teste de desconexão e reconexão também foi realizado, confirmando a recuperação automática das conexões dos três Publishers e do Subscriber após o restabelecimento do broker Mosquitto.