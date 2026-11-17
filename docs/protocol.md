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
