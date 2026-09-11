"""A tranca do painel, e o que ela não pode trancar junto.

O túnel do Cloudflare é aberto para o Twilio alcançar `/whatsapp/entrada` — e
expõe a API inteira junto. Em 17/08/2026 verificamos: `GET /painel/fila` pelo
endereço público devolvia a fila com nome de motorista, placa e endereço, sem
credencial nenhuma.

Metade destes testes guarda a tranca. A outra metade guarda as três rotas que
**precisam continuar abertas** — proteger qualquer uma delas quebra o sistema
de um jeito que não aparece em teste de unidade comum.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from central_ia.api import seguranca
from central_ia.api.rotas import midia, painel, saude, whatsapp
from central_ia.config import Settings


def _cfg(token: str | None) -> Settings:
    return Settings(oracle_password="x", mysql_password="x", painel_token=token)


def _rotas_com_dependencia(router) -> bool:
    nomes = [d.dependency.__name__ for d in router.dependencies if d.dependency]
    return "exigir_token_do_painel" in nomes


def test_painel_exige_token() -> None:
    """A trava está no router, não em cada rota — rota nova nasce protegida."""
    assert _rotas_com_dependencia(painel.router)


@pytest.mark.parametrize(
    ("modulo", "porque"),
    [
        (saude, "é o HEALTHCHECK da imagem: trancar deixa o contêiner insalubre"),
        (midia, "o Twilio busca o áudio com as credenciais dele; token faria a voz nunca chegar"),
        (whatsapp, "já autentica pela assinatura HMAC do Twilio sobre URL e parâmetros"),
    ],
)
def test_rotas_que_precisam_continuar_abertas(modulo, porque: str) -> None:
    assert not _rotas_com_dependencia(modulo.router), porque


@pytest.mark.asyncio
async def test_sem_token_configurado_deixa_passar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Modo aberto é o que mantém uma máquina de desenvolvimento funcionando.

    A contrapartida é o aviso no boot — sem ele, o modo cômodo vira o modo
    esquecido.
    """
    monkeypatch.setattr(seguranca, "settings", lambda: _cfg(None))
    assert await seguranca.exigir_token_do_painel(None) is None


@pytest.mark.asyncio
async def test_token_errado_e_ausente_sao_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seguranca, "settings", lambda: _cfg("segredo-certo"))

    for enviado in (None, "", "segredo-errado", "segredo-cert"):
        with pytest.raises(HTTPException) as erro:
            await seguranca.exigir_token_do_painel(enviado)
        assert erro.value.status_code == 401


@pytest.mark.asyncio
async def test_token_certo_passa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seguranca, "settings", lambda: _cfg("segredo-certo"))
    assert await seguranca.exigir_token_do_painel("segredo-certo") is None


def test_comparacao_e_resistente_a_tempo() -> None:
    """`==` em string vaza o tamanho do prefixo correto pelo tempo de resposta.

    O ataque é remoto e lento, e a defesa custa uma linha — não há motivo para
    não pagá-la.
    """
    fonte = inspect.getsource(seguranca.exigir_token_do_painel)
    assert "compare_digest" in fonte
