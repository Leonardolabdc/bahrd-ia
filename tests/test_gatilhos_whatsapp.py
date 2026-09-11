"""A palavra que abre a ocorrência, vinda de texto ou de áudio transcrito."""

from __future__ import annotations

import pytest

from central_ia.api.rotas.whatsapp import _gatilho


@pytest.mark.parametrize(
    ("mensagem", "esperado"),
    [
        ("bateria", "REMOCAO_BATERIA"),
        ("Bateria", "REMOCAO_BATERIA"),
        ("BATERIA", "REMOCAO_BATERIA"),
        ("  bateria  ", "REMOCAO_BATERIA"),
        ("bateria por favor", "REMOCAO_BATERIA"),
        ("ignicao", "MOVIMENTO_SEM_IGNICAO"),
        ("ignição", "MOVIMENTO_SEM_IGNICAO"),
        ("panico", "PANICO"),
        ("pânico", "PANICO"),
    ],
)
def test_gatilhos_reconhecidos(mensagem: str, esperado: str) -> None:
    assert _gatilho(mensagem) == esperado


def test_o_teste_cobre_os_tres_eventos_da_demonstracao() -> None:
    """Três, por decisão de demonstração — nem mais, nem menos.

    Uma palavra a mais na lista é um caminho que ninguém ensaiou aparecendo na
    frente do gestor; uma a menos é um evento que o roteiro promete e não abre.
    """
    from central_ia.api.rotas.whatsapp import AJUDA, GATILHOS

    assert set(GATILHOS.values()) == {"REMOCAO_BATERIA", "MOVIMENTO_SEM_IGNICAO", "PANICO"}

    # O menu e os gatilhos não podem divergir: o que a IA oferece tem de abrir.
    for palavra in GATILHOS:
        if palavra in ("ignição", "pânico"):
            continue  # variantes com acento, o menu mostra a versão sem
        assert palavra in AJUDA, f"'{palavra}' abre evento mas não está no menu"


@pytest.mark.parametrize(
    "transcrito",
    ["Bateria.", "Pânico!", "Ignição,", '"bateria"', "Pânico…", "Ignicao?"],
)
def test_transcricao_pontuada_ainda_abre_o_evento(transcrito: str) -> None:
    """O `smart_format` do Deepgram pontua a fala.

    Sem limpar a pontuação, um áudio dizendo "bateria" chega como `"Bateria."`
    e o sistema devolveria o menu para quem acabou de pedir o evento certo.
    """
    assert _gatilho(transcrito) is not None


@pytest.mark.parametrize("mensagem", ["", "   ", "oi", "bom dia", "quero abrir um chamado"])
def test_mensagem_sem_gatilho_cai_no_menu(mensagem: str) -> None:
    assert _gatilho(mensagem) is None
