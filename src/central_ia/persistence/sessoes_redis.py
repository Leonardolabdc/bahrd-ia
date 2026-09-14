"""Depósito das conversas no Redis — o que faz a sessão sobreviver a um reinício.

Implementa o [ADR-003](../../../docs/adr/0003-sessoes-fora-da-memoria.md).

**Por que não é `await` a cada mutação.** A ideia inicial era gravar dentro de
cada método que muda a sessão. Não funciona, e o motivo só aparece lendo os
chamadores: a maior parte das mutações acontece **no objeto `Sessao`** —
`sessao.registrar_ia(...)`, `sessao.encerrar(...)` — e não através de `Sessoes`.
Interceptar os métodos do depósito pegaria uma fração das mudanças, e a fração
que escapasse seria invisível: a sessão voltaria do reinício com o valor antigo,
sem erro em lugar nenhum.

Além disso `Sessoes` é síncrona e o cliente Redis é assíncrono. Tornar os doze
métodos `async` espalharia `await` por todo o código de conversa, que é
exatamente o risco que o ADR-003 decidiu não correr.

**O que este módulo faz em vez disso:** grava todas as sessões vivas cujo
conteúdo mudou, na fronteira da requisição e no desligamento. Como a comparação
é do payload inteiro, não existe mutação que escape — não importa quem mudou o
quê, nem onde.

A janela de perda é uma requisição. Num desligamento gracioso — que é o caso do
deploy — ela é zero, porque o gancho de saída grava antes de morrer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from central_ia.config import Settings
from central_ia.observability.logging import logger
from central_ia.orchestration.sessao_whatsapp import VALIDADE, Sessao, Sessoes
from central_ia.persistence import redis_bus

log = logger(__name__)

#: Prefixo das sessões. `SCAN` sobre ele é o que reconstrói o depósito no boot.
PREFIXO = "sessao:"

#: Quando cada número falou conosco. Guardado à parte porque sobrevive à sessão:
#: a janela de 24 h da Meta vale por telefone, não por conversa — e ela é
#: dinheiro. Perder isso num reinício faz o próximo disparo sair como template
#: cobrado, quando poderia ser mensagem livre.
PREFIXO_JANELA = "janela:"

#: Margem sobre a validade. A sessão morre por regra de domínio (`viva`), não
#: por expiração de chave — o TTL existe só para o Redis não acumular lixo de
#: conversa que ninguém vai ler.
_FOLGA = timedelta(hours=1)

#: Payload da última gravação de cada sessão, por ocorrência. É o que evita
#: reescrever sessão que não mudou — sem isto, cada requisição regravaria todas
#: as conversas vivas.
_ultimo_gravado: dict[str, str] = {}


def _chave(ocorrencia_id: str) -> str:
    return f"{PREFIXO}{ocorrencia_id}"


def _ttl_s(sessao: Sessao) -> int:
    restante = (sessao.ultima_em + VALIDADE + _FOLGA) - datetime.now(UTC)
    return max(int(restante.total_seconds()), 60)


async def gravar(cfg: Settings, sessao: Sessao) -> bool:
    """Grava uma sessão. Devolve `False` se ela não mudou desde a última vez."""
    payload = json.dumps(sessao.para_dicionario(), ensure_ascii=False, sort_keys=True)
    if _ultimo_gravado.get(sessao.ocorrencia_id) == payload:
        return False

    await redis_bus.cliente(cfg).set(_chave(sessao.ocorrencia_id), payload, ex=_ttl_s(sessao))
    _ultimo_gravado[sessao.ocorrencia_id] = payload
    return True


async def sincronizar(cfg: Settings, sessoes: Sessoes) -> int:
    """Grava toda sessão viva que mudou. Devolve quantas foram gravadas.

    ⚠️ **Nunca levanta.** Redis fora do ar aqui significa perder sessão num
    reinício que talvez não aconteça; levantar significa derrubar o turno de uma
    conversa que está acontecendo agora. Entre as duas, o ADR-003 escolheu a
    primeira — mas só porque o log grita. Um erro silencioso neste ponto seria a
    pior das três opções.
    """
    gravadas = 0
    try:
        for sessao in sessoes.todas():
            if sessao.viva and await gravar(cfg, sessao):
                gravadas += 1

        cliente = redis_bus.cliente(cfg)
        for telefone, momento in sessoes.ultimas_entradas().items():
            await cliente.set(
                f"{PREFIXO_JANELA}{telefone}",
                momento.isoformat(),
                ex=int(VALIDADE.total_seconds()),
            )
    except Exception as erro:  # noqa: BLE001 — ver docstring
        log.error(
            "sessao_nao_gravada",
            erro=str(erro),
            tipo=type(erro).__name__,
            consequencia="conversas em curso serao perdidas se o processo reiniciar",
        )
        return gravadas

    return gravadas


async def carregar(cfg: Settings, sessoes: Sessoes) -> int:
    """Devolve ao depósito as sessões que sobreviveram ao reinício.

    Chamado uma vez, no boot. Devolve quantas voltaram.

    Sessão ilegível é **descartada com log**, e não propagada: uma conversa
    perdida é ruim, e a API inteira não subir por causa dela é pior.
    """
    cliente = redis_bus.cliente(cfg)
    voltaram = 0
    descartadas = 0

    try:
        async for chave in cliente.scan_iter(match=f"{PREFIXO}*", count=100):
            bruto = await cliente.get(chave)
            if not bruto:
                continue
            try:
                sessao = Sessao.de_dicionario(json.loads(bruto))
            except Exception as erro:  # noqa: BLE001 — ver docstring
                descartadas += 1
                log.warning("sessao_ilegivel_descartada", chave=chave, erro=str(erro))
                await cliente.delete(chave)
                continue

            if not sessao.viva:
                await cliente.delete(chave)
                continue

            sessoes.readmitir(sessao)
            _ultimo_gravado[sessao.ocorrencia_id] = json.dumps(
                sessao.para_dicionario(), ensure_ascii=False, sort_keys=True
            )
            voltaram += 1

        async for chave in cliente.scan_iter(match=f"{PREFIXO_JANELA}*", count=100):
            bruto = await cliente.get(chave)
            if bruto:
                telefone = chave[len(PREFIXO_JANELA) :]
                sessoes.readmitir_janela(telefone, datetime.fromisoformat(bruto))

    except Exception as erro:  # noqa: BLE001 — subir sem sessão é melhor que não subir
        log.error("sessoes_nao_carregadas", erro=str(erro), tipo=type(erro).__name__)
        return voltaram

    log.info("sessoes_restauradas", quantas=voltaram, descartadas=descartadas)
    return voltaram


async def esquecer(cfg: Settings, ocorrencia_id: str) -> None:
    """Apaga uma sessão do depósito. Usado quando ela encerra de vez."""
    _ultimo_gravado.pop(ocorrencia_id, None)
    try:
        await redis_bus.cliente(cfg).delete(_chave(ocorrencia_id))
    except Exception as erro:  # noqa: BLE001
        log.warning("sessao_nao_apagada", ocorrencia_id=ocorrencia_id, erro=str(erro))
