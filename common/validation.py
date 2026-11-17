# Módulo de validação do protocolo de comunicação MQTT

# Implementa todas as regras definidas em `docs/protocol.md` com portabilidade
# entre os ambientes dos agentes (publishers) e do monitor central (subscriber)

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Any, Dict, Optional
