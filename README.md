# Monitoramento Distribuído de Desempenho via MQTT

**Universidade Federal de Pernambuco (UFPE)**  
**Centro de Informática (CIn)**  
**Disciplina:** CIN0143 ? Introdução aos Sistemas Distribuídos e Redes de Computadores  
**Equipe:** 06

## 1. Descrição do projeto

Este projeto tem como objetivo desenvolver um sistema distribuído para monitoramento de desempenho de computadores, utilizando o protocolo MQTT e a arquitetura Publisher/Subscriber.

O sistema permite coletar métricas de CPU e memória RAM de diferentes máquinas e enviá-las para um monitor central, responsável por receber, organizar e apresentar as informações.

A comunicação é intermediada pelo broker MQTT Eclipse Mosquitto, permitindo que os agentes publiquem informações sem depender de uma comunicação direta com o monitor central.

## 2. Tecnologias utilizadas

| Tecnologia | Finalidade |
|---|---|
| Python | Desenvolvimento dos agentes e do monitor central |
| MQTT | Protocolo de comunicação entre os componentes |
| Eclipse Mosquitto | Broker responsável pelo encaminhamento das mensagens |
| Paho MQTT | Biblioteca Python utilizada para comunicação MQTT |
| psutil | Biblioteca Python utilizada para coleta das métricas |
| JSON | Formato das mensagens transmitidas |
| unittest | Biblioteca utilizada para os testes automatizados |

### Justificativa da escolha

O MQTT foi escolhido por ser um protocolo leve, apropriado para a transmissão periódica de informações entre dispositivos distribuídos.

A arquitetura Publisher/Subscriber permite desacoplar os agentes responsáveis pela coleta do monitor central responsável pela visualização.

O Eclipse Mosquitto foi selecionado por ser um broker MQTT de código aberto, compatível com a arquitetura proposta e de fácil execução em ambiente local.

## 3. Arquitetura do sistema

O sistema é composto por três elementos principais:

**Agente (Publisher):** executado em cada computador monitorado. É responsável por coletar métricas de CPU e memória RAM e publicar os dados em tópicos MQTT.

**Broker MQTT (Mosquitto):** recebe as publicações dos agentes e encaminha as mensagens aos clientes inscritos nos tópicos correspondentes.

**Monitor central (Subscriber):** recebe as mensagens utilizando wildcards MQTT, organiza o estado das máquinas em memória e apresenta as informações em uma tabela consolidada no terminal.

Fluxo de comunicação:

```text
        Agente 1 (Publisher) ??????
                                 ?
        Agente 2 (Publisher) ????????? Broker MQTT
                                 ?       Mosquitto
        Agente N (Publisher) ??????          ?
                                            ?
                                    Monitor central
                                      (Subscriber)
                                            ?
                                            ?
                                     Estado em memória
                                            ?
                                            ?
                                  Tabela consolidada
```

A documentação detalhada da arquitetura está disponível em [docs/architecture.md](docs/architecture.md).

## 4. Métricas monitoradas

As duas métricas escolhidas são:

- **CPU:** percentual geral de utilização e informações de utilização por núcleo lógico.
- **Memória RAM:** quantidade total, utilizada e livre.

A coleta é realizada com a biblioteca Python `psutil`.

O intervalo de amostragem padrão é de **5 segundos**, podendo ser configurado na execução do agente.

## 5. Hierarquia de tópicos MQTT

Os tópicos seguem o padrão:

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

monitoramento/maquina03/cpu
monitoramento/maquina03/memoria
```

### Utilização de wildcards

O monitor central utiliza wildcards MQTT para receber as métricas de diferentes computadores.

| Assinatura | Finalidade |
|---|---|
| `monitoramento/+/cpu` | Receber CPU de todas as máquinas |
| `monitoramento/+/memoria` | Receber memória de todas as máquinas |
| `monitoramento/+/+` | Receber CPU e memória de todas as máquinas |
| `monitoramento/#` | Receber todos os tópicos abaixo de `monitoramento` |

O wildcard `+` representa exatamente um nível do tópico, enquanto `#` representa todos os níveis restantes.

Os wildcards são utilizados nas assinaturas do Subscriber, não nos tópicos de publicação dos agentes.

### Qualidade de serviço (QoS)

Foi escolhido **QoS 0** para a transmissão periódica das métricas.

Essa configuração prioriza simplicidade e baixo custo de comunicação. Como novas leituras são publicadas regularmente, a perda eventual de uma mensagem pode ser compensada por uma medição posterior.

O QoS 0 não garante a entrega de cada publicação.

## 6. Formato das mensagens

As mensagens são transmitidas em JSON, seguindo o contrato definido em `docs/protocol.md`.

Exemplo de uma publicação de CPU:

```json
{
  "valor": 25.5,
  "unidade": "%",
  "timestamp": "2026-11-21T18:00:00-03:00"
}
```

Exemplo de uma publicação de memória:

```json
{
  "valor": 8192,
  "unidade": "MB",
  "timestamp": "2026-11-21T18:00:00-03:00"
}
```

Esses exemplos representam o formato mínimo das mensagens. O agente também publica informações complementares no campo opcional `detalhes`, como utilização por núcleo da CPU e informações de memória total, livre e percentual.

O protocolo define os campos obrigatórios, as unidades, os identificadores das máquinas e as regras de validação, disponíveis em [docs/protocol.md](docs/protocol.md).

## 7. Modelagem do estado central

O monitor central mantém os dados em memória, organizados por identificador de máquina.

Para cada computador, a estrutura implementada armazena:

- Identificador da máquina.
- Últimas métricas de CPU recebidas.
- Últimas métricas de memória RAM recebidas.
- Data e horário da última atualização.

Essa estrutura está implementada no componente `server/state.py`, utilizando estruturas em memória e mecanismos de sincronização para proteger o acesso concorrente aos dados.

Cada máquina mantém suas próprias métricas, evitando que as atualizações de um agente sobrescrevam as informações dos demais.

O Subscriber consulta esse estado para apresentar as informações na tabela consolidada do terminal.

## 8. Estrutura do repositório

```text
monitoramento-distribuido-mqtt/
??? agent/
?   ??? collector.py
?   ??? publisher.py
?
??? common/
?   ??? validation.py
?
??? config/
?   ??? mosquitto.conf
?
??? docs/
?   ??? architecture.md
?   ??? protocol.md
?   ??? testing.md
?
??? server/
?   ??? state.py
?   ??? subscriber.py
?
??? tests/
?   ??? test_integration.py
?   ??? test_publisher.py
?   ??? test_state.py
?   ??? test_validation.py
?   ??? test_visualizacao.py
?
??? .gitignore
??? README.md
??? requirements.txt
```

As pastas possuem as seguintes responsabilidades:

- `agent/`: contém os componentes responsáveis pela coleta e publicação das métricas.
- `common/`: contém as funções compartilhadas de validação do protocolo.
- `config/`: contém a configuração do broker Mosquitto.
- `docs/`: reúne a documentação da arquitetura, do protocolo e dos testes.
- `server/`: contém o monitor central e a implementação do estado em memória.
- `tests/`: contém os testes automatizados dos componentes e da integração do sistema.

## 9. Instalação do ambiente

### Pré-requisitos

Para executar o projeto, é necessário ter:

- Python 3 instalado.
- Eclipse Mosquitto instalado.
- Bibliotecas Python definidas em `requirements.txt`.

No Windows, o Mosquitto pode ser instalado utilizando o instalador disponibilizado no site oficial:

https://mosquitto.org/download/

No macOS, a instalação pode ser realizada com o Homebrew:

```bash
brew install mosquitto
```

Para verificar se o Mosquitto está disponível:

```bash
mosquitto -h
```

### Configuração do ambiente Python

Na raiz do repositório, crie um ambiente virtual.

No Windows (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

No Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

### Configuração do broker

O arquivo `config/mosquitto.conf` contém:

```conf
listener 1883 127.0.0.1
allow_anonymous true
```

Essa configuração permite conexões MQTT locais na porta `1883`.

**Importante:** o broker está limitado ao endereço `127.0.0.1`, exclusivamente para desenvolvimento e testes no mesmo computador. A comunicação entre diferentes máquinas exigirá uma configuração de rede apropriada e mecanismos de segurança.

## 10. Como executar o projeto

Todos os comandos devem ser executados a partir da raiz do repositório.

Para a execução completa, são necessários cinco terminais: um para o broker, um para o monitor central e três para os agentes de monitoramento.

### Terminal 1 ? Iniciar o broker

No Windows (PowerShell):

```powershell
& "C:\Program Files\mosquitto\mosquitto.exe" -c ".\config\mosquitto.conf" -v
```

No Linux/macOS:

```bash
mosquitto -c config/mosquitto.conf -v
```

O broker deverá iniciar na porta `1883`.

Caso a porta já esteja sendo utilizada por outra instância do Mosquitto, verifique o serviço em execução antes de iniciar outro broker.

### Terminal 2 ? Iniciar o Subscriber

No Windows:

```powershell
.\.venv\Scripts\python.exe -m server.subscriber
```

No Linux/macOS:

```bash
python -m server.subscriber
```

O Subscriber utilizará o filtro padrão:

```text
monitoramento/+/+
```

A tabela consolidada será atualizada automaticamente a cada 5 segundos, conforme a configuração padrão.

Também é possível configurar o intervalo de atualização:

```powershell
.\.venv\Scripts\python.exe -m server.subscriber --intervalo-tabela 5
```

### Terminal 3 ? Iniciar o Publisher da maquina01

No Windows:

```powershell
.\.venv\Scripts\python.exe -m agent.publisher --id maquina01 --intervalo 5
```

No Linux/macOS:

```bash
python -m agent.publisher --id maquina01 --intervalo 5
```

### Terminal 4 ? Iniciar o Publisher da maquina02

No Windows:

```powershell
.\.venv\Scripts\python.exe -m agent.publisher --id maquina02 --intervalo 5
```

No Linux/macOS:

```bash
python -m agent.publisher --id maquina02 --intervalo 5
```

### Terminal 5 ? Iniciar o Publisher da maquina03

No Windows:

```powershell
.\.venv\Scripts\python.exe -m agent.publisher --id maquina03 --intervalo 5
```

No Linux/macOS:

```bash
python -m agent.publisher --id maquina03 --intervalo 5
```

### Executar com outros identificadores

É possível iniciar outros agentes utilizando identificadores diferentes, desde que cada um siga as regras definidas no protocolo.

Exemplo:

```bash
python -m agent.publisher --id maquina04 --intervalo 5
```

Cada Publisher realizará a coleta e publicação das métricas de CPU e memória RAM de forma independente.

### Resultado esperado

O terminal do Subscriber deverá exibir uma tabela consolidada semelhante a:

```text
Monitor central | broker 127.0.0.1:1883 (conectado)

MÁQUINA    CPU     RAM                ÚLTIMA ATUALIZAÇÃO
---------  ------  -----------------  ------------------
maquina01  36.1 %  3320.8 MB (91.8%)  18:52:07 (há 0s)
maquina02  35.3 %  3233.8 MB (89.4%)  18:52:05 (há 3s)
maquina03  29.2 %  3298.2 MB (91.2%)  18:52:06 (há 1s)
```

Os valores apresentados são ilustrativos. As métricas exibidas correspondem aos dados coletados pelos agentes em execução.

## 11. Testes realizados

Foram realizados testes manuais e automatizados para verificar o funcionamento dos componentes do sistema.

Os testes manuais contemplaram:

- Inicialização do Mosquitto utilizando o arquivo `config/mosquitto.conf`.
- Comunicação básica entre Publisher e Subscriber utilizando os comandos `mosquitto_pub` e `mosquitto_sub`.
- Conexão dos componentes Python com o broker MQTT.
- Publicação e recebimento das métricas de CPU e memória RAM.
- Verificação do intervalo de publicação de 5 segundos.
- Recebimento de mensagens utilizando o wildcard `+`.
- Recebimento de mensagens utilizando o wildcard `#`.
- Aceitação de mensagens válidas.
- Rejeição de mensagens inválidas, incluindo valores de CPU acima de 100%.
- Execução simultânea de três Publishers com identificadores diferentes.
- Atualização da tabela consolidada com as informações das três máquinas.
- Desconexão e reconexão automática dos clientes após a interrupção e o restabelecimento do broker Mosquitto.

Também foram realizados testes automatizados utilizando a biblioteca `unittest` do Python.

Na execução geral da suíte de testes, foram obtidos os seguintes resultados:

- Total de testes executados: 104.
- Testes aprovados: 104.
- Testes reprovados: 0.
- Tempo de execução: aproximadamente 2,385 segundos.

O arquivo `tests/test_publisher.py` foi executado separadamente, apresentando:

- Total de testes: 4.
- Testes aprovados: 4.
- Testes reprovados: 0.

O arquivo `tests/test_integration.py` também foi executado separadamente, apresentando:

- Total de testes: 4.
- Testes aprovados: 4.
- Testes reprovados: 0.

### Teste com múltiplos agentes

Foi realizada uma execução prática com três Publishers simultâneos:

- `maquina01`
- `maquina02`
- `maquina03`

Durante o teste, o monitor central apresentou as três máquinas separadamente na tabela consolidada.

Na execução registrada, foram observados:

- Total de máquinas registradas: 3.
- Mensagens recebidas: 158.
- Mensagens descartadas: 0.

O teste demonstrou que os três agentes conseguiram publicar suas métricas utilizando o mesmo broker MQTT.

### Teste de desconexão e reconexão

Foi realizada a interrupção e a reinicialização do broker Mosquitto durante a execução dos componentes.

O Subscriber identificou a perda da conexão, iniciou tentativas de reconexão e, após o restabelecimento do broker, conectou-se novamente e refez a assinatura do filtro `monitoramento/+/+`.

Os três Publishers também reconectaram automaticamente, sem necessidade de reiniciar os programas Python.

Os procedimentos completos e os resultados dos testes estão disponíveis em [docs/testing.md](docs/testing.md).

### Executar os testes automatizados

No Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

No Linux/macOS:

```bash
python -m unittest discover -s tests -v
```

## 12. Estado atual do projeto

A segunda entrega do projeto ampliou a implementação dos componentes MQTT, permitindo o monitoramento simultâneo de múltiplas máquinas, a visualização consolidada das métricas e a recuperação automática das conexões.

Atualmente, o sistema possui:

- Agentes Publishers em Python, responsáveis pela coleta e publicação das métricas de CPU e memória RAM.
- Execução simultânea de múltiplos Publishers utilizando identificadores diferentes.
- Broker Eclipse Mosquitto configurado para execução local.
- Monitor central Subscriber, responsável por receber mensagens utilizando wildcards MQTT.
- Tabela consolidada com CPU, memória RAM e última atualização de cada máquina.
- Atualização periódica das informações no monitor central.
- Estrutura de armazenamento do estado das máquinas em memória.
- Módulo compartilhado de validação das mensagens.
- Tratamento de mensagens inválidas, impedindo alterações indevidas no estado central.
- Reconexão automática dos Publishers e do Subscriber após a interrupção do broker.
- Documentação da arquitetura e do protocolo.
- Testes manuais e automatizados de integração.

Os testes realizados demonstraram o funcionamento dos principais componentes e a comunicação simultânea de três agentes com o monitor central em ambiente local.

## 13. Limitações da configuração atual

- Os testes de comunicação com múltiplos agentes foram realizados localmente, utilizando `127.0.0.1` e identificadores diferentes.
- A comunicação entre três computadores físicos distintos ainda não foi validada.
- A configuração atual do broker permite acesso anônimo somente na interface local.
- Não foram implementados mecanismos de autenticação e criptografia para comunicação externa.
- O estado das máquinas é mantido em memória, sem persistência após o encerramento do monitor central.