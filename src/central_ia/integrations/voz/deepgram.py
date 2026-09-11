"""Deepgram — o ouvido. Transforma o áudio do motorista em texto.

Duas coisas que este módulo devolve junto com a transcrição, e que importam
mais do que o texto em si:

* **A confiança.** A IA decide a partir do que foi transcrito, não do que foi
  dito. Uma transcrição ruim vira uma decisão ruim sem que ninguém perceba —
  o texto chega gramatical e plausível. Por isso a confiança sobe junto e o
  chamador decide o que fazer com ela.
* **A duração.** O painel mostra a bolinha de áudio com o tempo, como no
  WhatsApp, e o operador precisa ver que aquilo foi falado, não digitado.

`smart_format` liga pontuação e números por extenso — sem isso o texto chega
como um bloco corrido e o modelo interpreta pior.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from central_ia.config import Settings
from central_ia.observability.logging import logger

log = logger(__name__)

URL = "https://api.deepgram.com/v1/listen"

#: Abaixo disto, não se trata a transcrição como fato.
#:
#: Não é um número mágico: é o ponto em que o Deepgram costuma estar chutando
#: em áudio de cabine de caminhão — motor, vento, rádio. Acima, o texto serve
#: para decidir; abaixo, serve no máximo para o operador ler com ressalva.
CONFIANCA_MINIMA = 0.60


@dataclass(frozen=True)
class Transcricao:
    texto: str
    confianca: float
    duracao_s: float

    @property
    def confiavel(self) -> bool:
        return bool(self.texto.strip()) and self.confianca >= CONFIANCA_MINIMA


class DeepgramIndisponivel(RuntimeError):
    """Falha ao transcrever. Nunca vira texto vazio tratado como silêncio."""


async def transcrever(cfg: Settings, audio: bytes, tipo_conteudo: str) -> Transcricao:
    if cfg.deepgram_api_key is None:
        raise DeepgramIndisponivel("DEEPGRAM_API_KEY não preenchida no .env.")

    parametros = {
        "model": cfg.deepgram_model,
        "language": cfg.deepgram_language,
        "smart_format": "true",
        "punctuate": "true",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
        try:
            resposta = await http.post(
                URL,
                params=parametros,
                content=audio,
                headers={
                    "Authorization": f"Token {cfg.deepgram_api_key.get_secret_value()}",
                    "Content-Type": tipo_conteudo,
                },
            )
        except httpx.HTTPError as erro:
            raise DeepgramIndisponivel(f"rede: {erro}") from erro

    if resposta.status_code >= 400:
        raise DeepgramIndisponivel(
            f"Deepgram respondeu {resposta.status_code}: {resposta.text[:300]}"
        )

    dados = resposta.json()
    duracao = float(dados.get("metadata", {}).get("duration", 0.0))

    canais = dados.get("results", {}).get("channels", [])
    alternativas = canais[0].get("alternatives", []) if canais else []
    if not alternativas:
        return Transcricao("", 0.0, duracao)

    melhor = alternativas[0]
    texto = (melhor.get("transcript") or "").strip()
    confianca = float(melhor.get("confidence", 0.0))

    log.info(
        "audio_transcrito",
        caracteres=len(texto),
        confianca=round(confianca, 3),
        duracao_s=round(duracao, 1),
    )
    return Transcricao(texto, confianca, duracao)
