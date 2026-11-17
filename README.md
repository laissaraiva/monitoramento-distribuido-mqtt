# # Monitoramento Distribuído de Desempenho via MQTT

**Universidade Federal de Pernambuco (UFPE)**  
**Centro de Informática (CIn)**  
**Disciplina:** CIN0143 — Introdução aos Sistemas Distribuídos e Redes de Computadores  
**Equipe:** 06

## 1. Descrição do projeto

Este projeto tem como objetivo desenvolver um sistema distribuído para monitoramento de desempenho de computadores, utilizando o protocolo MQTT e a arquitetura Publisher/Subscriber.

O sistema permitirá coletar métricas de CPU e memória RAM de diferentes máquinas e enviá-las para um monitor central, responsável por receber, organizar e apresentar as informações.

A comunicação será intermediada pelo broker MQTT Eclipse Mosquitto, permitindo que os agentes publiquem informações sem depender de uma comunicação direta com o monitor central.

## 2. Tecnologias utilizadas

| Tecnologia | Finalidade |
|---|---|
| Python | Desenvolvimento dos agentes e do monitor central |
| MQTT | Protocolo de comunicação entre os componentes |
| Eclipse Mosquitto | Broker responsável pelo encaminhamento das mensagens |
| Paho MQTT | Biblioteca Python prevista para comunicação MQTT |
| psutil | Biblioteca Python prevista para coleta das métricas |
| JSON | Formato das mensagens transmitidas |

### Justificativa da escolha

O MQTT foi escolhido por ser um protocolo leve, apropriado para a transmissão periódica de informações entre dispositivos distribuídos.

A arquitetura Publisher/Subscriber permite desacoplar os agentes responsáveis pela coleta do monitor central responsável pela visualização.

O Eclipse Mosquitto foi selecionado por ser um broker MQTT de código aberto, compatível com a arquitetura proposta e de fácil execução em ambiente local.

## 3. Arquitetura do sistema

O sistema será composto por três elementos principais:

**Agente (Publisher):** executado em cada computador monitorado. Será responsável por coletar métricas de CPU e memória RAM e publicar os dados em tópicos MQTT.

**Broker MQTT (Mosquitto):** recebe as publicações dos agentes e encaminha as mensagens aos clientes inscritos nos tópicos correspondentes.

**Monitor central (Subscriber):** recebe as mensagens utilizando wildcards MQTT, organiza o estado das máquinas em memória e apresenta as informações recebidas.

Fluxo de comunicação:

```text
        Agente 1 (Publisher) ───┐
                               │
        Agente 2 (Publisher) ───┼──► Broker MQTT
                               │     Mosquitto
        Agente N (Publisher) ───┘         │
                                         ▼
                                 Monitor central
                                   (Subscriber)
                                         │
                                         ▼
                                  Estado em memória
```

A documentação detalhada da arquitetura está disponível em [docs/architecture.md](docs/architecture.md).

## 4. Métricas monitoradas

As duas métricas escolhidas são:

- **CPU:** percentual geral de utilização e informações de utilização por núcleo lógico.
- **Memória RAM:** quantidade total, utilizada e livre.

A coleta será realizada com a biblioteca Python `psutil`.

O intervalo inicial planejado de amostragem é de **5 segundos**, podendo ser configurado posteriormente.

## 5. Hierarquia de tópicos MQTT

Os tópicos seguirão o padrão:

```text
monitoramento/<id_maquina>/cpu
monitoramento/<id_maquina>/memoria
```

Exemplos:

```text
monitoramento/maquina01/cpu
monitoramento/maquina01/memoria

monitoramento/maquina02/cpu
monitoramento/maquina02/memoria
```

### Utilização de wildcards

O monitor central utilizará wildcards MQTT para receber as métricas de diferentes computadores.

| Assinatura | Finalidade |
|---|---|
| `monitoramento/+/cpu` | Receber CPU de todas as máquinas |
| `monitoramento/+/memoria` | Receber memória de todas as máquinas |
| `monitoramento/+/+` | Receber CPU e memória de todas as máquinas |
| `monitoramento/#` | Receber todos os tópicos abaixo de `monitoramento` |

O wildcard `+` representa exatamente um nível do tópico, enquanto `#` representa todos os níveis restantes.

### Qualidade de serviço (QoS)

Foi escolhido **QoS 0** para a transmissão periódica das métricas.

Essa configuração prioriza simplicidade e baixo custo de comunicação. Como novas leituras serão publicadas regularmente, a perda eventual de uma mensagem pode ser compensada por uma medição posterior.

O QoS 0 não garante a entrega de cada publicação.

## 6. Formato preliminar das mensagens

As mensagens serão transmitidas em JSON.

Exemplo ilustrativo de uma publicação de CPU:

```json
{
  "valor": 25.5,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```

Exemplo ilustrativo de uma publicação de memória:

```json
{
  "valor": 8192,
  "unidade": "MB",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```

Esses exemplos foram utilizados para demonstrar a comunicação MQTT.

O contrato definitivo das mensagens, incluindo informações detalhadas das métricas, identificadores das máquinas, campos obrigatórios e regras de validação, será documentado em `docs/protocol.md`.

## 7. Modelagem do estado central

O monitor central manterá os dados em memória, organizados por identificador de máquina.

Para cada computador, a estrutura prevista armazenará:

- Identificador da máquina.
- Últimas métricas de CPU recebidas.
- Últimas métricas de memória RAM recebidas.
- Data e horário da última atualização.

Essa estrutura será implementada no componente responsável pelo monitor central.

## 8. Estrutura inicial do repositório

```text
monitoramento-distribuido-mqtt/
├── agent/
├── common/
├── config/
│   └── mosquitto.conf
├── docs/
│   └── architecture.md
├── server/
├── tests/
├── .gitignore
└── README.md
```

As pastas `agent`, `common`, `server` e `tests` foram preparadas para receber os componentes das próximas etapas de desenvolvimento.

## 9. Instalação do ambiente

### Pré-requisitos

Para executar a infraestrutura MQTT atual, é necessário ter o Eclipse Mosquitto instalado.

No macOS, a instalação pode ser realizada com o Homebrew:

```bash
brew install mosquitto
```

Para verificar se o Mosquitto está disponível:

```bash
mosquitto -h
```

### Configuração do broker

O arquivo `config/mosquitto.conf` contém:

```conf
listener 1883 127.0.0.1
allow_anonymous true
```

Essa configuração permite conexões MQTT locais na porta `1883`.

**Importante:** o broker está limitado ao endereço `127.0.0.1`, exclusivamente para desenvolvimento e testes no mesmo computador. A comunicação entre diferentes máquinas exigirá uma configuração de rede apropriada e mecanismos de segurança.

## 10. Como executar a infraestrutura MQTT

Todos os comandos devem ser executados a partir da raiz do repositório.

### Terminal 1 — Iniciar o broker

```bash
mosquitto -c config/mosquitto.conf -v
```

O broker deverá iniciar na porta `1883`.

### Terminal 2 — Iniciar um Subscriber de teste

```bash
mosquitto_sub -h 127.0.0.1 -p 1883 -t 'monitoramento/+/+' -q 0 -v
```

O Subscriber permanecerá aguardando mensagens dos tópicos correspondentes.

### Terminal 3 — Publicar uma métrica de CPU

```bash
mosquitto_pub -h 127.0.0.1 -p 1883 -q 0 -t 'monitoramento/maquina01/cpu' -m '{"valor":25.5,"unidade":"%","timestamp":"2026-11-16T22:00:00-03:00"}'
```

### Publicar uma métrica de memória RAM

```bash
mosquitto_pub -h 127.0.0.1 -p 1883 -q 0 -t 'monitoramento/maquina01/memoria' -m '{"valor":8192,"unidade":"MB","timestamp":"2026-11-16T22:00:00-03:00"}'
```

### Resultado esperado

O terminal do Subscriber deverá exibir:

```text
monitoramento/maquina01/cpu {"valor":25.5,"unidade":"%","timestamp":"2026-11-16T22:00:00-03:00"}

monitoramento/maquina01/memoria {"valor":8192,"unidade":"MB","timestamp":"2026-11-16T22:00:00-03:00"}
```

## 11. Testes realizados

Foi realizado um teste inicial da infraestrutura MQTT em ambiente local, utilizando o Eclipse Mosquitto 2.1.2 no macOS.

Os registros do broker confirmaram:

- Inicialização do Mosquitto na porta `1883`.
- Conexão de um Subscriber.
- Assinatura do tópico `monitoramento/+/+` com QoS 0.
- Recebimento de publicação no tópico `monitoramento/maquina01/cpu`.
- Encaminhamento da mensagem de CPU ao Subscriber.
- Recebimento de publicação no tópico `monitoramento/maquina01/memoria`.
- Encaminhamento da mensagem de memória ao Subscriber.
- Manutenção da conexão do Subscriber por meio das mensagens MQTT de keep-alive.

**Resultado:** a comunicação básica Publisher/Subscriber foi validada no ambiente local.

Esse teste utilizou os utilitários de linha de comando do Mosquitto. A integração com os componentes definitivos em Python ainda será desenvolvida.

## 12. Estado atual do projeto

A estrutura inicial do repositório, a documentação da arquitetura, a definição dos tópicos e a configuração local do broker MQTT foram preparadas.

A comunicação básica entre publicação e assinatura MQTT foi testada com sucesso.

As próximas implementações incluem:

- Definição definitiva do protocolo JSON e das validações.
- Desenvolvimento do agente Publisher em Python.
- Desenvolvimento do monitor central Subscriber.
- Implementação do armazenamento do estado em memória.
- Integração dos componentes e testes completos.

## 13. Limitações da configuração inicial

- Os testes de comunicação foram realizados localmente, usando `127.0.0.1`.
- A configuração atual do broker permite acesso anônimo somente na interface local.
- Ainda não foram implementados os agentes e o monitor central definitivos em Python.
- O contrato JSON completo e as validações específicas serão definidos na documentação do protocolo.
- A arquitetura foi preparada para múltiplas máquinas, mas essa comunicação ainda não foi testada em computadores físicos diferentes.