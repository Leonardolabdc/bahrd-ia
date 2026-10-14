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

⚠️ **Por que API HTTPS (Resend), e não SMTP direto do Gmail.** Primeira
versão usava `smtplib` contra `smtp.gmail.com`. Testado de verdade em
14/10/2026: a conexão e o `STARTTLS` funcionavam, mas o login era derrubado
com `Connection unexpectedly closed` — padrão de IP de camada gratuita de
nuvem (Oracle, neste caso) sendo bloqueado preventivamente por reputação,
não de senha errada. Trocar para uma API HTTPS de terceiro resolve porque
quem entrega o e-mail é a infraestrutura deles, não o IP da VM — mesmo
padrão já usado para Twilio, OpenRouter, Deepgram e ElevenLabs neste
projeto: nenhuma outra integração fala protocolo bruto.
"""

from __future__ import annotations

import httpx

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

    # Checa o canal **antes** de reservar o cooldown. Defeito real, achado
    # testando o alerta pela primeira vez (14/10/2026): sem isto, uma
    # tentativa sem e-mail configurado consumia o cooldown de 1h do mesmo
    # jeito — e quando o canal fosse configurado depois, o próximo alerta de
    # verdade ficava mudo até o cooldown vencer sozinho.
    if not _alerta_configurado(cfg):
        log.info("alerta_sem_canal_configurado", motivo="variaveis de email ausentes")
        return False

    # `SET ... NX` com TTL: só o primeiro turno a cruzar o limiar, depois do
    # cooldown anterior expirar, consegue escrever a chave e disparar. Os
    # turnos seguintes, na mesma janela, encontram a chave já lá e desistem —
    # é o cooldown impedindo e-mail a cada turno.
    conseguiu = await r.set(_CHAVE_COOLDOWN, "1", nx=True, ex=_COOLDOWN_S)
    if not conseguiu:
        return False

    log.warning("alerta_taxa_de_erro", total=total, falhas=falhas, taxa=round(taxa, 3))
    await _enviar_email(
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
        cfg.alerta_resend_api_key
        and cfg.alerta_email_remetente
        and cfg.alerta_email_destinatario
    )


async def _enviar_email(cfg: Settings, *, assunto: str, corpo: str) -> None:
    """Sem as três variáveis preenchidas, não tenta enviar — fica só no log.

    Sem try/except escondendo erro de envio: se a API do Resend falhar, o
    erro sobe e aparece no log do worker. Um alerta que falha em silêncio é
    pior que não ter alerta — ninguém percebe a ausência até o incidente de
    verdade.
    """
    if not _alerta_configurado(cfg):
        log.info("alerta_sem_canal_configurado", motivo="variaveis de e-mail ausentes")
        return

    async with httpx.AsyncClient(timeout=15.0) as cliente:
        resposta = await cliente.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {cfg.alerta_resend_api_key.get_secret_value()}",  # type: ignore[union-attr]
            },
            json={
                "from": cfg.alerta_email_remetente,
                "to": [cfg.alerta_email_destinatario],
                "subject": assunto,
                "text": corpo,
            },
        )
        resposta.raise_for_status()
