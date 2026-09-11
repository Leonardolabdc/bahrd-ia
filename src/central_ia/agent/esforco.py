"""Quanto o modelo pode raciocinar em cada tipo de chamada.

**Por que isto existe como módulo.** O esforço estava fixo em três arquivos
diferentes, e as variáveis `ANTHROPIC_EFFORT_*` do `config.py` não eram lidas
por ninguém. Quem ajustasse o `.env` não via efeito nenhum — configuração que
mente é pior que configuração que não existe.

O esforço mexe em **custo e latência ao mesmo tempo**: mais raciocínio é mais
token cobrado e mais segundos até a primeira palavra. Numa ligação isso é
audível; num WhatsApp, não.

Os padrões são exatamente o que já rodava antes desta centralização — ligar a
configuração não podia mudar comportamento de quem não pediu.
"""

from __future__ import annotations

from central_ia.config import settings
from central_ia.ports.llm import Esforco


def esforco_do_canal(canal: str) -> Esforco:
    """Conversa com o cliente, por canal.

    `LIGACAO` recebe menos porque a voz não tolera espera: o silêncio enquanto
    o modelo pensa soa como chamada caída. No texto a pessoa aceita alguns
    segundos, e o playbook rende mais com um pouco mais de raciocínio.
    """
    cfg = settings()
    return cfg.anthropic_effort_voz if canal == "LIGACAO" else cfg.anthropic_effort_texto


def esforco_da_triagem() -> Esforco:
    """Classificação do pânico — uma vez por ocorrência, antes de falar.

    É a chamada de maior consequência do sistema: decide se o caso é acidental
    ou real. Também é a mais barata de tornar mais cuidadosa, porque acontece
    **uma vez**, não a cada turno. Se algum dia valer subir o esforço em algum
    lugar, é aqui.
    """
    return settings().anthropic_effort_triagem
