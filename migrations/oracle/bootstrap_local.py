"""Cria o usuário CENTRAL_IA no container local — **só em desenvolvimento**.

Na OCI este passo não existe: o usuário de aplicação do Autonomous Database é
provisionado pela TI no console, e ninguém tem SYS. Por isso ele mora aqui, num
script separado do runner, e não numa migração: o runner precisa rodar
*idêntico* nos dois ambientes, este script não roda na nuvem de jeito nenhum.

Os privilégios concedidos são deliberadamente o conjunto mínimo que o ADB-S
também concede — nada de DBA, ALTER SYSTEM ou pacote restrito. É o que garante
que o schema criado em local seja criável em produção (armadilha 1, doc 02 §3.4).

    python -m migrations.oracle.bootstrap_local
"""

from __future__ import annotations

import asyncio
import os
import sys

import oracledb

from central_ia.config import settings

PRIVILEGIOS = [
    "CREATE SESSION",
    "CREATE TABLE",
    "CREATE VIEW",
    "CREATE SEQUENCE",
    "CREATE PROCEDURE",
    "CREATE TRIGGER",
    "CREATE TYPE",
    "CREATE MATERIALIZED VIEW",
]


async def bootstrap() -> int:
    cfg = settings()

    if cfg.app_env != "dev":
        print(
            "bootstrap_local só roda com APP_ENV=dev. Na OCI o usuário do "
            "Autonomous Database é criado pela TI.",
            file=sys.stderr,
        )
        return 1

    senha_sys = os.environ.get("ORACLE_SYS_PASSWORD")
    if not senha_sys:
        print("ORACLE_SYS_PASSWORD ausente — é obrigatório no container local.", file=sys.stderr)
        return 1

    usuario = cfg.oracle_user.upper()
    senha_app = cfg.oracle_password.get_secret_value()

    conexao = await oracledb.connect_async(
        user="sys",
        password=senha_sys,
        dsn=cfg.oracle_dsn,
        mode=oracledb.AUTH_MODE_SYSDBA,
    )

    try:
        with conexao.cursor() as cursor:
            await cursor.execute(
                "SELECT COUNT(*) FROM all_users WHERE username = :u", u=usuario
            )
            (existe,) = await cursor.fetchone()

            if existe:
                print(f"Usuário {usuario} já existe — só sincronizando a senha.")
                await cursor.execute(f'ALTER USER {usuario} IDENTIFIED BY "{senha_app}"')
            else:
                print(f"Criando usuário {usuario}.")
                await cursor.execute(f'CREATE USER {usuario} IDENTIFIED BY "{senha_app}"')

            for privilegio in PRIVILEGIOS:
                await cursor.execute(f"GRANT {privilegio} TO {usuario}")

            # Necessário para BLOCKCHAIN TABLE (auditoria imutável).
            await cursor.execute(f"GRANT EXECUTE ON DBMS_BLOCKCHAIN_TABLE TO {usuario}")

            # Sem tablespace dedicado — o ADB-S também não deixa escolher.
            await cursor.execute(f"ALTER USER {usuario} QUOTA UNLIMITED ON USERS")

        await conexao.commit()
        print(f"Pronto. {usuario} criado com o conjunto mínimo de privilégios.")
        return 0

    finally:
        await conexao.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(bootstrap()))
