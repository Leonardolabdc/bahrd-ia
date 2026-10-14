"""Alerta de taxa de erro — P2, canal e-mail, público: operação.

Etapa 2 pede "alerta sem ação é ruído": prioridade, público e canal definidos
de propósito, não um número solto.

| | |
|---|---|
| **O quê** | Taxa de erro de turnos de IA acima de 5%, numa janela de 15 min |
| **Prioridade** | P2 — degradação, não sistema parado; exige ação rápida |
| **Público** | A operação (quem mantém o sistema) |
| **Canal** | E-mail — de propósito, não WhatsApp. O número de WhatsApp já serve para
  testar a conversa com a IA; misturar aviso operacional no mesmo número
  confundiria o quê é teste de cliente e o quê é alerta de sistema |

A contagem usa o Redis que já está rodando — dois contadores com TTL de 15
min (`total` e `falhas`), incrementados a cada turno. Sem rolling window
sofisticada: a cada turno novo depois dos 15 min, os contadores já expiraram
e recomeçam do zero sozinhos — é o próprio TTL do Redis fazendo o trabalho,
sem um job de limpeza à parte.

**Cooldown de 1h.** Sem isso, cada turno que mantém a taxa acima de 5% manda
um e-mail novo — e um alerta que pinga a cada minuto vira o mesmo problema
que o curso descreve: tanto alerta que vira ruído, e ruído se ignora.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from central_ia.config import Settings
from central_ia.observability.logging import logger
from central_ia.persistence import redis_bus

log = logger(__name__)

#: Mesmo limiar do material da disciplina sobre LLMOps: "taxa de erro > 5% em
#: janela de 15 min exige ação imediata; provavelmente um P1 ou P2".
LIMIAR_TAXA_DE_ERRO = 0.05
JANELA_S = 15 * 60

#: Amostra mínima antes de calcular taxa. Sem isso, a primeira falha de um dia
#: parado já seria "100% de erro" — estatística mentirosa com dois turnos.
AMOSTRA_MINIMA = 10

_COOLDOWN_S = 60 * 60

_CHAVE_TOTAL = "alerta:turnos:total"
_CHAVE_FALHAS = "alerta:turnos:falhas"
_CHAVE_COOLDOWN = "alerta:taxa_de_erro:cooldown"


async def registrar_turno(cfg: Settings, *, sucesso: bool) -> None:
    """Chamado a cada turno de IA — sucesso ou falha. Barato: dois `INCR`."""
    r = redis_bus.cliente(cfg)
    pipe = r.pipeline()
    pipe.incr(_CHAVE_TOTAL)
    pipe.expire(_CHAVE_TOTAL, JANELA_S)
    if not sucesso:
        pipe.incr(_CHAVE_FALHAS)
        pipe.expire(_CHAVE_FALHAS, JANELA_S)
    await pipe.execute()

    if not sucesso:
        await verificar_e_alertar(cfg)


async def verificar_e_alertar(cfg: Settings) -> bool:
    """Confere a taxa de erro da janela atual e dispara o e-mail se passar
    do limiar. Devolve se disparou — só para os testes conferirem.
    """
    r = redis_bus.cliente(cfg)
    total = int(await r.get(_CHAVE_TOTAL) or 0)
    falhas = int(await r.get(_CHAVE_FALHAS) or 0)

    if total < AMOSTRA_MINIMA:
        return False

    taxa = falhas / total
    # "<=", não "<": o material da disciplina fala em "acima de 5%"
    # (`>`), então 5% exatos ainda é normal, não alerta.
    if taxa <= LIMIAR_TAXA_DE_ERRO:
        return False

    # `SET ... NX` com TTL: só o primeiro turno a cruzar o limiar, depois do
    # cooldown anterior expirar, consegue escrever a chave e disparar. Os
    # turnos seguintes, na mesma janela, encontram a chave já lá e desistem —
    # é o cooldown impedindo e-mail a cada turno.
    conseguiu = await r.set(_CHAVE_COOLDOWN, "1", nx=True, ex=_COOLDOWN_S)
    if not conseguiu:
        return False

    log.warning("alerta_taxa_de_erro", total=total, falhas=falhas, taxa=round(taxa, 3))
    # smtplib é síncrono — numa thread à parte para não travar o loop
    # assíncrono enquanto o handshake SMTP acontece.
    await asyncio.to_thread(
        _enviar_email,
        cfg,
        assunto="[P2] Bahrd — taxa de erro de turnos da IA acima do limiar",
        corpo=(
            f"{falhas} de {total} turnos falharam nos últimos 15 minutos "
            f"({taxa:.0%}, limiar é {LIMIAR_TAXA_DE_ERRO:.0%}).\n\n"
            "Prioridade P2 — degradação significativa, não é sistema parado, "
            "mas pede investigação logo. Comece pelo Langfuse, filtrando por "
            "erro, para achar o padrão."
        ),
    )
    return True


def _alerta_configurado(cfg: Settings) -> bool:
    return bool(
        cfg.alerta_email_remetente
        and cfg.alerta_email_senha_app
        and cfg.alerta_email_destinatario
    )


def _enviar_email(cfg: Settings, *, assunto: str, corpo: str) -> None:
    """Sem as três variáveis preenchidas, não tenta enviar — fica só no log.

    Sem try/except escondendo erro de envio: se o SMTP falhar, o erro sobe e
    aparece no log do worker. Um alerta que falha em silêncio é pior que não
    ter alerta — ninguém percebe a ausência até o incidente de verdade.
    """
    if not _alerta_configurado(cfg):
        log.info("alerta_sem_canal_configurado", motivo="variaveis de email ausentes")
        return

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = cfg.alerta_email_remetente
    mensagem["To"] = cfg.alerta_email_destinatario
    mensagem.set_content(corpo)

    with smtplib.SMTP(cfg.alerta_smtp_host, cfg.alerta_smtp_port) as smtp:
        smtp.starttls()
        smtp.login(
            cfg.alerta_email_remetente,
            cfg.alerta_email_senha_app.get_secret_value(),  # type: ignore[union-attr]
        )
        smtp.send_message(mensagem)
