"""O breakpoint de cache no adaptador da OpenRouter.

Vale ~US$ 700/mês no volume de 41.000 (doc 06 §1), e **falha em silêncio**: sem
o campo no lugar certo, tudo continua funcionando e só a fatura muda. Por isso
o formato do corpo da requisição é preso por teste, sem chamar a API.
"""

from __future__ import annotations

import pytest

from central_ia.integrations.llm.openrouter import _sistema

BLOCOS = ["persona…", "guardrails…", "canal…", "playbook…"]
CLAUDE = "anthropic/claude-sonnet-5"
GEMINI = "google/gemini-2.5-flash"


def test_claude_recebe_os_blocos_em_lista() -> None:
    """Cache exige conteúdo em blocos. Texto puro não tem onde marcar."""
    conteudo = _sistema(BLOCOS, CLAUDE)

    assert isinstance(conteudo, list)
    assert [p["text"] for p in conteudo] == BLOCOS
    assert all(p["type"] == "text" for p in conteudo)


def test_o_breakpoint_vai_no_ultimo_bloco() -> None:
    """Ele cobre tudo que vem antes — um só basta para os quatro."""
    conteudo = _sistema(BLOCOS, CLAUDE)

    assert conteudo[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert all("cache_control" not in p for p in conteudo[:-1])


def test_ttl_de_uma_hora_e_deliberado() -> None:
    """5 min morre entre ocorrências; 1 h atravessa. Ver docstring de `_sistema`."""
    conteudo = _sistema(BLOCOS, CLAUDE)

    assert conteudo[-1]["cache_control"]["ttl"] == "1h"


def test_gemini_nao_recebe_cache_control() -> None:
    """Só a Anthropic usa breakpoint explícito.

    O Gemini faz cache implícito. Mandar o campo é, na melhor das hipóteses,
    ignorado — e trocar de modelo por variável é o motivo de a OpenRouter
    existir aqui.
    """
    conteudo = _sistema(BLOCOS, GEMINI)

    assert isinstance(conteudo, str)
    assert "cache_control" not in conteudo


def test_gemini_recebe_os_blocos_juntos_e_na_ordem() -> None:
    conteudo = _sistema(BLOCOS, GEMINI)

    assert conteudo == "persona…\n\nguardrails…\n\ncanal…\n\nplaybook…"


def test_bloco_vazio_e_descartado() -> None:
    """Bloco vazio viraria uma parte sem texto, que a API recusa."""
    conteudo = _sistema(["persona…", "", "playbook…"], CLAUDE)

    assert [p["text"] for p in conteudo] == ["persona…", "playbook…"]


def test_sem_blocos_nao_explode() -> None:
    assert _sistema([], CLAUDE) == ""
    assert _sistema(["", ""], GEMINI) == ""


def test_um_bloco_so_ainda_recebe_o_breakpoint() -> None:
    conteudo = _sistema(["persona…"], CLAUDE)

    assert conteudo[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


@pytest.mark.parametrize(
    "modelo",
    ["anthropic/claude-sonnet-5", "anthropic/claude-opus-5", "anthropic/claude-haiku-4-5"],
)
def test_qualquer_modelo_anthropic_recebe_cache(modelo: str) -> None:
    assert isinstance(_sistema(BLOCOS, modelo), list)


@pytest.mark.parametrize(
    "modelo",
    ["google/gemini-3.1-pro", "openai/gpt-5", "meta-llama/llama-4"],
)
def test_modelo_de_outro_fornecedor_nao_recebe_cache(modelo: str) -> None:
    assert isinstance(_sistema(BLOCOS, modelo), str)


def test_no_maximo_um_breakpoint() -> None:
    """A OpenRouter permite quatro; usar um evita gastar orçamento à toa."""
    conteudo = _sistema(BLOCOS, CLAUDE)

    assert sum("cache_control" in p for p in conteudo) == 1
