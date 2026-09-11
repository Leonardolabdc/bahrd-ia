"""O travessão não pode chegar ao cliente.

Pedido do Leonardo em 24/08: ninguém digita "—" no WhatsApp. Ele é marca de
texto redigido, e texto redigido denuncia a máquina.

Os prompts foram limpos e ganharam a regra explícita, mas instrução de prompt é
pedido, não garantia — e mensagem entregue não tem volta. Estes testes cobrem a
garantia.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from central_ia.agent.escrita import sem_travessao

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


# ─────────────────────────── a limpeza ───────────────────────────


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        # No meio da frase ele marca uma pausa: vírgula é o equivalente.
        ("Vou registrar aqui — pode confirmar?", "Vou registrar aqui, pode confirmar?"),
        ("O guincho está a caminho — chega em 40 minutos.",
         "O guincho está a caminho, chega em 40 minutos."),
        # Depois de pontuação forte, vírgula ficaria errado.
        ("Certo, — obrigado.", "Certo, obrigado."),
        ("Tudo bem? — vamos seguir", "Tudo bem? vamos seguir"),
        # Abrindo linha é marcador de item ou de fala: some.
        ("— Primeiro item", "Primeiro item"),
        ("- — item de lista", "- item de lista"),
        # No fim não pode virar vírgula pendurada.
        ("Beleza —", "Beleza"),
        # Traço médio também.
        ("das 8 – 18h", "das 8, 18h"),
    ],
)
def test_troca(entrada: str, esperado: str) -> None:
    assert sem_travessao(entrada) == esperado


def test_hifen_comum_fica_intacto() -> None:
    """Placa e telefone usam hífen, e gente digita hífen o tempo todo."""
    texto = "A placa é ABC-1234 e o telefone 0800-080-8888, tudo certo."

    assert sem_travessao(texto) == texto


def test_texto_sem_travessao_nao_e_tocado() -> None:
    texto = "Beleza, Antônio! Já registrei aqui.\nBoa viagem."

    assert sem_travessao(texto) == texto


def test_varias_linhas() -> None:
    assert sem_travessao("linha um — dois\nlinha três — quatro") == (
        "linha um, dois\nlinha três, quatro"
    )


def test_idempotente() -> None:
    """Chamado no registro e na entrega; rodar duas vezes não pode piorar."""
    for entrada in [
        "Vou registrar aqui — pode confirmar?",
        "— item",
        "Beleza —",
        "nada aqui",
    ]:
        uma = sem_travessao(entrada)
        assert sem_travessao(uma) == uma


def test_vazio_nao_explode() -> None:
    assert sem_travessao("") == ""


# ─────────────────────── e os prompts, na origem ───────────────────────


def test_nenhum_prompt_usa_travessao() -> None:
    """O modelo imita o estilo do que lê.

    Limpar a saída resolve o sintoma; limpar os prompts é o que faz o modelo
    não escrever assim em primeiro lugar. Este teste impede a volta por
    descuido, num arquivo novo ou numa edição.
    """
    sujos = [
        f.relative_to(PROMPTS).as_posix()
        for f in sorted(PROMPTS.rglob("*.md"))
        if "—" in f.read_text(encoding="utf-8") or "–" in f.read_text(encoding="utf-8")
    ]

    assert sujos == [], f"travessão encontrado em: {', '.join(sujos)}"


def test_a_regra_esta_escrita_no_prompt() -> None:
    """Limpar sem dizer por quê deixa o próximo editor repor o travessão."""
    persona = (PROMPTS / "persona_core.md").read_text(encoding="utf-8")

    assert "Nunca use travessão" in persona
