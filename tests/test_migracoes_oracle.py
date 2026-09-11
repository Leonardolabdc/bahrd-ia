"""Testes do runner de migração do Oracle — sem banco.

O que se testa aqui é a parte que erra em silêncio: a divisão dos comandos SQL
e a substituição dos placeholders que diferem entre o container local e o ADB-S.
"""

from __future__ import annotations

import pytest

from migrations.oracle.runner import _dividir_comandos, _renderizar


def test_divide_por_ponto_e_virgula() -> None:
    sql = """
    CREATE TABLE a (id NUMBER);
    CREATE INDEX ix_a ON a (id);
    """
    comandos = _dividir_comandos(sql)
    assert len(comandos) == 2
    assert comandos[0].startswith("CREATE TABLE a")
    assert not comandos[0].endswith(";")


def test_bloco_plsql_termina_na_barra() -> None:
    """Um `;` dentro de bloco PL/SQL não pode encerrar o comando."""
    sql = """
    BEGIN
      EXECUTE IMMEDIATE 'CREATE TABLE a (id NUMBER)';
      NULL;
    END;
    /
    CREATE INDEX ix_a ON a (id);
    """
    comandos = _dividir_comandos(sql)
    assert len(comandos) == 2
    assert comandos[0].startswith("BEGIN")
    assert "EXECUTE IMMEDIATE" in comandos[0]


def test_comentarios_sao_descartados() -> None:
    sql = """
    -- comentário de linha inteira
    CREATE TABLE a (id NUMBER);
    """
    assert _dividir_comandos(sql) == ["CREATE TABLE a (id NUMBER)"]


def test_renderiza_placeholders() -> None:
    sql = "NO DROP UNTIL ${AUDITORIA_DIAS_IDLE} DAYS IDLE"
    assert _renderizar(sql, {"AUDITORIA_DIAS_IDLE": "31"}) == "NO DROP UNTIL 31 DAYS IDLE"


def test_placeholder_sem_valor_falha_alto() -> None:
    """Silenciosamente deixar `${...}` no DDL geraria um ORA obscuro no meio
    da migração — melhor falhar antes de abrir conexão."""
    with pytest.raises(ValueError, match="DESCONHECIDO"):
        _renderizar("SELECT ${DESCONHECIDO}", {"OUTRO": "1"})
