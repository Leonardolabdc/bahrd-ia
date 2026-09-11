"""O que sai do modelo e o que chega no celular não são a mesma coisa.

O modelo escreve Markdown por hábito. O WhatsApp usa `*um asterisco*` para
negrito, não dois — então `**GHI7J89**` chega literalmente com os asteriscos na
tela do motorista, que foi o que aconteceu numa conversa real. No canal de voz
é pior: o TTS lê ou engasga no símbolo.
"""

from __future__ import annotations

import pytest

from central_ia.agent.atendimento_real import _MARKDOWN


def limpar(texto: str) -> str:
    return " ".join(_MARKDOWN.sub("", texto).split())


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("a bateria do **GHI7J89** foi desligada", "a bateria do GHI7J89 foi desligada"),
        ("o *sistema* acusou agora", "o sistema acusou agora"),
        ("me confirma a ___palavra-chave___", "me confirma a palavra-chave"),
        ("olha o `PB-BATERIA` aqui", "olha o PB-BATERIA aqui"),
        ("# Título que não devia existir", "Título que não devia existir"),
    ],
)
def test_formatacao_nao_chega_no_cliente(bruto: str, esperado: str) -> None:
    assert limpar(bruto) == esperado


def test_texto_limpo_passa_intacto() -> None:
    frase = "Oi, Antônio! Tudo bem, e você? O sistema acusou que a bateria foi desligada."
    assert limpar(frase) == frase


def test_asterisco_no_meio_de_palavra_tambem_sai() -> None:
    """Melhor perder um asterisco legítimo do que entregar marcação na tela.

    Asterisco no meio de uma frase falada não existe; formatação vazada
    existe e já apareceu.
    """
    assert "*" not in limpar("2*3 é seis")
