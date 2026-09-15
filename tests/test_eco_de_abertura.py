"""O "Entendi, Leonardo!" que a IA repetia em toda mensagem.

Observado numa conversa real por WhatsApp, em 15/09/2026: a IA abria **toda**
resposta reconhecendo o que a pessoa acabara de dizer, sempre com o nome dela.

O problema não é a palavra. Reconhecer é boa conversa — na primeira vez. Na
terceira seguida vira tique, e tique é o que denuncia a máquina. É o mesmo
motivo pelo qual este módulo já tirava o travessão: ninguém digita travessão no
WhatsApp, e ninguém abre três frases seguidas com "Entendi, Fulano!".

A regra é permitir uma vez e bloquear a repetição, que é como gente conversa.
"""

from __future__ import annotations

import pytest

from central_ia.agent.escrita import abre_com_reconhecimento, sem_eco_de_abertura

# ─────────────────────── reconhecer a abertura ───────────────────────


@pytest.mark.parametrize(
    "texto",
    [
        "Entendi, Leonardo! Vou registrar aqui.",
        "Entendi! Já anotei.",
        "Certo, Marcos. Vou verificar.",
        "Beleza! Obrigado por avisar.",
        "Perfeito, Ana! Fico no aguardo.",
        "Ok, então seguimos assim.",
        "Combinado! Qualquer coisa me chama.",
        "Tranquilo, Bruno. Sem problema.",
        "Ótimo! Isso ajuda bastante.",
        "Isso mesmo, é isso.",
    ],
)
def test_reconhece_as_formas_que_o_modelo_usa(texto: str) -> None:
    assert abre_com_reconhecimento(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "Vou registrar aqui, obrigado.",
        "A bateria foi removida às 14h.",
        "Você consegue verificar o veículo?",
        "Entendimento é importante aqui.",  # começa com "Entendi" mas não é a palavra
        "Okapi é um animal.",  # começa com "Ok" mas não é a palavra
    ],
)
def test_nao_confunde_com_frase_comum(texto: str) -> None:
    """O padrão fecha em limite de palavra. Sem isso, "Okapi" viraria "api"."""
    assert not abre_com_reconhecimento(texto)


# ─────────────────────── cortar só quando repete ───────────────────────


def test_a_primeira_vez_passa() -> None:
    """Sem fala anterior da IA, o reconhecimento está certo e fica."""
    texto = "Entendi, Leonardo! Vou registrar aqui."
    assert sem_eco_de_abertura(texto, None) == texto


def test_a_segunda_seguida_e_cortada() -> None:
    """O caso observado: duas mensagens seguidas abrindo igual."""
    assert (
        sem_eco_de_abertura(
            "Entendi, Leonardo! Vou registrar aqui.",
            "Entendi, Leonardo! Que bom que está tudo bem.",
        )
        == "Vou registrar aqui."
    )


def test_corta_mesmo_trocando_a_palavra() -> None:
    """Alternar entre "Entendi" e "Beleza" é o mesmo tique com outra roupa."""
    assert (
        sem_eco_de_abertura("Certo! Já anotei.", "Beleza, Leonardo! Obrigado.")
        == "Já anotei."
    )


def test_anterior_sem_eco_libera_esta() -> None:
    """Se a última fala não abriu assim, esta pode. Não é proibição, é ritmo."""
    texto = "Entendi, Leonardo! Vou registrar aqui."
    assert sem_eco_de_abertura(texto, "E aí, está tudo certo com o veículo?") == texto


def test_texto_sem_eco_passa_intocado() -> None:
    assert (
        sem_eco_de_abertura("Vou registrar aqui.", "Entendi, Leonardo!")
        == "Vou registrar aqui."
    )


def test_fala_que_era_so_o_eco_nao_vira_vazio() -> None:
    """Cortar tudo deixaria a IA muda, e silêncio numa central é informação errada.

    É a mesma escolha de `sem_saudacao_no_inicio`: entre entregar algo repetido
    e não entregar nada, entrega-se o repetido.
    """
    assert sem_eco_de_abertura("Entendi!", "Entendi, Leonardo! Que bom.") == "Entendi!"


def test_a_frase_que_sobra_comeca_com_maiuscula() -> None:
    """Senão o corte fica visível, e aí o remédio denuncia mais que a doença."""
    saida = sem_eco_de_abertura(
        "Entendi, Leonardo! vou registrar aqui.", "Certo! Obrigado."
    )
    assert saida == "Vou registrar aqui."
