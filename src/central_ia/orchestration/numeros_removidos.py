"""Números que pediram para não receber mais os eventos de um veículo.

⛔ **Não é conveniência, é obrigação de plataforma.** Uma linha de celular
cancelada é reciclada pela operadora, e o cadastro da Bahrd continua apontando
para ela. Quem atende passa a receber alarme de um caminhão que nunca foi seu.
Continuar mandando depois de a pessoa pedir para parar derruba a nota de
qualidade do número na Meta e, no limite, tira a conta do ar — e aí **nenhum**
cliente recebe nada.

**Por veículo, e não pelo número inteiro.** Decisão de 10/09/2026. Bloquear o
número todo é mais simples e resolve a linha reciclada de uma vez, mas se quem
pediu for o motorista certo, confuso, ele deixa de receber o alerta de roubo do
próprio caminhão. Por placa o estrago de um engano fica contido num veículo.

⚠️ **O preço dessa escolha:** se a linha antiga estava ligada a cinco caminhões,
a pessoa errada precisa pedir cinco vezes. Está registrado porque é o tipo de
coisa que aparece em produção e ninguém lembra que foi escolhido.

**Mora no Redis, e não em memória.** Uma lista de bloqueio que esquece no deploy
é pior que não ter: a pessoa pede para sair, agradecemos, e no dia seguinte o
alarme volta. O Redis do projeto sobe com `--appendonly yes` e volume próprio,
então sobrevive a restart e a recriação de contêiner; na OCI vira OCI Cache, com
o mesmo cliente.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from central_ia.config import Settings
from central_ia.integrations.mensageria.twilio import variantes_do_numero
from central_ia.observability.logging import logger
from central_ia.persistence import redis_bus

log = logger(__name__)

#: Um hash só, e não uma chave por bloqueio.
#:
#: A aba do painel precisa listar tudo, e `HGETALL` num hash é uma viagem;
#: varrer chaves soltas seria `SCAN` com padrão, que é o tipo de coisa que
#: funciona com dez registros e para de funcionar com dez mil.
_CHAVE = "central:numeros_removidos"


@dataclass(frozen=True, slots=True)
class NumeroRemovido:
    """Um pedido de remoção, como o painel precisa ler."""

    telefone: str
    placa: str
    quando: datetime
    ocorrencia_id: str
    #: A frase do cliente que originou o pedido, para o operador julgar.
    pedido: str


def _campo(telefone: str, placa: str) -> str:
    """A chave do par, em forma canônica dos dois lados.

    ⛔ **A normalização do telefone é o que faz o bloqueio funcionar.** O mesmo
    celular chega como `+5541999999999` pelo payload da Bahrd, `554199999999`
    pelo webhook da Meta e `whatsapp:+55...` pelo Twilio. Comparar texto puro
    bloquearia numa grafia e deixaria passar nas outras — e o sintoma seria a
    pessoa recebendo de novo depois de ter pedido para parar, que é exatamente
    o que este módulo existe para impedir.

    `variantes_do_numero` devolve as grafias com e sem o nono dígito; a menor
    delas serve de forma canônica porque é estável nas duas.
    """
    grafias = variantes_do_numero(telefone)
    canonico = min(grafias)
    return f"{canonico}|{placa.strip().upper()}"


async def remover(
    cfg: Settings, telefone: str, placa: str, *, ocorrencia_id: str, pedido: str
) -> None:
    """Registra que este número não quer mais eventos desta placa."""
    dados = {
        "telefone": telefone,
        "placa": placa.strip().upper(),
        "quando": datetime.now(UTC).isoformat(),
        "ocorrencia_id": ocorrencia_id,
        "pedido": pedido[:300],
    }
    await redis_bus.cliente(cfg).hset(_CHAVE, _campo(telefone, placa), json.dumps(dados))
    log.info(
        "numero_removido",
        placa=placa,
        ocorrencia=ocorrencia_id,
        # ⚠️ O telefone NÃO entra no log: é dado de cliente, e o painel já o
        # mostra para quem tem acesso a ele.
    )


async def esta_removido(cfg: Settings, telefone: str, placa: str) -> bool:
    """Este par já pediu para sair?

    ⚠️ **Devolve `False` quando o Redis está fora.** Um bloqueio que não pode
    ser lido não pode ser respeitado, e as duas saídas são ruins: mandar para
    quem pediu para não receber, ou não mandar para ninguém. A segunda é pior —
    um alarme de roubo que não sai é o que este sistema existe para evitar. A
    falha fica no log para aparecer na investigação.
    """
    try:
        return bool(await redis_bus.cliente(cfg).hexists(_CHAVE, _campo(telefone, placa)))
    except Exception as erro:  # noqa: BLE001 — indisponibilidade não cala o alarme
        log.warning("numeros_removidos_indisponivel", placa=placa, erro=str(erro))
        return False


async def listar(cfg: Settings) -> list[NumeroRemovido]:
    """Todos os pedidos, do mais recente para o mais antigo."""
    try:
        bruto = await redis_bus.cliente(cfg).hgetall(_CHAVE)
    except Exception as erro:  # noqa: BLE001 — a aba vazia é melhor que o painel caído
        log.warning("numeros_removidos_ilegivel", erro=str(erro))
        return []

    itens: list[NumeroRemovido] = []
    for cru in bruto.values():
        try:
            d = json.loads(cru)
            itens.append(
                NumeroRemovido(
                    telefone=d["telefone"],
                    placa=d["placa"],
                    quando=datetime.fromisoformat(d["quando"]),
                    ocorrencia_id=d.get("ocorrencia_id", "—"),
                    pedido=d.get("pedido", ""),
                )
            )
        except Exception:  # noqa: BLE001, PERF203 — registro torto não some com a lista
            log.warning("numero_removido_ilegivel", registro=cru[:120])
    return sorted(itens, key=lambda i: i.quando, reverse=True)


async def devolver(cfg: Settings, telefone: str, placa: str) -> bool:
    """Desfaz o bloqueio. `True` se havia um.

    ⛔ **Existe porque a IA pode errar.** Ela interpreta linguagem, e um "não é
    meu carro" dito por confusão vira bloqueio. Sem desfazer, a correção exigiria
    alguém com acesso ao Redis — e o operador que percebe o engano é justamente
    quem não tem.
    """
    apagados = await redis_bus.cliente(cfg).hdel(_CHAVE, _campo(telefone, placa))
    if apagados:
        log.info("numero_devolvido", placa=placa)
    return bool(apagados)
