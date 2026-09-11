"""ElevenLabs — a boca. Transforma o texto da IA em nota de voz.

Formato: MP3, e não o `ulaw_8000` que a configuração usa para telefonia. São
canais diferentes com exigências diferentes — o µ-law existe porque a linha
telefônica é 8 kHz, e mandar isso no WhatsApp entregaria um áudio abafado sem
motivo.

`eleven_flash_v2_5` é o modelo rápido: numa conversa, a pessoa está esperando
com o celular na mão, e meio segundo a mais por mensagem aparece.
"""

from __future__ import annotations

import asyncio

import httpx

from central_ia.config import Settings
from central_ia.observability.logging import logger

log = logger(__name__)

BASE = "https://api.elevenlabs.io/v1/text-to-speech"

#: MP3 de 44,1 kHz. O WhatsApp aceita e o áudio sai limpo no alto-falante do
#: caminhão, que é onde ele vai ser ouvido.
FORMATO_WHATSAPP = "mp3_44100_128"
TIPO_CONTEUDO = "audio/mpeg"


class ElevenLabsIndisponivel(RuntimeError):
    """Falha ao sintetizar. O chamador cai para texto — nunca fica mudo."""


#: Uma retentativa em falha de rede, com uma pausa curta.
#:
#: **Por que existe.** Quando a pessoa começa a mandar áudio, a conversa segue
#: em áudio até o fim — quem está dirigindo não vai parar para ler. Um tropeço
#: de rede derrubava a mensagem para texto **no meio do atendimento**, e o
#: motorista via a IA mudar de canal sem explicação (observado em 24/08/2026).
#:
#: Uma só, e curta: falha persistente cai para texto do mesmo jeito, e insistir
#: mais custaria segundos de silêncio para quem está esperando resposta.
TENTATIVAS = 2
PAUSA_ENTRE_TENTATIVAS_S = 0.6


async def sintetizar(cfg: Settings, texto: str) -> bytes:
    if cfg.elevenlabs_api_key is None:
        raise ElevenLabsIndisponivel("ELEVENLABS_API_KEY não preenchida no .env.")
    if not cfg.elevenlabs_voice_id:
        raise ElevenLabsIndisponivel("ELEVENLABS_VOICE_ID não escolhido. Rode `.\\dev.ps1 vozes`.")

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return await _sintetizar_uma_vez(cfg, texto)
        except ElevenLabsIndisponivel as erro:
            # Só falha de rede vale retentar. Chave errada ou voz inexistente
            # dão o mesmo erro na segunda vez, e a espera é pura latência.
            if tentativa == TENTATIVAS or not str(erro).startswith("rede:"):
                raise
            log.warning("audio_retentando", tentativa=tentativa, erro=str(erro))
            await asyncio.sleep(PAUSA_ENTRE_TENTATIVAS_S)

    raise ElevenLabsIndisponivel("inalcançável")  # pragma: no cover — o laço sempre sai antes


async def _sintetizar_uma_vez(cfg: Settings, texto: str) -> bytes:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
        try:
            resposta = await http.post(
                f"{BASE}/{cfg.elevenlabs_voice_id}",
                params={"output_format": FORMATO_WHATSAPP},
                headers={
                    "xi-api-key": cfg.elevenlabs_api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                json={
                    "text": texto,
                    "model_id": cfg.elevenlabs_model_voz,
                    # Estabilidade alta e estilo baixo: numa central, entonação
                    # dramática soa falsa e tira credibilidade do atendimento.
                    "voice_settings": {
                        "stability": 0.55,
                        "similarity_boost": 0.75,
                        "style": 0.0,
                        "use_speaker_boost": True,
                    },
                },
            )
        except httpx.HTTPError as erro:
            # `str()` de timeout do httpx vem **vazio** — sem o nome da classe,
            # o log vira `rede: ` e não diz se foi conexão, leitura ou recusa.
            raise ElevenLabsIndisponivel(
                f"rede: {type(erro).__name__}: {erro or 'sem detalhe'}"
            ) from erro

    if resposta.status_code >= 400:
        raise ElevenLabsIndisponivel(
            f"ElevenLabs respondeu {resposta.status_code}: {resposta.text[:300]}"
        )

    audio = resposta.content
    log.info("audio_gerado", bytes=len(audio), caracteres=len(texto))
    return audio
