"""Adaptador do OpenRouter — ponte, não destino.

O que se perde em relação ao adaptador da Anthropic, e por que importa:

* **`effort` vira o `reasoning` do OpenRouter**, que não é a mesma coisa. Aqui
  os tokens de raciocínio saem do mesmo `max_tokens` da resposta e vão para um
  campo separado do conteúdo — se o raciocínio consumir o orçamento, `content`
  volta **vazio** com `finish_reason: "length"`. Por isso o parâmetro é sempre
  enviado explicitamente: deixar no padrão liga o raciocínio e engole a
  resposta em silêncio.
* **Sem saída estruturada validada.** Triagem, briefing e QA continuam
  dependendo do adaptador da Anthropic.

O que **não** se perde, ao contrário do que este arquivo dizia até 19/08/2026:

* **Cache de prompt.** A OpenRouter aceita `cache_control` para modelos Claude,
  igual à API direta, e ainda fixa o roteamento no mesmo provedor para aumentar
  o acerto. Ver `_sistema`.

Serve para o que precisa servir agora: ver a conversa acontecendo, com o
prompt real, e julgar o tom — e comparar modelos por variável de ambiente, sem
tocar em código.

Formato da API: compatível com OpenAI (`/chat/completions`), não com a
Messages API. Por isso os blocos de sistema viram **uma** mensagem — com
conteúdo em lista quando há cache, em texto quando não há.
"""

from __future__ import annotations

import httpx

from central_ia.config import Settings
from central_ia.ports.llm import (
    Esforco,
    Mensagem,
    OrcamentoDeTokensEstourado,
    RespostaLLM,
    RespostaVaziaDoModelo,
    Uso,
)

#: `xhigh` e `max` não existem no OpenRouter; caem no teto que existe.
_ESFORCO_PARA_REASONING = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


#: Só a Anthropic usa `cache_control` explícito. O Gemini faz cache implícito
#: sozinho, e mandar o campo para ele é, na melhor das hipóteses, ignorado.
#: Checar o prefixo mantém a troca de modelo por variável — que é o motivo de
#: a OpenRouter estar aqui.
_PREFIXO_COM_CACHE_EXPLICITO = "anthropic/"


def _sistema(blocos: list[str], modelo: str) -> str | list[dict]:
    """Os blocos de sistema, com o breakpoint de cache quando o modelo aceita.

    **Por que isto importa:** os quatro blocos (persona, guardrails, canal,
    playbook) somam ~5.500 tokens e são reprocessados a cada turno. Com o
    breakpoint, são relidos a **10% do preço** a partir do segundo turno — o
    que corta quase metade do custo do modelo e reduz a latência.

    O breakpoint vai no **último** bloco, e cobre tudo que vem antes. Só
    funciona porque os quatro são estáveis: nada de data, nome de cliente ou
    identificador de ocorrência aqui — isso vive nas mensagens (doc 02 §6.1).
    Um caractere que mude a cada chamada invalida o cache inteiro.

    `ttl` de 1 h em vez dos 5 min padrão: a escrita custa 2×, mas no volume da
    Bahrd há conversa o tempo todo, e o cache atravessa **ocorrências
    diferentes** em vez de morrer entre uma e outra.
    """
    uteis = [b for b in blocos if b]
    if not uteis:
        return ""

    if not modelo.startswith(_PREFIXO_COM_CACHE_EXPLICITO):
        return "\n\n".join(uteis)

    partes: list[dict] = [{"type": "text", "text": b} for b in uteis]
    partes[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return partes


class ClienteOpenRouter:
    def __init__(self, cfg: Settings, modelo: str | None = None) -> None:
        if cfg.openrouter_api_key is None:
            raise RuntimeError(
                "OPENROUTER_API_KEY ausente. Preencha o .env e salve o arquivo."
            )

        # `modelo` vem da sessão quando a Central trocou o cérebro; o `.env` é o
        # padrão de quem não pediu nada. Bônus de graça na troca: `_sistema()`
        # já condiciona o `cache_control` ao prefixo `anthropic/`, então o cache
        # de prompt liga e desliga sozinho e correto.
        self.modelo = modelo or cfg.openrouter_modelo
        self._http = httpx.AsyncClient(
            base_url=cfg.openrouter_base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {cfg.openrouter_api_key.get_secret_value()}",
                "Content-Type": "application/json",
                # Identificação opcional do projeto no painel do OpenRouter.
                "X-Title": "POC IA Central Bahrd",
            },
        )

    async def gerar(
        self,
        *,
        blocos_sistema: list[str],
        mensagens: list[Mensagem],
        max_tokens: int = 1024,
        esforco: Esforco | None = None,
    ) -> RespostaLLM:
        corpo: dict = {
            "model": self.modelo,
            "max_tokens": max_tokens,
            # Sempre explícito. Sem isto o modelo raciocina por padrão, o
            # raciocínio come o `max_tokens` e o conteúdo volta vazio.
            "reasoning": (
                {"effort": _ESFORCO_PARA_REASONING[esforco]}
                if esforco
                else {"enabled": False}
            ),
            "messages": [
                {"role": "system", "content": _sistema(blocos_sistema, self.modelo)},
                *({"role": m.papel, "content": m.conteudo} for m in mensagens),
            ],
            # Pede o custo real da chamada de volta — é o que torna o gasto
            # visível durante a POC, em vez de descobrir no fim do crédito.
            "usage": {"include": True},
        }

        resposta = await self._http.post("/chat/completions", json=corpo)

        if resposta.status_code >= 400:
            raise RuntimeError(
                f"OpenRouter respondeu {resposta.status_code}: {resposta.text[:400]}"
            )

        dados = resposta.json()
        if erro := dados.get("error"):
            # O OpenRouter devolve 200 com `error` no corpo em alguns casos.
            raise RuntimeError(f"OpenRouter recusou a chamada: {erro}")

        escolha = dados["choices"][0]
        uso = dados.get("usage") or {}
        texto = (escolha.get("message") or {}).get("content") or ""

        # Resposta vazia por estouro de orçamento é erro de configuração, não
        # recusa do modelo. Sem esta checagem o sintoma chega distorcido lá na
        # frente — "JSON inválido" quando o problema era `max_tokens`.
        if not texto.strip() and escolha.get("finish_reason") == "length":
            raise OrcamentoDeTokensEstourado(
                f"O modelo consumiu os {max_tokens} tokens sem produzir conteúdo "
                f"(esforço={esforco}). Aumente max_tokens ou reduza o esforço."
            )

        # ⚠️ **Vazio dizendo que terminou é o mesmo buraco, outra porta.**
        # Visto em 02/09/2026 num pânico: `finish_reason: stop` e conteúdo
        # nenhum. Sem levantar aqui, o vazio seguia adiante e só virava erro
        # depois do parse, fora do alcance da segunda tentativa — o turno
        # morria sem nunca ter sido repetido.
        if not texto.strip():
            raise RespostaVaziaDoModelo(
                f"O modelo terminou sem escrever nada (parada="
                f"{escolha.get('finish_reason')}, esforço={esforco})."
            )

        return RespostaLLM(
            texto=texto,
            modelo=dados.get("model", self.modelo),
            motivo_parada=escolha.get("finish_reason"),
            uso=Uso(
                tokens_entrada=uso.get("prompt_tokens", 0),
                tokens_saida=uso.get("completion_tokens", 0),
                # Sem isto o cache funcionaria em silêncio e ninguém saberia
                # dizer se está pegando. `0` no segundo turno de uma conversa
                # é o sinal de que o breakpoint quebrou.
                tokens_cache_leitura=(uso.get("prompt_tokens_details") or {}).get(
                    "cached_tokens", 0
                )
                or 0,
                custo_usd=uso.get("cost"),
            ),
        )

    async def fechar(self) -> None:
        await self._http.aclose()
