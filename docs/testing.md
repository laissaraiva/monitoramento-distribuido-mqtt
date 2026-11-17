# Relatório de Testes ? Equipe 06

## 1. Objetivo

Apresentamos os testes realizados na primeira entrega do sistema distribuído de monitoramento utilizando MQTT.

Os testes têm como objetivo verificar a comunicação entre o Publisher, o broker Mosquitto e o Subscriber, além de conferir o funcionamento das validações do protocolo e do armazenamento das métricas em memória.

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

## 3. Testes manuais realizados

### 3.1. Inicialização do broker Mosquitto

**Procedimento:** inicialização do Mosquitto utilizando o arquivo de configuração `config/mosquitto.conf`.

**Resultado obtido:** o broker iniciou corretamente e ficou disponível na porta 1883.

**Status:** APROVADO.

### 3.2. Comunicação básica entre Publisher e Subscriber

**Procedimento:** utilização dos comandos `mosquitto_pub` e `mosquitto_sub` para publicar e receber uma mensagem de teste no tópico `teste/equipe06`, utilizando o wildcard `#`.

**Resultado obtido:** a mensagem "Teste de comunicacao MQTT" foi recebida corretamente pelo subscriber.

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

## 4. Testes automatizados

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

## 5. Conclusão

Os testes realizados demonstraram o funcionamento da comunicação MQTT entre o agente de monitoramento, o broker Mosquitto e o monitor central.

Foi possível verificar a publicação periódica das métricas de CPU e memória RAM, o recebimento das mensagens por meio dos wildcards definidos na arquitetura e a rejeição de dados que não respeitam as regras do protocolo.

Os quatro testes automatizados também foram executados com sucesso.

Dessa forma, os testes realizados atendem às verificações básicas de integração previstas para a primeira entrega do projeto.