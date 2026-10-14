"""Expurgo de conversas antigas — o mecanismo, não só a intenção.

A retenção de 90 dias para `conversa`/`mensagem` já estava **desenhada** desde
11/08/2026 (ver cabeçalho de `migrations/mysql/versions/0001_camada_operacional.py`
e doc 02 §5.2: "retenção curta (90 dias) e expurgo automatizado"). O que
faltava era o job rodar — a Etapa 2 pede isso por nome: "mecanismo real (cron,
SQL ou cenário), e não só a intenção".

Por que só o MySQL, e não o Oracle também: o desenho sempre separou os dois
por papel. `conversa`/`mensagem` guardam a transcrição crua — é onde mora o
dado pessoal de verdade (o que o cliente escreveu, com nome e situação). A
`ocorrencia` no Oracle guarda o resumo e o desfecho, não a conversa — é
auditoria de longo prazo, não dado pessoal bruto, e continua existindo depois
do expurgo. Minimização de dado é isso: manter o que prova a decisão, apagar
o que não precisa mais existir.

⚠️ **Deleta, não anonimiza.** Mais simples e mais seguro: não há ambiguidade
sobre "anonimizado o suficiente" quando o registro simplesmente não existe
mais.
"""

from __future__ import annotations

from sqlalchemy import bindparam, text

from central_ia.config import Settings
from central_ia.observability.logging import logger
from central_ia.persistence import mysql

log = logger(__name__)

#: Mesmo prazo desenhado desde o início — ver o cabeçalho deste módulo.
RETENCAO_DIAS = 90


async def expurgar_conversas_antigas(cfg: Settings) -> int:
    """Apaga `mensagem` e `conversa` de ocorrências encerradas há mais de
    `RETENCAO_DIAS`. Devolve quantas conversas foram apagadas.

    Conversa **sem** `encerrada_em` (ainda em curso, ou encerrada de forma
    anômala sem registrar o fechamento) nunca é apagada — `encerrada_em IS
    NOT NULL` no `WHERE` é a trava. Expurgar uma conversa que não terminou
    apagaria evidência de um caso que pode ainda estar em aberto.
    """
    async with mysql.engine(cfg).begin() as conexao:
        alvo = await conexao.execute(
            text(
                """
                SELECT conversa_id FROM conversa
                WHERE encerrada_em IS NOT NULL
                  AND encerrada_em < NOW() - INTERVAL :dias DAY
                """
            ),
            {"dias": RETENCAO_DIAS},
        )
        ids = [linha.conversa_id for linha in alvo]

        if not ids:
            log.info("expurgo_sem_conversa_elegivel", retencao_dias=RETENCAO_DIAS)
            return 0

        # `expanding=True` deixa o SQLAlchemy montar o IN (...) com N
        # placeholders — sem isso, uma lista vira um placeholder só e o
        # MySQL rejeita a sintaxe.
        #
        # mensagem antes de conversa — mensagem referencia conversa_id, e a
        # ordem inversa deixaria registro órfão se algo falhar no meio.
        apaga_mensagem = text("DELETE FROM mensagem WHERE conversa_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        apaga_conversa = text("DELETE FROM conversa WHERE conversa_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        await conexao.execute(apaga_mensagem, {"ids": ids})
        await conexao.execute(apaga_conversa, {"ids": ids})

    log.info(
        "expurgo_conversas_antigas",
        quantidade=len(ids),
        retencao_dias=RETENCAO_DIAS,
    )
    return len(ids)


async def expurgo_diario(ctx: dict) -> None:
    """Entrada do `cron_jobs` do arq — ver `workers/main.py`."""
    cfg: Settings = ctx["cfg"]
    await expurgar_conversas_antigas(cfg)
