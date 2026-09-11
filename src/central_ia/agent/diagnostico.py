"""Teste de fumaça do modelo — deliberadamente minúsculo.

Confirma três coisas, gastando frações de centavo:

1. A chave e o modelo configurados funcionam.
2. O provedor responde no formato que o adaptador espera.
3. O custo real da chamada, quando o provedor o informa.

`max_tokens` é 24 de propósito. Isto não avalia qualidade — avalia se o cano
está ligado. A avaliação de conversa vem depois, com o prompt completo.

    python -m central_ia.agent.diagnostico
"""

from __future__ import annotations

import asyncio
import sys

from central_ia.config import settings
from central_ia.integrations.llm import construir_cliente_llm
from central_ia.ports.llm import Mensagem

MAX_TOKENS = 24


async def executar() -> int:
    cfg = settings()

    print(f"provedor : {cfg.llm_provider}")
    cliente = construir_cliente_llm(cfg)
    print(f"modelo   : {cliente.modelo}")
    print(f"limite   : {MAX_TOKENS} tokens de saída\n")

    try:
        resposta = await cliente.gerar(
            blocos_sistema=[
                "Você responde em português do Brasil, em uma frase curta."
            ],
            mensagens=[
                Mensagem(
                    papel="user",
                    conteudo="Responda apenas: a conexão está funcionando.",
                )
            ],
            max_tokens=MAX_TOKENS,
        )
    except Exception as erro:  # noqa: BLE001 — aqui o objetivo é diagnosticar
        print(f"FALHOU: {erro}", file=sys.stderr)
        return 1
    finally:
        await cliente.fechar()

    print(f"resposta : {resposta.texto.strip()}")
    print(f"atendeu  : {resposta.modelo}")
    print(
        f"tokens   : {resposta.uso.tokens_entrada} entrada · "
        f"{resposta.uso.tokens_saida} saída"
    )
    if resposta.uso.custo_usd is not None:
        print(f"custo    : US$ {resposta.uso.custo_usd:.6f}")

    print("\nOK — o modelo está acessível.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(executar()))
