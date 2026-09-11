"""Ambiente do Alembic.

A URL do banco vem de ``Settings`` (ou seja, do ambiente), nunca do
``alembic.ini`` — mesma regra do resto da aplicação: configuração só por
variável de ambiente.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from central_ia.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

cfg = settings()
config.set_main_option("sqlalchemy.url", cfg.mysql_url_sincrono)

# As tabelas operacionais são criadas por DDL explícito nas revisões, não por
# autogenerate a partir de modelos — o particionamento e os tipos ENUM do
# MySQL não sobrevivem bem ao autogenerate.
target_metadata = None


def migracoes_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def migracoes_online() -> None:
    conectavel = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with conectavel.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    migracoes_offline()
else:
    migracoes_online()
