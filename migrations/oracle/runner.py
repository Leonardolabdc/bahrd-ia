"""Runner de migração do Oracle — versionado e idempotente.

Não existe Alembic para Oracle aqui: os scripts são SQL numerado e este runner
registra o que já aplicou numa tabela de controle. Rodar duas vezes não faz
nada na segunda.

    python -m migrations.oracle.runner            # aplica o que falta
    python -m migrations.oracle.runner --status   # só mostra o estado

O mesmo runner roda contra o container local e contra o ADB-S. É ele que o
Sprint 3 usa no *deploy de fumaça* que mata a armadilha 1 (doc 02 §3.4).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from pathlib import Path

import oracledb

from central_ia.config import Settings, settings

DIRETORIO = Path(__file__).parent
PADRAO_ARQUIVO = re.compile(r"^(\d{3})_(.+)\.sql$")

TABELA_CONTROLE = """
CREATE TABLE migracao_aplicada (
  versao      VARCHAR2(10)  PRIMARY KEY,
  nome        VARCHAR2(200) NOT NULL,
  sha256      VARCHAR2(64)  NOT NULL,
  aplicada_em TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
)
"""


def _substituicoes(cfg: Settings) -> dict[str, str]:
    """Valores que diferem entre ambientes, injetados nos placeholders ${...}."""
    return {
        # 0 em dev permite recriar o schema; 31 em hml/prd-poc protege a trilha.
        "AUDITORIA_DIAS_IDLE": str(cfg.oracle_auditoria_dias_idle),
        # Wallet presente = ADB-S = vector pool disponível = HNSW.
        "TIPO_INDICE_VETORIAL": (
            "INMEMORY NEIGHBOR GRAPH" if cfg.oracle_wallet_dir else "NEIGHBOR PARTITIONS"
        ),
    }


def _renderizar(sql: str, valores: dict[str, str]) -> str:
    for chave, valor in valores.items():
        sql = sql.replace("${" + chave + "}", valor)
    if pendentes := set(re.findall(r"\$\{(\w+)\}", sql)):
        raise ValueError(f"Placeholder sem valor definido: {sorted(pendentes)}")
    return sql


# Um comando que comece assim é PL/SQL: tem `;` internos e só termina numa
# linha contendo apenas `/`. Dividir por `;` aqui produziria fragmentos que o
# Oracle aceita parcialmente — corrupção silenciosa da migração.
INICIO_BLOCO_PLSQL = re.compile(
    r"^\s*(DECLARE|BEGIN|CREATE\s+(OR\s+REPLACE\s+)?"
    r"(PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE)\b)",
    re.IGNORECASE,
)


def _dividir_comandos(sql: str) -> list[str]:
    """Separa comandos, seguindo a convenção do SQL*Plus.

    Um `;` no fim da linha encerra um comando SQL comum. Dentro de um bloco
    PL/SQL, só uma linha contendo apenas `/` encerra. Comentários de linha
    inteira são descartados.
    """
    comandos: list[str] = []
    buffer: list[str] = []
    em_bloco = False

    for linha_bruta in sql.splitlines():
        linha = linha_bruta.rstrip()
        sem_espaco = linha.strip()

        if not sem_espaco or sem_espaco.startswith("--"):
            continue

        if sem_espaco == "/":
            if buffer:
                comandos.append("\n".join(buffer).strip())
                buffer = []
            em_bloco = False
            continue

        if not buffer and INICIO_BLOCO_PLSQL.match(linha):
            em_bloco = True

        if not em_bloco and sem_espaco.endswith(";"):
            buffer.append(linha[: linha.rfind(";")])
            comandos.append("\n".join(buffer).strip())
            buffer = []
            continue

        buffer.append(linha)

    if restante := "\n".join(buffer).strip():
        comandos.append(restante)

    return [c for c in comandos if c]


def _migracoes() -> list[tuple[str, str, Path]]:
    encontradas = []
    for arquivo in sorted(DIRETORIO.glob("*.sql")):
        if achado := PADRAO_ARQUIVO.match(arquivo.name):
            encontradas.append((achado.group(1), achado.group(2), arquivo))
    return encontradas


async def _garantir_tabela_controle(conexao: oracledb.AsyncConnection) -> None:
    with conexao.cursor() as cursor:
        try:
            await cursor.execute(TABELA_CONTROLE)
            await conexao.commit()
        except oracledb.DatabaseError as erro:
            (info,) = erro.args
            if info.code != 955:  # ORA-00955: objeto já existe
                raise


async def _aplicadas(conexao: oracledb.AsyncConnection) -> dict[str, str]:
    with conexao.cursor() as cursor:
        await cursor.execute("SELECT versao, sha256 FROM migracao_aplicada")
        return {versao: sha for versao, sha in await cursor.fetchall()}


async def executar(cfg: Settings, apenas_status: bool = False) -> int:
    conexao = await oracledb.connect_async(
        user=cfg.oracle_user,
        password=cfg.oracle_password.get_secret_value(),
        dsn=cfg.oracle_dsn,
        **(
            {"config_dir": cfg.oracle_wallet_dir, "wallet_location": cfg.oracle_wallet_dir}
            if cfg.oracle_wallet_dir
            else {}
        ),
    )

    try:
        await _garantir_tabela_controle(conexao)
        ja_aplicadas = await _aplicadas(conexao)
        valores = _substituicoes(cfg)
        pendentes = 0

        for versao, nome, arquivo in _migracoes():
            sql = _renderizar(arquivo.read_text(encoding="utf-8"), valores)
            sha = hashlib.sha256(sql.encode("utf-8")).hexdigest()

            if versao in ja_aplicadas:
                if ja_aplicadas[versao] != sha:
                    print(
                        f"  ! {versao}_{nome}: conteúdo mudou depois de aplicado. "
                        "Migração é append-only — crie um script novo.",
                        file=sys.stderr,
                    )
                    return 1
                print(f"  = {versao}_{nome} (já aplicada)")
                continue

            pendentes += 1
            if apenas_status:
                print(f"  + {versao}_{nome} (pendente)")
                continue

            print(f"  → aplicando {versao}_{nome}")
            with conexao.cursor() as cursor:
                for comando in _dividir_comandos(sql):
                    await cursor.execute(comando)
                await cursor.execute(
                    "INSERT INTO migracao_aplicada (versao, nome, sha256) "
                    "VALUES (:versao, :nome, :sha)",
                    versao=versao,
                    nome=nome,
                    sha=sha,
                )
            await conexao.commit()

        if apenas_status:
            print(f"\n{pendentes} migração(ões) pendente(s).")
        else:
            print(f"\nOracle em dia ({pendentes} aplicada(s) nesta execução).")
        return 0

    finally:
        await conexao.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrações do Oracle")
    parser.add_argument("--status", action="store_true", help="não aplica, só relata")
    args = parser.parse_args()

    cfg = settings()
    print(f"Oracle: {cfg.oracle_user}@{cfg.oracle_dsn} (ambiente {cfg.app_env})")
    return asyncio.run(executar(cfg, apenas_status=args.status))


if __name__ == "__main__":
    raise SystemExit(main())
