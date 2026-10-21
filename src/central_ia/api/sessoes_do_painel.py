"""Sessões do login do painel, e o contador de tentativas, no Redis.

**O token nunca é guardado.** A chave no Redis é o SHA-256 do token, e o
token mesmo só existe no cookie do navegador. Quem ler o Redis — um `MONITOR`
esquecido, um dump de backup, um `KEYS *` numa depuração — vê a lista de
sessões abertas, mas não consegue usar nenhuma. SHA-256 sem sal basta aqui,
ao contrário da senha: o token tem 256 bits aleatórios, e não há dicionário
para atacar.

**O prefixo é `painel:`, e não `sessao:`.** `sessao:` já é das conversas de
WhatsApp, e `persistence/sessoes_redis.py` varre `sessao:*` no boot para
retomá-las. Uma sessão de login com esse prefixo seria lida como conversa.

**Expira sozinha.** O TTL do Redis é o prazo da sessão (`PAINEL_SESSAO_HORAS`,
contado do login). Não há faxina para rodar nem para esquecer.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime

from central_ia.config import Settings
from central_ia.persistence import redis_bus

PREFIXO_SESSAO = "painel:sessao:"
PREFIXO_TENTATIVAS = "painel:tentativas:"

#: Cinco senhas erradas em quinze minutos, para o mesmo usuário a partir do
#: mesmo IP, e o login daquele par para até a janela vencer. Quem errou a
#: senha de verdade erra duas, três vezes; cinco já é alguém tentando.
MAXIMO_DE_FALHAS = 5
JANELA_DE_FALHAS_S = 15 * 60


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def chave_da_sessao(token: str) -> str:
    return f"{PREFIXO_SESSAO}{_sha256(token)}"


def _chave_das_tentativas(ip: str, usuario: str) -> str:
    # Com hash também: o par IP + nome digitado é dado de pessoa, e o nome
    # digitado pode ser a senha de alguém que trocou os campos.
    return f"{PREFIXO_TENTATIVAS}{_sha256(f'{ip}|{usuario}')}"


def duracao_s(cfg: Settings) -> int:
    return cfg.painel_sessao_horas * 3600


async def criar(cfg: Settings, *, usuario: str, perfil: str) -> str:
    """Abre uma sessão e devolve o token, que só o cookie vai guardar."""
    token = secrets.token_urlsafe(32)
    dados = {
        "usuario": usuario,
        "perfil": perfil,
        "criada_em": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    await redis_bus.cliente(cfg).set(
        chave_da_sessao(token), json.dumps(dados), ex=duracao_s(cfg)
    )
    return token


async def ler(cfg: Settings, token: str) -> dict[str, str] | None:
    """Os dados da sessão, ou `None` se não existe ou já expirou."""
    bruto = await redis_bus.cliente(cfg).get(chave_da_sessao(token))
    if not bruto:
        return None
    try:
        dados = json.loads(bruto)
    except (TypeError, ValueError):
        return None
    if not isinstance(dados, dict) or "usuario" not in dados:
        return None
    return dados


async def apagar(cfg: Settings, token: str) -> None:
    await redis_bus.cliente(cfg).delete(chave_da_sessao(token))


async def segundos_de_bloqueio(cfg: Settings, *, ip: str, usuario: str) -> int:
    """Quanto falta para o par IP + usuário poder tentar de novo. 0 = pode já."""
    r = redis_bus.cliente(cfg)
    chave = _chave_das_tentativas(ip, usuario)
    falhas = int(await r.get(chave) or 0)
    if falhas < MAXIMO_DE_FALHAS:
        return 0
    restante = await r.ttl(chave)
    return restante if restante and restante > 0 else JANELA_DE_FALHAS_S


async def registrar_falha(cfg: Settings, *, ip: str, usuario: str) -> None:
    """Conta uma senha errada. A janela começa na primeira falha.

    `EXPIRE ... NX` no mesmo pipeline do `INCR`: o prazo é posto só quando a
    chave nasce, e nunca fica faltando. Um `INCR` sem prazo, se o processo
    morresse entre os dois comandos, bloquearia aquele login para sempre.
    """
    chave = _chave_das_tentativas(ip, usuario)
    pipe = redis_bus.cliente(cfg).pipeline()
    pipe.incr(chave)
    pipe.expire(chave, JANELA_DE_FALHAS_S, nx=True)
    await pipe.execute()


async def zerar_falhas(cfg: Settings, *, ip: str, usuario: str) -> None:
    await redis_bus.cliente(cfg).delete(_chave_das_tentativas(ip, usuario))
