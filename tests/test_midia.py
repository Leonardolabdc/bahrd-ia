"""O depósito de áudio que o Twilio vem buscar.

A rota é pública por necessidade — o Twilio busca a mídia sem credencial
nossa. O que protege é o identificador imprevisível e o tempo de vida curto,
e é isso que estes testes guardam.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from central_ia.api.rotas import midia


def _limpar() -> None:
    midia._ARQUIVOS.clear()


def test_cada_audio_ganha_um_nome_imprevisivel() -> None:
    """Nome sequencial deixaria qualquer um baixar o áudio dos outros."""
    _limpar()
    primeiro = midia.guardar(b"um", "audio/mpeg")
    segundo = midia.guardar(b"dois", "audio/mpeg")

    assert primeiro != segundo
    assert primeiro.endswith(".mp3")
    # 32 caracteres hexadecimais de UUID, não um contador.
    assert len(primeiro.removesuffix(".mp3")) == 32


def test_audio_expirado_deixa_de_existir() -> None:
    """Áudio que fica para sempre é dado exposto para sempre."""
    _limpar()
    nome = midia.guardar(b"conteudo", "audio/mpeg")
    assert nome in midia._ARQUIVOS

    antigo = midia._ARQUIVOS[nome]
    midia._ARQUIVOS[nome] = midia.Audio(
        antigo.conteudo, antigo.tipo, datetime.now(UTC) - midia.VALIDADE - timedelta(seconds=1)
    )
    midia._expirar()

    assert nome not in midia._ARQUIVOS


def test_deposito_nao_cresce_sem_limite() -> None:
    """Demonstração longa não pode virar vazamento de memória."""
    _limpar()
    for i in range(midia.MAXIMO + 25):
        midia.guardar(f"audio {i}".encode(), "audio/mpeg")

    assert len(midia._ARQUIVOS) <= midia.MAXIMO


def test_url_publica_nao_duplica_barra() -> None:
    """URL torta é áudio que o Twilio não consegue buscar — e ninguém ouve."""
    assert (
        midia.url_publica("https://algo.trycloudflare.com", "abc.mp3")
        == "https://algo.trycloudflare.com/midia/abc.mp3"
    )
    assert (
        midia.url_publica("https://algo.trycloudflare.com/", "abc.mp3")
        == "https://algo.trycloudflare.com/midia/abc.mp3"
    )
