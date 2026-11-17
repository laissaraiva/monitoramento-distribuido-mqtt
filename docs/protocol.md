# Especificação do protocolo de comunicação MQTT

## 1. Visão geral

Este documento define o contrato formal de comunicação entre os agentes de monitoramento (publishers) e o monitor central (subscriber) por meio do broker Eclipse Mosquitto, complementando a arquitetura definida em [docs/architecture.md](architecture.md).

O protocolo padroniza:
1. A estrutura e as regras de validação dos tópicos MQTT;
2. As regras de formação do identificador da máquina (`id_maquina`);
3. O schema JSON dos payloads de CPU e memória RAM (formato mínimo obrigatório e formato estendido opcional);
4. As faixas válidas de valores, unidades e formato de timestamp;
5. O comportamento esperado diante de mensagens válidas e inválidas.
