"""O teste que justifica o ADR-003: reiniciar o processo não perde conversa.

Roda sem Redis. O dublê abaixo implementa as quatro operações que o depósito
usa, e nada mais — um Redis falso que fizesse tudo esconderia o fato de que
este código depende de muito pouco.

O cenário central é `test_reinicio_nao_perde_a_conversa`: ele monta um depósito,
grava, **joga fora o depósito inteiro** — que é o que um reinício faz — e
carrega num depósito novo. Se a conversa não voltar, o deploy automático volta a
derrubar quem está falando.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from central_ia.config import settings
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import Sessoes
from central_ia.persistence import redis_bus, sessoes_redis

TELEFONE = "whatsapp:+5511999999999"
OUTRO = "whatsapp:+5511888888888"
DADOS = {"placa": "XYZ4E56", "interlocutor": "Marcos Pereira"}


class RedisFalso:
    """Só o que o depósito usa: `set`, `get`, `delete` e `scan_iter`."""

    def __init__(self) -> None:
        self.dados: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.gravacoes = 0
        self.quebrado = False

    def _conferir(self) -> None:
        if self.quebrado:
            raise ConnectionError("redis fora do ar")

    async def set(self, chave: str, valor: str, ex: int | None = None) -> None:
        self._conferir()
        self.dados[chave] = valor
        self.gravacoes += 1
        if ex is not None:
            self.ttl[chave] = ex

    async def get(self, chave: str) -> str | None:
        self._conferir()
        return self.dados.get(chave)

    async def delete(self, chave: str) -> None:
        self._conferir()
        self.dados.pop(chave, None)

    async def scan_iter(self, match: str, count: int = 100):
        self._conferir()
        padrao = re.compile(match.replace("*", ".*"))
        for chave in list(self.dados):
            if padrao.fullmatch(chave):
                yield chave


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> RedisFalso:
    falso = RedisFalso()
    monkeypatch.setattr(redis_bus, "cliente", lambda _cfg: falso)
    # O cache de payloads é módulo-global: sem limpar, um teste enxerga as
    # gravações do anterior e "nada mudou" vira falso negativo.
    sessoes_redis._ultimo_gravado.clear()
    return falso


def _com_conversa() -> Sessoes:
    sessoes = Sessoes()
    sessao = sessoes.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "whatsapp", DADOS)
    sessao.registrar_cliente("removi para manutencao")
    sessao.registrar_ia("entendi, obrigado", custo=0.01)
    sessoes.registrar_entrada(TELEFONE)
    return sessoes


@pytest.mark.asyncio
async def test_reinicio_nao_perde_a_conversa(redis: RedisFalso) -> None:
    """O cenário inteiro: grava, o processo morre, outro sobe e a conversa volta."""
    cfg = settings()
    antes = _com_conversa()
    original = antes.todas()[0]

    assert await sessoes_redis.sincronizar(cfg, antes) == 1

    # O reinício. Nada do objeto anterior atravessa esta linha.
    depois = Sessoes()
    assert depois.todas() == []

    assert await sessoes_redis.carregar(cfg, depois) == 1

    voltou = depois.ativa(TELEFONE)
    assert voltou is not None
    assert voltou.ocorrencia_id == original.ocorrencia_id
    assert voltou.turnos_ia == original.turnos_ia
    assert [f.texto for f in voltou.falas] == [f.texto for f in original.falas]
    assert voltou.tipo is eventos.REMOCAO_BATERIA


@pytest.mark.asyncio
async def test_a_janela_de_24h_tambem_volta(redis: RedisFalso) -> None:
    """Perder a janela não quebra nada — aparece na fatura.

    Fora dela só template entrega, e template é cobrado a cada disparo. Um
    reinício que esquece quem falou conosco faz a próxima notificação sair paga
    quando poderia ser de graça.
    """
    cfg = settings()
    antes = _com_conversa()
    assert antes.janela_aberta(TELEFONE)

    await sessoes_redis.sincronizar(cfg, antes)

    depois = Sessoes()
    assert not depois.janela_aberta(TELEFONE)

    await sessoes_redis.carregar(cfg, depois)
    assert depois.janela_aberta(TELEFONE)


@pytest.mark.asyncio
async def test_sessao_que_nao_mudou_nao_e_regravada(redis: RedisFalso) -> None:
    """Sem isto, cada requisição regravaria todas as conversas vivas."""
    cfg = settings()
    sessoes = _com_conversa()

    assert await sessoes_redis.sincronizar(cfg, sessoes) == 1
    assert await sessoes_redis.sincronizar(cfg, sessoes) == 0

    sessoes.todas()[0].registrar_cliente("mais uma coisa")
    assert await sessoes_redis.sincronizar(cfg, sessoes) == 1


@pytest.mark.asyncio
async def test_redis_fora_do_ar_nao_derruba_o_turno(redis: RedisFalso) -> None:
    """A decisão de operação do ADR-003, exercitada.

    Recusar o turno de um pânico porque um cache caiu é pior do que atendê-lo
    com risco de perder a sessão num reinício que talvez não aconteça. Mas isso
    só é defensável porque o log grita — ver o teste seguinte.
    """
    cfg = settings()
    sessoes = _com_conversa()
    redis.quebrado = True

    assert await sessoes_redis.sincronizar(cfg, sessoes) == 0  # não levanta


@pytest.mark.asyncio
async def test_falha_ao_gravar_vira_log_de_erro(
    redis: RedisFalso, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silêncio aqui seria a pior das três opções do ADR-003.

    Asserta em `capsys`, e não em `caplog`: o structlog escreve direto no
    stdout, e `caplog` só enxerga o que passa pelo `logging` da biblioteca
    padrão. Um teste com `caplog` aqui reprovaria com o log funcionando
    perfeitamente — foi o que aconteceu ao escrever este arquivo.
    """
    cfg = settings()
    sessoes = _com_conversa()
    redis.quebrado = True

    await sessoes_redis.sincronizar(cfg, sessoes)

    saida = capsys.readouterr().out
    assert "sessao_nao_gravada" in saida
    assert "ConnectionError" in saida
    # O log precisa dizer o que a falha custa, e não só que houve falha.
    assert "conversas em curso serao perdidas" in saida


@pytest.mark.asyncio
async def test_sessao_ilegivel_e_descartada_sem_derrubar_o_boot(redis: RedisFalso) -> None:
    """Uma conversa perdida é ruim; a API inteira não subir por causa dela é pior."""
    cfg = settings()
    antes = _com_conversa()
    await sessoes_redis.sincronizar(cfg, antes)

    redis.dados["sessao:LIXO"] = "{isto nao e json valido"

    depois = Sessoes()
    assert await sessoes_redis.carregar(cfg, depois) == 1
    assert "sessao:LIXO" not in redis.dados


@pytest.mark.asyncio
async def test_sessao_expirada_nao_volta(redis: RedisFalso) -> None:
    """Sessão tem validade de domínio. Persistir não é arquivar."""
    cfg = settings()
    antes = _com_conversa()
    antes.todas()[0].ultima_em = datetime.now(UTC) - timedelta(days=3)

    # `sincronizar` só grava viva; para exercitar a leitura, grava direto.
    await sessoes_redis.gravar(cfg, antes.todas()[0])

    depois = Sessoes()
    assert await sessoes_redis.carregar(cfg, depois) == 0
    assert depois.todas() == []


@pytest.mark.asyncio
async def test_carregar_duas_vezes_nao_duplica(redis: RedisFalso) -> None:
    """`readmitir` é idempotente — o painel não pode mostrar a conversa em dobro."""
    cfg = settings()
    await sessoes_redis.sincronizar(cfg, _com_conversa())

    depois = Sessoes()
    await sessoes_redis.carregar(cfg, depois)
    await sessoes_redis.carregar(cfg, depois)

    assert len(depois.todas()) == 1
    assert len(depois.vivas(TELEFONE)) == 1


@pytest.mark.asyncio
async def test_varias_conversas_do_mesmo_numero_voltam_todas(redis: RedisFalso) -> None:
    """Frota no mesmo telefone: o caso que já quebrou este depósito uma vez."""
    cfg = settings()
    antes = Sessoes()
    antes.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "whatsapp", {"placa": "AAA1A11"})
    antes.abrir(TELEFONE, eventos.MOVIMENTO_SEM_IGNICAO, "whatsapp", {"placa": "BBB2B22"})
    antes.abrir(OUTRO, eventos.REMOCAO_BATERIA, "whatsapp", {"placa": "CCC3C33"})

    assert await sessoes_redis.sincronizar(cfg, antes) == 3

    depois = Sessoes()
    assert await sessoes_redis.carregar(cfg, depois) == 3
    assert len(depois.vivas(TELEFONE)) == 2
    assert len(depois.vivas(OUTRO)) == 1
