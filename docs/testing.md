# Relat�rio de Testes ? Equipe 06 - Entrega 1

## 1. Objetivo

Apresentamos os testes realizados na primeira entrega do sistema distribu�do de monitoramento utilizando MQTT.

Os testes t�m como objetivo verificar a comunica��o entre o Publisher, o broker Mosquitto e o Subscriber, al�m de conferir o funcionamento das valida��es do protocolo e do armazenamento das m�tricas em mem�ria.

## 2. Ambiente de testes

- Sistema operacional: Windows
- Linguagem: Python 3.13
- Broker MQTT: Eclipse Mosquitto 2.1.2
- Protocolo: MQTT
- Porta: 1883
- Endere�o do broker: 127.0.0.1
- M�tricas monitoradas: CPU e mem�ria RAM
- Intervalo de publica��o: 5 segundos
- QoS: 0

## 3. Testes manuais realizados

### 3.1. Inicializa��o do broker Mosquitto

**Procedimento:** inicializa��o do Mosquitto utilizando o arquivo de configura��o `config/mosquitto.conf`.

**Resultado obtido:** o broker iniciou corretamente e ficou dispon�vel na porta 1883.

**Status:** APROVADO.

### 3.2. Comunica��o b�sica entre Publisher e Subscriber

**Procedimento:** utiliza��o dos comandos `mosquitto_pub` e `mosquitto_sub` para publicar e receber uma mensagem de teste no t�pico `teste/equipe06`, utilizando o wildcard `#`.

**Resultado obtido:** a mensagem "Teste de comunicacao MQTT" foi recebida corretamente pelo subscriber.

**Status:** APROVADO.

### 3.3. Integra��o entre os componentes do sistema

**Procedimento:**
1. Inicializa��o do broker Mosquitto.
2. Execu��o do monitor central por meio de `server.subscriber`.
3. Execu��o do agente por meio de `agent.publisher`, utilizando o identificador `maquina01` e intervalo de 5 segundos.

**Resultado obtido:** o Publisher conectou-se ao broker e publicou as m�tricas de CPU e mem�ria RAM. O Subscriber recebeu corretamente as mensagens, exibindo valores, unidades, timestamps e informa��es complementares.

Foram utilizados os t�picos:

- `monitoramento/maquina01/cpu`
- `monitoramento/maquina01/memoria`

**Status:** APROVADO.

### 3.4. Recebimento utilizando wildcard +

**Procedimento:** execu��o do Subscriber com o filtro `monitoramento/+/+`.

**Resultado obtido:** o monitor central recebeu corretamente as mensagens de CPU e mem�ria RAM publicadas pelo agente.

**Status:** APROVADO.

### 3.5. Recebimento utilizando wildcard #

**Procedimento:** execu��o do Subscriber com o filtro `monitoramento/#`, seguida da publica��o das m�tricas pelo agente.

**Resultado obtido:** as mensagens correspondentes aos t�picos de CPU e mem�ria RAM foram recebidas corretamente.

**Status:** APROVADO.

### 3.6. Valida��o de mensagens v�lidas e inv�lidas

**Procedimento:** publica��o de duas mensagens de CPU no t�pico `monitoramento/maquina01/cpu`.

- Mensagem v�lida: CPU de 25,5%.
- Mensagem inv�lida: CPU de 112,5%.

**Resultado obtido:** a mensagem v�lida foi recebida e armazenada. A mensagem inv�lida foi rejeitada pela valida��o do protocolo, pois ultrapassava o limite de 100%.

Foi verificado que o valor inv�lido n�o substituiu a �ltima leitura v�lida no estado em mem�ria.

**Status:** APROVADO.

## 4. Testes automatizados

Foi criado o arquivo `tests/test_integration.py`, utilizando a biblioteca `unittest` do Python.

Foram implementados quatro testes:

| Teste | Descri��o | Resultado |
|---|---|---|
| `test_filtro_wildcard` | Verifica o filtro padr�o do Subscriber. | APROVADO |
| `test_recebimento_cpu_valida` | Verifica o recebimento e armazenamento de CPU. | APROVADO |
| `test_recebimento_memoria_valida` | Verifica o recebimento e armazenamento de RAM. | APROVADO |
| `test_mensagem_invalida_nao_atualiza_estado` | Verifica a rejei��o de mensagens inv�lidas. | APROVADO |

**Comando utilizado para execu��o:**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_integration.py" -v
```

**Resultado obtido:**

- Total de testes: 4.
- Testes aprovados: 4.
- Testes reprovados: 0.

**Status: APROVADO.**

Os testes automatizados verificam o processamento das mensagens pelo callback do Subscriber, incluindo valida��o e atualiza��o do estado em mem�ria. A comunica��o real com o broker foi verificada separadamente nos testes manuais.

## 5. Conclus�o

Os testes realizados demonstraram o funcionamento da comunica��o MQTT entre o agente de monitoramento, o broker Mosquitto e o monitor central.

Foi poss�vel verificar a publica��o peri�dica das m�tricas de CPU e mem�ria RAM, o recebimento das mensagens por meio dos wildcards definidos na arquitetura e a rejei��o de dados que n�o respeitam as regras do protocolo.

Os quatro testes automatizados tamb�m foram executados com sucesso.

Dessa forma, os testes realizados atendem �s verifica��es b�sicas de integra��o previstas para a primeira entrega do projeto.