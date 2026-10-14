"""O expurgo de conversas antigas — mecanismo real, não só intenção.

Etapa 2: "política de retenção e exclusão, com mecanismo real (cron, SQL ou
cenário), e não só a intenção". A retenção de 90 dias já estava desenhada
desde 11/08/2026 (ver cabeçalho de `workers/retencao.py`) — o que faltava era
isto aqui: o código que de fato apaga.

Sem tocar banco nem rede: um dublê de conexão grava os comandos que recebeu,
e os testes conferem o comportamento por cima disso.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from central_ia.config import Settings
from central_ia.workers import retencao


@dataclass
class _Linha:
    conversa_id: str


@dataclass
class _ConexaoFalsa:
    ids_existentes: list[str]
    comandos: list[tuple[str, dict | None]] = field(default_factory=list)

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.comandos.append((str(statement), params))
        if "SELECT conversa_id" in str(statement):
            return [_Linha(i) for i in self.ids_existentes]
        return None


class _EngineFalso:
    def __init__(self, conexao: _ConexaoFalsa) -> None:
        self._conexao = conexao

    def begin(self):  # noqa: ANN201 — devolve a si mesmo como context manager
        return self

    async def __aenter__(self):
        return self._conexao

    async def __aexit__(self, *_exc) -> bool:
        return False


def _instalar_dublê(monkeypatch: pytest.MonkeyPatch, ids_existentes: list[str]) -> _ConexaoFalsa:
    conexao = _ConexaoFalsa(ids_existentes=ids_existentes)
    monkeypatch.setattr(retencao.mysql, "engine", lambda _cfg: _EngineFalso(conexao))
    return conexao


@pytest.mark.asyncio
async def test_sem_conversa_elegivel_nao_apaga_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    conexao = _instalar_dublê(monkeypatch, ids_existentes=[])

    quantidade = await retencao.expurgar_conversas_antigas(Settings())

    assert quantidade == 0
    # Só a consulta rodou — nenhum DELETE foi tentado contra lista vazia.
    assert len(conexao.comandos) == 1


@pytest.mark.asyncio
async def test_apaga_mensagem_antes_de_conversa(monkeypatch: pytest.MonkeyPatch) -> None:
    conexao = _instalar_dublê(monkeypatch, ids_existentes=["c1", "c2"])

    quantidade = await retencao.expurgar_conversas_antigas(Settings())

    assert quantidade == 2
    textos = [cmd for cmd, _ in conexao.comandos]
    # A ordem dos índices já prova a sequência: mensagem referencia
    # conversa_id, e apagar na ordem inversa deixaria registro órfão se algo
    # falhasse entre os dois DELETE.
    assert "SELECT conversa_id" in textos[0]
    assert "DELETE FROM mensagem" in textos[1]
    assert "DELETE FROM conversa" in textos[2]


@pytest.mark.asyncio
async def test_os_dois_deletes_recebem_os_mesmos_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    conexao = _instalar_dublê(monkeypatch, ids_existentes=["c1", "c2", "c3"])

    await retencao.expurgar_conversas_antigas(Settings())

    _, params_mensagem = conexao.comandos[1]
    _, params_conversa = conexao.comandos[2]
    assert params_mensagem == {"ids": ["c1", "c2", "c3"]}
    assert params_conversa == {"ids": ["c1", "c2", "c3"]}


def test_consulta_exige_encerrada_em_preenchido() -> None:
    """Conversa em curso nao pode ser apagada — a trava mora na própria SQL.

    Não executa nada: só confere que o texto da consulta não perdeu a
    cláusula de segurança numa edição futura.
    """
    import inspect

    fonte = inspect.getsource(retencao.expurgar_conversas_antigas)
    assert "encerrada_em IS NOT NULL" in fonte


@pytest.mark.asyncio
async def test_expurgo_diario_le_cfg_do_contexto_do_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = []

    async def _fake_expurgo(cfg: Settings) -> int:
        chamadas.append(cfg)
        return 0

    monkeypatch.setattr(retencao, "expurgar_conversas_antigas", _fake_expurgo)

    cfg = Settings()
    await retencao.expurgo_diario({"cfg": cfg})

    assert chamadas == [cfg]
