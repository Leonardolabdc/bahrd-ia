"""Mede o ganho real do cache de prompt da OpenRouter, com duas chamadas
reais e consecutivas — não é estimativa, é o número que a API devolveu.

Só funciona com `anthropic/claude-sonnet-5` (ou outro modelo com prefixo
`anthropic/`): é o único que `integrations/llm/openrouter.py::_sistema`
marca com `cache_control`. Resultado medido em 14/10/2026, documentado na
seção "Otimização medida" do README: 94,3% de economia de custo.

Uso, de dentro do container da API:

    docker exec $(docker compose -f docker-compose.prod.yml ps -q api) \\
        python3 scripts/medir_cache_llm.py

⚠️ Consome crédito real da OpenRouter — poucos centavos de dólar por
execução, mas não é grátis. Não rodar em loop.
"""

from __future__ import annotations

import asyncio

from central_ia.agent import prompts
from central_ia.config import settings
from central_ia.domain.eventos import REMOCAO_BATERIA
from central_ia.integrations.llm.openrouter import ClienteOpenRouter
from central_ia.ports.llm import Mensagem


async def main() -> None:
    cfg = settings()
    blocos = prompts.blocos_de_sistema(REMOCAO_BATERIA, "TEXTO")
    mensagens = [Mensagem(papel="user", conteudo="Está tudo bem por aí?")]

    cliente = ClienteOpenRouter(cfg, modelo="anthropic/claude-sonnet-5")
    try:
        print("=== chamada 1 (sem cache ainda) ===")
        r1 = await cliente.gerar(blocos_sistema=blocos, mensagens=mensagens, max_tokens=200)
        print(
            f"tokens_entrada={r1.uso.tokens_entrada} "
            f"tokens_cache_leitura={r1.uso.tokens_cache_leitura} "
            f"custo_usd={r1.uso.custo_usd}"
        )

        await asyncio.sleep(3)

        print("\n=== chamada 2 (mesmo prompt — cache deveria pegar) ===")
        r2 = await cliente.gerar(blocos_sistema=blocos, mensagens=mensagens, max_tokens=200)
        print(
            f"tokens_entrada={r2.uso.tokens_entrada} "
            f"tokens_cache_leitura={r2.uso.tokens_cache_leitura} "
            f"custo_usd={r2.uso.custo_usd}"
        )

        if r1.uso.custo_usd and r2.uso.custo_usd:
            economia = (1 - r2.uso.custo_usd / r1.uso.custo_usd) * 100
            print(f"\n=== economia de custo entre chamada 1 e 2: {economia:.1f}% ===")
    finally:
        await cliente.fechar()


asyncio.run(main())
