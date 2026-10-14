"""O alerta de taxa de erro — P2, e-mail, com cooldown.

Etapa 2: "alerta sem ação é ruído". Prioridade, público e canal estão fixados
no cabeçalho de `observability/alertas.py` — aqui os testes conferem que o
limiar, a amostra mínima e o cooldown funcionam de verdade, sem tocar Redis
nem enviar e-mail real.
"""

from __future__ import annotations

import pytest

from central_ia.config import Settings
from central_ia.observability import alertas
from central_ia.persistence import redis_bus


class _PipelineFalso:
    def __init__(self, dono: _RedisFalso) -> None:
        self._dono = dono
        self._comandos: list[tuple[str, tuple]] = []

    def incr(self, chave: str) -> _PipelineFalso:
        self._comandos.append(("incr", (chave,)))
        return self

    def expire(self, chave: str, segundos: int) -> _PipelineFalso:
        self._comandos.append(("expire", (chave, segundos)))
        return self

    async def execute(self) -> None:
        for nome, args in self._comandos:
            if nome == "incr":
                (chave,) = args
                self._dono.dados[chave] = str(int(self._dono.dados.get(chave, 0)) + 1)
            # `expire` não precisa de efeito nenhum para o teste — a lógica
            # de negócio não lê TTL, só confia que o Redis vai honrá-lo.


class _RedisFalso:
    def __init__(self) -> None:
        self.dados: dict[str, str] = {}

    def pipeline(self) -> _PipelineFalso:
        return _PipelineFalso(self)

    async def get(self, chave: str) -> str | None:
        return self.dados.get(chave)

    async def set(self, chave: str, valor: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and chave in self.dados:
            return False
        self.dados[chave] = valor
        return True


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _RedisFalso:
    falso = _RedisFalso()
    monkeypatch.setattr(redis_bus, "cliente", lambda _cfg: falso)
    return falso


def _cfg_com_email() -> Settings:
    return Settings(
        alerta_resend_api_key="re_chave-de-teste",
        alerta_email_remetente="central@exemplo.com",
        alerta_email_destinatario="operacao@exemplo.com",
    )


def _grava_em(lista: list) -> object:
    """Substitui `_enviar_email` nos testes — `async` porque o código real
    faz `await _enviar_email(...)`."""

    async def _fn(cfg: Settings, *, assunto: str, corpo: str) -> None:
        lista.append((assunto, corpo))

    return _fn


async def _registrar(cfg: Settings, *, sucessos: int, falhas: int) -> None:
    for _ in range(sucessos):
        await alertas.registrar_turno(cfg, sucesso=True)
    for _ in range(falhas):
        await alertas.registrar_turno(cfg, sucesso=False)


@pytest.mark.asyncio
async def test_amostra_pequena_nao_alerta_mesmo_com_100_por_cento_de_erro(redis) -> None:
    cfg = _cfg_com_email()
    # 2 turnos, os 2 falharam — 100% de erro, mas abaixo da amostra mínima.
    await _registrar(cfg, sucessos=0, falhas=2)

    disparou = await alertas.verificar_e_alertar(cfg)

    assert disparou is False


@pytest.mark.asyncio
async def test_taxa_abaixo_do_limiar_nao_alerta(redis) -> None:
    cfg = _cfg_com_email()
    # 20 turnos, 1 falhou — 5% exatos não deve passar o limiar (é "< 0.05").
    await _registrar(cfg, sucessos=19, falhas=0)
    await alertas.registrar_turno(cfg, sucesso=False)

    disparou = await alertas.verificar_e_alertar(cfg)

    assert disparou is False


@pytest.mark.asyncio
async def test_taxa_acima_do_limiar_com_amostra_suficiente_dispara(
    redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    enviados: list = []
    monkeypatch.setattr(alertas, "_enviar_email", _grava_em(enviados))
    cfg = _cfg_com_email()
    # 10 turnos, 2 falharam — 20%, bem acima dos 5%. `registrar_turno` já
    # dispara `verificar_e_alertar` sozinho a cada falha — é no 2º falho,
    # o que fecha a amostra mínima, que o disparo acontece.
    await _registrar(cfg, sucessos=8, falhas=2)

    assert len(enviados) == 1
    assunto, corpo = enviados[0]
    assert "[P2]" in assunto
    assert "2 de 10" in corpo


@pytest.mark.asyncio
async def test_cooldown_impede_segundo_email_na_mesma_janela(
    redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    enviados: list = []
    monkeypatch.setattr(alertas, "_enviar_email", _grava_em(enviados))
    cfg = _cfg_com_email()
    # A 2ª falha já dispara (ver teste acima). Uma 3ª falha, na mesma janela,
    # não deveria mandar um segundo e-mail — é o cooldown funcionando.
    await _registrar(cfg, sucessos=8, falhas=2)
    await alertas.registrar_turno(cfg, sucesso=False)

    assert len(enviados) == 1, "o cooldown deveria impedir o segundo disparo"


@pytest.mark.asyncio
async def test_sem_canal_configurado_nao_tenta_enviar(
    redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    chamou_http = []

    class _ClienteFalso:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

        async def post(self, *_a, **_k):
            chamou_http.append(1)
            raise AssertionError("nao deveria chamar a API sem canal configurado")

    monkeypatch.setattr(alertas.httpx, "AsyncClient", lambda **_k: _ClienteFalso())
    cfg = Settings()  # sem nenhuma das três variáveis de alerta preenchidas

    # A lógica de limiar roda igual — só o canal é checado antes do cooldown,
    # e o envio em si fica mudo.
    await _registrar(cfg, sucessos=8, falhas=2)

    assert chamou_http == [], "sem resend configurado, a API nunca deveria ser chamada"


@pytest.mark.asyncio
async def test_sem_canal_configurado_nao_consome_o_cooldown(
    redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defeito real, achado testando o alerta pela primeira vez (14/10/2026).

    Sem canal configurado, uma tentativa que cruza o limiar não pode
    reservar o cooldown de 1h — senão, quando alguém configurar o e-mail
    depois, o primeiro alerta de verdade fica mudo até o cooldown vencer
    sozinho, sem ninguém entender por quê.
    """
    enviados: list = []
    monkeypatch.setattr(alertas, "_enviar_email", _grava_em(enviados))

    # Primeira rodada, sem e-mail configurado — cruza o limiar, mas não deve
    # reservar o cooldown.
    sem_email = Settings()
    await _registrar(sem_email, sucessos=8, falhas=2)
    assert enviados == []

    # Segunda rodada, agora com e-mail configurado — se o cooldown tivesse
    # sido reservado antes, este alerta ficaria mudo.
    com_email = _cfg_com_email()
    await _registrar(com_email, sucessos=8, falhas=2)
    assert len(enviados) == 1, (
        "o alerta de verdade nao pode ficar mudo por causa da tentativa anterior"
    )


@pytest.mark.asyncio
async def test_chamada_real_ao_resend_tem_o_formato_certo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confere o contrato com a API do Resend sem bater na rede — mesmo
    espírito de `test_cache_openrouter.py`: o formato é preso por teste
    porque falha em silêncio (manda errado, a resposta não avisa o porquê)."""

    chamadas = []

    class _RespostaFalsa:
        def raise_for_status(self) -> None:
            pass

    class _ClienteFalso:
        def __init__(self, **kwargs) -> None:
            self._kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

        async def post(self, url: str, *, headers: dict, json: dict):
            chamadas.append((url, headers, json))
            return _RespostaFalsa()

    monkeypatch.setattr(alertas.httpx, "AsyncClient", _ClienteFalso)
    cfg = _cfg_com_email()

    await alertas._enviar_email(cfg, assunto="[P2] teste", corpo="corpo do alerta")

    assert len(chamadas) == 1
    url, headers, corpo_json = chamadas[0]
    assert url == "https://api.resend.com/emails"
    assert headers["Authorization"] == "Bearer re_chave-de-teste"
    assert corpo_json["from"] == "central@exemplo.com"
    assert corpo_json["to"] == ["operacao@exemplo.com"]
    assert corpo_json["subject"] == "[P2] teste"
    assert corpo_json["text"] == "corpo do alerta"
