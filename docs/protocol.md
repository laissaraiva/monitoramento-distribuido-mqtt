# Especificação do protocolo de comunicação MQTT

## 1. Visão geral

Este documento define o contrato formal de comunicação entre os agentes de monitoramento (publishers) e o monitor central (subscriber) por meio do broker Eclipse Mosquitto, complementando a arquitetura definida em [docs/architecture.md](architecture.md).

O protocolo padroniza:
1. A estrutura e as regras de validação dos tópicos MQTT;
2. As regras de formação do identificador da máquina (`id_maquina`);
3. O schema JSON dos payloads de CPU e memória RAM (formato mínimo obrigatório e formato estendido opcional);
4. As faixas válidas de valores, unidades e formato de timestamp;
5. O comportamento esperado diante de mensagens válidas e inválidas.

---

## 2. Estrutura de tópicos e QoS

### 2.1. Padrão de publicação

Cada agente publica cada métrica em um tópico próprio, seguindo rigorosamente a hierarquia de três níveis:

```text
monitoramento/<id_maquina>/<metrica>
```

Em que:
- **`monitoramento`**: prefixo fixo raiz do sistema;
- **`<id_maquina>`**: identificador único da máquina monitorada (regras na seção 3.);
- **`<metrica>`**: nome padronizado da métrica (`cpu` ou `memoria`).

Tópicos válidos:
- `monitoramento/<id_maquina>/cpu`
- `monitoramento/<id_maquina>/memoria`

> **Sobre wildcards MQTT:** Os curingas `+` (nível único) e `#` (múltiplos níveis), como `monitoramento/+/+` ou `monitoramento/#`, são utilizados exclusivamente na assinatura (`SUBSCRIBE`) pelo monitor central. Em mensagens publicadas (`PUBLISH`), o tópico recebido pelo subscriber não pode conter `+` ou `#`.

### 2.2. Qualidade de Serviço (QoS)

- **QoS adotado:** `0` (*At most once* —> no máximo uma entrega);
- **Justificativa:** Como as leituras são periódicas (padrão de 5 segundos), o envio contínuo sem confirmação de recebimento reduz latência e sobrecarga de rede; eventual perda pontual é naturalmente suprida pela amostra seguinte.

---

## 3. Regras para o identificador da máquina (`id_maquina`)

O campo `<id_maquina>` é extraído do segundo nível do tópico MQTT e identifica a origem dos dados na estrutura em memória do monitor central.

### 3.1. Restrições sintáticas

1. **Tipo:** string (`str`) não vazia;
2. **Comprimento:** mínimo de **2** e máximo de **64** caracteres;
3. **Caracteres permitidos:** apenas letras ASCII sem acento (`a-z`, `A-Z`), dígitos (`0-9`), hífen (`-`) e sublinhado (`_`);
4. **Início e fim:** deve começar e terminar obrigatoriamente com caractere alfanumérico (`a-z`, `A-Z`, `0-9`);
5. **Caracteres proibidos:** espaços em branco, acentos, barras (`/`), curingas MQTT (`+`, `#`) e caracteres de controle.

Expressão regular canônica:

```regex
^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}[a-zA-Z0-9]$
```

### 3.2. Exemplos de `id_maquina`

| Identificador | Status | Motivo |
|---|---|---|
| `maquina01` | Válido | Alfanumérico, 9 caracteres |
| `pc-lab-02` | Válido | Letras, dígitos e hífens internos |
| `ubuntu_node_1` | Válido | Letras, dígitos e sublinhados internos |
| `m1` | Válido | Comprimento mínimo (2 caracteres alfanuméricos) |
| `""` (vazio) | Inválido | String vazia |
| `a` | Inválido | Comprimento inferior a 2 caracteres |
| `maquina/01` | Inválido | Contém separador de nível MQTT (`/`) |
| `maquina+1` | Inválido | Contém wildcard MQTT (`+`) |
| `#` | Inválido | Contém wildcard MQTT (`#`) |
| `maquina 01` | Inválido | Contém espaço em branco |
| `-maquina01` | Inválido | Inicia com hífen (deve iniciar com alfanumérico) |

---

## 4. Formato do payload JSON

Toda mensagem publicada deve ser codificada em **UTF-8** contendo um **objeto JSON (`dict`)** no nível raiz.

### 4.1. Campos obrigatórios (em todas as métricas)

| Campo | Tipo JSON | Obrigatório | Descrição e regras |
|---|---|---|---|
| `valor` | `number` (`int` ou `float`) | Sim | Valor principal da medição. Rejeita strings (`"25.5"`), booleanos (`true`/`false`), `null`, `NaN` e `Infinity`. |
| `unidade` | `string` | Sim | Unidade de medida associada ao `valor`. Deve corresponder exatamente à métrica do tópico (`"%"` para `cpu`; `"MB"` para `memoria`). |
| `timestamp` | `string` | Sim | Data e hora da coleta no formato **ISO 8601 com fuso horário explícito** (offset `±HH:MM` ou sufixo `Z` para UTC). Ex.: `"2026-11-16T22:00:00-03:00"`. |

> **Por que exigir fuso horário no `timestamp`?** Em sistemas distribuídos, agentes podem rodar em máquinas com configurações de fuso distintas ou em containers UTC. Exigir offset explícito (`-03:00` ou `Z`) elimina ambiguidades na ordenação temporal e no cálculo de última atualização no Monitor Central.

### 4.2. Campo complementar opcional (`detalhes`)

Para suportar tanto clientes simples (como testes manuais via `mosquitto_pub`) quanto agentes completos em Python (`psutil`), o payload aceita o campo opcional **`detalhes`** (objeto JSON), validado sempre que estiver presente:

#### A) Métrica `cpu` (`monitoramento/<id_maquina>/cpu`)

- **`valor` (obrigatório):** percentual médio geral de utilização da CPU.
  - **Faixa válida:** $0.0 \le \text{valor} \le 100.0$
  - **Unidade obrigatória:** `"%"`
- **`detalhes` (opcional):** objeto contendo:
  - `por_nucleo` (`list[number]`, opcional): lista não vazia com o percentual de uso de cada núcleo lógico da CPU, onde cada elemento deve satisfazer $0.0 \le x \le 100.0$.

#### B) Métrica `memoria` (`monitoramento/<id_maquina>/memoria`)

- **`valor` (obrigatório):** quantidade de memória RAM utilizada.
  - **Faixa válida:** $\text{valor} \ge 0$ (e, caso `detalhes.total` seja informado, $\text{valor} \le \text{total}$).
  - **Unidade obrigatória:** `"MB"`
- **`detalhes` (opcional):** objeto contendo:
  - `total` (`number`, opcional): memória RAM física total instalada em MB ($\text{total} > 0$).
  - `livre` (`number`, opcional): memória RAM disponível/livre em MB ($\text{livre} \ge 0$). Se `total` também for informado, deve respeitar $\text{livre} \le \text{total}$ e a consistência $\text{valor} + \text{livre} \le \text{total}$ (com tolerância de 1% + 1 MB para arredondamentos).
  - `percentual` (`number`, opcional): percentual de memória RAM utilizada ($0.0 \le \text{percentual} \le 100.0$).

### 4.3. Resumo das regras de validação por métrica

| Métrica (tópico) | `unidade` esperada | Faixa de `valor` | Campos permitidos na raiz | Campos permitidos em `detalhes` |
|---|---|---|---|---|
| `cpu` | `"%"` | `0.0 <= valor <= 100.0` | `valor`, `unidade`, `timestamp`, `detalhes` (opc.) | `por_nucleo` (opc.) |
| `memoria` | `"MB"` | `valor >= 0` (e `<= total`) | `valor`, `unidade`, `timestamp`, `detalhes` (opc.) | `total`, `livre`, `percentual` (opcs.) |

---

## 5. Exemplos de mensagens válidas

### 5.1. CPU — formato mínimo (compatível com testes CLI)

**Tópico:** `monitoramento/maquina01/cpu`

```json
{
  "valor": 25.5,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```

### 5.2. CPU — formato estendido (com uso por núcleo lógico)

**Tópico:** `monitoramento/pc-lab-02/cpu`

```json
{
  "valor": 32.4,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:05-03:00",
  "detalhes": {
    "por_nucleo": [28.0, 35.2, 31.4, 35.0]
  }
}
```

### 5.3. Memória RAM — formato mínimo (compatível com testes CLI)

**Tópico:** `monitoramento/maquina01/memoria`

```json
{
  "valor": 8192,
  "unidade": "MB",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```

### 5.4. Memória RAM — formato estendido (com total, livre e percentual)

**Tópico:** `monitoramento/ubuntu_node_1/memoria`

```json
{
  "valor": 6144.5,
  "unidade": "MB",
  "timestamp": "2026-11-17T01:00:10Z",
  "detalhes": {
    "total": 16384.0,
    "livre": 10239.5,
    "percentual": 37.5
  }
}
```

---

## 6. Exemplos de mensagens inválidas (devem ser rejeitadas)

As mensagens abaixo ilustram violações de protocolo que o módulo `common/validation.py` rejeita antes que os dados alterem o estado em memória do Monitor Central:

### 6.1. Campo obrigatório ausente (`timestamp` faltando)

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": 40.0,
  "unidade": "%"
}
```
- **Motivo da rejeição:** Campo obrigatório `timestamp` ausente no payload.

### 6.2. Tipo de dado incorreto (`valor` enviado como string)

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": "40.0",
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```
- **Motivo da rejeição:** `valor` deve ser numérico (`int` ou `float`), mas foi recebido como `str`.

### 6.3. Tipo booleano no lugar de número (`true` em Python é subclasse de `int`)

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": true,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```
- **Motivo da rejeição:** Valores booleanos (`true`/`false`) não são métricas numéricas válidas.

### 6.4. CPU fora da faixa permitida (`> 100.0` ou `< 0.0`)

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": 112.5,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```
- **Motivo da rejeição:** Percentual de CPU (`112.5`) excede o limite superior de `100.0%`.

### 6.5. Memória RAM negativa

**Tópico:** `monitoramento/maquina01/memoria`
```json
{
  "valor": -512,
  "unidade": "MB",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```
- **Motivo da rejeição:** Consumo de memória RAM (`-512`) não pode ser negativo (`valor < 0`).

### 6.6. Inconsistência matemática na RAM (`valor > total`)

**Tópico:** `monitoramento/maquina01/memoria`
```json
{
  "valor": 18000,
  "unidade": "MB",
  "timestamp": "2026-11-16T22:00:00-03:00",
  "detalhes": {
    "total": 16384,
    "livre": 0
  }
}
```
- **Motivo da rejeição:** A memória utilizada (`18000 MB`) é maior que a memória total instalada (`16384 MB`).

### 6.7. Unidade incompatível com a métrica do tópico

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": 45.0,
  "unidade": "MB",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```
- **Motivo da rejeição:** O tópico especifica a métrica `cpu`, que exige `unidade == "%"`, mas foi recebido `"MB"`.

### 6.8. Timestamp malformado ou sem fuso horário

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": 20.0,
  "unidade": "%",
  "timestamp": "16/11/2026 22:00:00"
}
```
- **Motivo da rejeição:** Formato inválido; deve seguir ISO 8601 com fuso horário (ex.: `"2026-11-16T22:00:00-03:00"`). Timestamps ISO sem fuso (ex.: `"2026-11-16T22:00:00"`) também são rejeitados.

### 6.9. JSON malformado (sintaxe quebrada)

**Tópico:** `monitoramento/maquina01/cpu`
```text
{"valor": 25.5, "unidade": "%", "timestamp":
```
- **Motivo da rejeição:** Payload não é um JSON sintaticamente válido (`JSONDecodeError`).

### 6.10. Tópico com `id_maquina` inválido

**Tópico:** `monitoramento/maquina+01/cpu`
```json
{
  "valor": 25.5,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```
- **Motivo da rejeição:** O identificador `maquina+01` contém o caractere curinga MQTT `+`, violando a regra de formação de `id_maquina`.

---

## 7. Fluxo de validação

O módulo `common/validation.py` fornece funções reutilizáveis (sem dependências externas, apenas biblioteca padrão do Python 3) para duas pontas do sistema:
1. **Agente (`agent/publisher.py`):** Pode validar o tópico e o payload antes de chamar `client.publish(...)`, evitando poluir o broker com mensagens fora do contrato.
2. **Monitor Central (`server/subscriber.py`):** Valida toda mensagem recebida no callback `on_message` antes de atualizar o dicionário de estado em memória. Mensagens inválidas são descartadas com registro de log de alerta, preservando a integridade do estado central.
