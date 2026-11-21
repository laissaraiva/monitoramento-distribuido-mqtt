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
| `timestamp` | `string` | Sim | Data e hora da coleta no formato **ISO 8601 estendido com fuso horário explícito** (offset `±HH:MM` ou sufixo `Z` para UTC). Ex.: `"2026-11-16T22:00:00-03:00"`. Formato exato na seção 4.5. |

> **Por que exigir fuso horário no `timestamp`?** Em sistemas distribuídos, agentes podem rodar em máquinas com configurações de fuso distintas ou em containers UTC. Exigir offset explícito (`-03:00` ou `Z`) elimina ambiguidades na ordenação temporal e no cálculo de última atualização no Monitor Central.

### 4.2. Campo complementar opcional (`detalhes`)

Para suportar tanto clientes simples (como testes manuais via `mosquitto_pub`) quanto agentes completos em Python (`psutil`), o payload aceita o campo opcional **`detalhes`** (objeto JSON), validado sempre que estiver presente:

#### A) Métrica `cpu` (`monitoramento/<id_maquina>/cpu`)

- **`valor` (obrigatório):** percentual médio geral de utilização da CPU.
  - **Faixa válida:** $0.0 \le \text{valor} \le 100.0$
  - **Unidade obrigatória:** `"%"`
- **`detalhes` (opcional):** objeto contendo:
  - `por_nucleo` (`list[number]`, opcional): lista não vazia com o percentual de uso de cada núcleo lógico da CPU, onde cada elemento deve satisfazer $0.0 \le x \le 100.0$.
  - **Consistência:** quando `por_nucleo` é informado, a média dos núcleos deve diferir de `valor` em no máximo **1,0 ponto percentual** (`TOLERANCIA_PERCENTUAL`). O agente calcula `valor` como a média dos núcleos, e a tolerância cobre apenas o arredondamento para uma casa decimal.

#### B) Métrica `memoria` (`monitoramento/<id_maquina>/memoria`)

- **`valor` (obrigatório):** quantidade de memória RAM utilizada.
  - **Faixa válida:** $\text{valor} \ge 0$ (e, caso `detalhes.total` seja informado, $\text{valor} \le \text{total}$).
  - **Unidade obrigatória:** `"MB"`
- **`detalhes` (opcional):** objeto contendo:
  - `total` (`number`, opcional): memória RAM física total instalada em MB ($\text{total} > 0$).
  - `livre` (`number`, opcional): memória RAM disponível/livre em MB ($\text{livre} \ge 0$). Se `total` também for informado, deve respeitar $\text{livre} \le \text{total}$ e a consistência $\text{valor} + \text{livre} \le \text{total}$ (com tolerância de 1% + 1 MB para arredondamentos).
  - `percentual` (`number`, opcional): percentual de memória RAM utilizada ($0.0 \le \text{percentual} \le 100.0$). Se `total` também for informado, deve corresponder a $\text{valor} / \text{total} \times 100$ com diferença máxima de **1,0 ponto percentual**.
- **Unidade:** todos os valores de memória (`valor`, `total` e `livre`) são expressos em **MB** (mebibytes, `bytes / 1024²`, arredondados para uma casa decimal pelo agente). Outras grafias (`"mb"`, `"GB"`, `"MiB"`) são rejeitadas.

### 4.3. Resumo das regras de validação por métrica

| Métrica (tópico) | `unidade` esperada | Faixa de `valor` | Campos permitidos na raiz | Campos permitidos em `detalhes` |
|---|---|---|---|---|
| `cpu` | `"%"` | `0.0 <= valor <= 100.0` | `valor`, `unidade`, `timestamp`, `detalhes` (opc.) | `por_nucleo` (opc.) |
| `memoria` | `"MB"` | `valor >= 0` (e `<= total`) | `valor`, `unidade`, `timestamp`, `detalhes` (opc.) | `total`, `livre`, `percentual` (opcs.) |

Regras de consistência entre campos:

| Métrica | Regra | Tolerância |
|---|---|---|
| `cpu` | `média(por_nucleo) ≈ valor` | 1,0 ponto percentual |
| `memoria` | `valor <= total` | nenhuma |
| `memoria` | `livre <= total` | nenhuma |
| `memoria` | `valor + livre <= total` | 1% de `total` + 1 MB |
| `memoria` | `percentual ≈ valor / total × 100` | 1,0 ponto percentual |

Campos com valor `null` em `detalhes` (ou o próprio `detalhes: null`) são tratados como não informados.

### 4.4. Regras de codificação e estrutura do JSON

| Regra | Limite / comportamento |
|---|---|
| Codificação | UTF-8 sem BOM. Sequências inválidas são rejeitadas. |
| Raiz | Deve ser um objeto JSON. `null`, números, strings e listas são rejeitados. |
| Tamanho máximo | **64 KiB** (`TAMANHO_MAXIMO_PAYLOAD_BYTES = 65536`), verificado antes da desserialização. |
| Chaves duplicadas | Rejeitadas em qualquer nível (ex.: `{"valor": 99, "valor": 10}`), evitando que o último valor substitua silenciosamente o primeiro. |
| Constantes não padronizadas | `NaN`, `Infinity` e `-Infinity` são rejeitados (não fazem parte da RFC 8259). |
| Números | Devem ser finitos e representáveis em ponto flutuante. Literais como `1e400` ou inteiros com centenas de dígitos são rejeitados. Booleanos não são aceitos como números. |
| Aninhamento | Estruturas aninhadas em profundidade excessiva são rejeitadas como JSON inválido. |
| Campos extras | Campos fora da lista permitida (na raiz ou em `detalhes`) são rejeitados. |

### 4.5. Formato do `timestamp`

O `timestamp` deve seguir exatamente o padrão:

```text
AAAA-MM-DDTHH:MM:SS[.ffffff](Z|±HH:MM)
```

Expressão regular canônica (somente dígitos ASCII):

```regex
^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$
```

- Separador `T` e sufixo `Z` em maiúsculas;
- Segundos obrigatórios; fração de segundo opcional com 1 a 6 dígitos;
- Fuso obrigatório, entre `-14:00` e `+14:00`, com minutos entre `00` e `59`;
- A data e a hora precisam existir no calendário (ex.: `2026-02-30`, `2025-02-29` e `24:00:00` são rejeitados).

É o formato produzido pelo agente (`datetime.now().astimezone().isoformat(timespec="seconds")`). A validação é feita por expressão regular e montagem explícita do `datetime`, sem depender de `datetime.fromisoformat`, cujo comportamento varia entre versões do Python (no 3.11+ ele aceita formatos como `20261116T220000Z`, `2026-W47-1T22:00:00Z` ou `-0300`, que no 3.10 são rejeitados). Assim, o resultado é o mesmo em qualquer versão suportada.

O `timestamp` não é comparado com o relógio do monitor: diferenças de relógio entre máquinas não causam rejeição. A coluna "última atualização" do monitor usa a hora de recebimento no servidor (`recebido_em`), e o `timestamp` do agente é armazenado apenas como informação da coleta.

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

### 6.10. Tópico com curinga ou `id_maquina` inválido

**Tópico:** `monitoramento/maquina+01/cpu`
```json
{
  "valor": 25.5,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00"
}
```
- **Motivo da rejeição:** O tópico contém o curinga MQTT `+`, permitido apenas em filtros de assinatura. Essa verificação ocorre antes da validação do `id_maquina`. Um tópico como `monitoramento/-maquina01/cpu` (sem curinga) é rejeitado pela regra de formação do `id_maquina` (deve iniciar com alfanumérico).

### 6.11. Chave duplicada no JSON

**Tópico:** `monitoramento/maquina01/cpu`
```text
{"valor": 99, "valor": 10, "unidade": "%", "timestamp": "2026-11-16T22:00:00-03:00"}
```
- **Motivo da rejeição:** A chave `valor` aparece duas vezes. Sem essa regra, o parser manteria apenas o último valor e a mensagem seria aceita com um dado ambíguo.

### 6.12. Média dos núcleos incompatível com o valor geral da CPU

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": 5.0,
  "unidade": "%",
  "timestamp": "2026-11-16T22:00:00-03:00",
  "detalhes": {
    "por_nucleo": [90.0, 95.0]
  }
}
```
- **Motivo da rejeição:** A média de `por_nucleo` (92,5%) difere de `valor` (5,0%) em mais de 1,0 ponto percentual.

### 6.13. Percentual de memória incompatível com `valor` e `total`

**Tópico:** `monitoramento/maquina01/memoria`
```json
{
  "valor": 1000,
  "unidade": "MB",
  "timestamp": "2026-11-16T22:00:00-03:00",
  "detalhes": {
    "total": 8000,
    "percentual": 99.0
  }
}
```
- **Motivo da rejeição:** `1000 / 8000 × 100 = 12,5%`, mas foi informado `99.0%`.

### 6.14. Número fora da precisão de ponto flutuante

**Tópico:** `monitoramento/maquina01/cpu`
```text
{"valor": 1000...000 (400 dígitos), "unidade": "%", "timestamp": "2026-11-16T22:00:00-03:00"}
```
- **Motivo da rejeição:** O número não é representável como `float` finito. Antes desta correção, esse payload provocava `OverflowError` dentro do callback `on_message` e encerrava a thread de rede do monitor central.

### 6.15. Timestamp fora do formato canônico

**Tópico:** `monitoramento/maquina01/cpu`
```json
{
  "valor": 20.0,
  "unidade": "%",
  "timestamp": "2026-W47-1T22:00:00Z"
}
```
- **Motivo da rejeição:** Data em formato de semana ISO. Também são rejeitados `20261116T220000Z` (formato básico), `2026-11-16T22:00:00-0300` (fuso sem `:`), `2026-11-16T22:00Z` (sem segundos) e `2026-11-16t22:00:00z` (letras minúsculas).

---

## 7. Fluxo de validação

O módulo `common/validation.py` fornece funções reutilizáveis (sem dependências externas, apenas biblioteca padrão do Python 3) para duas pontas do sistema:
1. **Agente (`agent/publisher.py`):** Valida tópico e payload em `AgenteMonitoramento.publicar()` antes de chamar `client.publish(...)`, evitando poluir o broker com mensagens fora do contrato.
2. **Monitor Central (`server/subscriber.py`):** Valida toda mensagem recebida no callback `on_message` (`MonitorCentral._ao_receber`) antes de chamar `EstadoCentral.atualizar(...)`.

### 7.1. Ordem das verificações em `validar_mensagem_mqtt`

A função interrompe na primeira violação encontrada e devolve um `ResultadoValidacao(valido=False, erro=...)` com o motivo:

1. **Tópico:** string não vazia, sem curingas, com 3 níveis, prefixo `monitoramento`, `id_maquina` válido e métrica `cpu` ou `memoria`;
2. **Tipo do payload:** `bytes`, `bytearray`, `str` ou `dict`;
3. **Tamanho:** no máximo 64 KiB;
4. **Decodificação:** UTF-8 válido;
5. **Desserialização:** JSON sintaticamente válido, sem `NaN`/`Infinity`, sem chaves duplicadas e sem aninhamento excessivo;
6. **Estrutura:** objeto JSON com os campos obrigatórios e sem campos desconhecidos;
7. **Tipos e unidade:** `valor` numérico finito, `unidade` correspondente à métrica, `timestamp` válido;
8. **Faixas:** limites de `valor` e dos campos de `detalhes`;
9. **Consistência:** regras entre campos (seção 4.3).

Com `lancar_excecao=True`, a mesma violação é lançada como `ErroValidacaoProtocolo` (subclasse de `ValueError`). Para qualquer entrada recebida da rede (`bytes`), a validação não propaga outras exceções: todo erro de formato vira uma rejeição com motivo.

Os valores de entrada citados nas mensagens de erro são truncados em 60 caracteres, para que um payload grande não gere linhas de log extensas.

### 7.2. Comportamento diante de mensagens rejeitadas

Quando `validar_mensagem_mqtt` rejeita uma mensagem no monitor central:

- O estado central **não é acessado**: nenhuma máquina é criada, nenhuma métrica é substituída e `ultima_atualizacao` não muda. A última leitura válida de cada máquina é preservada;
- O contador `mensagens_descartadas` é incrementado (exibido no cabeçalho da tabela), assim como `mensagens_recebidas`;
- É registrado um log `WARNING` no formato `Mensagem descartada em '<tópico>': <motivo>`, exibido no painel de eventos recentes e gravado no arquivo de log;
- O monitor continua em execução e processa normalmente as mensagens seguintes, inclusive da mesma máquina.

`EstadoCentral.atualizar` mantém verificações próprias (métrica suportada, `id_maquina` e presença dos campos obrigatórios); se alguma delas falhar, o subscriber também descarta a mensagem com o mesmo log. Faixas, tipos e consistência não são verificados novamente no estado: essa responsabilidade é de `common/validation.py`, sempre chamado antes no fluxo de recebimento.

### 7.3. Catálogo de erros

| Categoria | Exemplo de motivo registrado |
|---|---|
| Tópico | `Tópico 'monitoramento/maquina01' deve possuir exatamente 3 níveis ...` |
| Curinga no tópico | `Tópico publicado 'monitoramento/+/cpu' não pode conter wildcards MQTT ('+' ou '#').` |
| Métrica | `Métrica 'disco' não suportada no tópico ... Valores aceitos: cpu, memoria.` |
| `id_maquina` | `Tópico ... possui id_maquina inválido: id_maquina '-maquina01' inválido. ...` |
| Tamanho | `Payload excede o tamanho máximo de 65536 bytes (recebidos ... bytes).` |
| Codificação | `Payload não é uma sequência UTF-8 válida: ...` |
| JSON malformado | `JSON malformado ou inválido: Expecting value: line 1 column 1 (char 0).` |
| Chave duplicada | `JSON malformado ou inválido: Chave duplicada no objeto JSON: 'valor'.` |
| Campo ausente | `Campos obrigatórios ausentes no payload: timestamp.` |
| Campo desconhecido | `Campos não permitidos na raiz do payload: ...` |
| Tipo incorreto | `Campo 'valor' deve ser numérico finito (int ou float), mas recebeu str ('40.0').` |
| Unidade | `Unidade inválida para a métrica 'cpu': esperado '%', recebido 'MB'.` |
| Timestamp | `Timestamp '2026-11-16T22:00:00' não está no formato ISO 8601 esperado ...` |
| Faixa | `Valor de CPU fora da faixa válida [0.0, 100.0]: recebido 112.5.` |
| Consistência | `Inconsistência na memória RAM: 'valor' utilizado (18000.0 MB) excede 'detalhes.total' (16384.0 MB).` |

### 7.4. Problemas encontrados e corrigidos na Entrega 2

| Problema | Impacto | Correção |
|---|---|---|
| Inteiro com centenas de dígitos em `valor` causava `OverflowError` | A exceção escapava do `on_message` e encerrava a thread de rede do paho; o monitor parava de receber mensagens | `_eh_numero_valido` trata o overflow e rejeita o valor |
| JSON com aninhamento profundo causava `RecursionError` | Mesmo efeito: exceção não tratada no callback | `RecursionError` tratado como JSON inválido, além do limite de 64 KiB |
| Chaves duplicadas eram aceitas | O último valor prevalecia silenciosamente (ex.: `99` seguido de `10` gravava `10`) | `object_pairs_hook` rejeita duplicatas |
| `datetime.fromisoformat` aceitava formatos diferentes conforme a versão do Python | Semana ISO, formato básico, fuso sem `:` e horários sem segundos passavam no Python 3.11+ | Validação por expressão regular com montagem explícita do `datetime` |
| Dados incompatíveis entre si eram aceitos | CPU com `valor` divergente dos núcleos e memória com `percentual` divergente de `valor/total` | Regras de consistência com tolerância de 1,0 ponto percentual |
| `REGEX_ID_MAQUINA.match` com `$` aceitava `\n` final | Dependia de uma verificação anterior para não aceitar `maquina01\n` | Uso de `fullmatch` |
| Payload em `bytearray` era rejeitado | Incompatibilidade com clientes que entregam o payload nesse tipo | `bytearray` e `memoryview` convertidos para `bytes` |
| Valores longos eram copiados integralmente nas mensagens de erro | Linhas de log extensas | Valores truncados em 60 caracteres |

### 7.5. Testes automatizados

Os testes de validação estão em `tests/test_validation.py` e cobrem entradas válidas, inválidas e casos-limite de `id_maquina`, tópicos, timestamps, payloads de CPU e memória, JSON malformado, codificação, tamanho, chaves duplicadas, compatibilidade com os payloads montados pelo agente e a garantia de que mensagens rejeitadas pelo `MonitorCentral` não alteram o estado central (usando `paho.mqtt.client.MQTTMessage` no callback real).

Execução a partir da raiz do repositório:

```bash
python3 -m pytest tests/test_validation.py -v
```

ou, sem pytest:

```bash
python3 -m unittest tests.test_validation -v
```
