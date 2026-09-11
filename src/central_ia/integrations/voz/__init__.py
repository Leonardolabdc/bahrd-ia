"""Ouvido e boca: transcrição (Deepgram) e voz sintética (ElevenLabs)."""

from central_ia.integrations.voz.deepgram import (
    CONFIANCA_MINIMA,
    DeepgramIndisponivel,
    Transcricao,
    transcrever,
)
from central_ia.integrations.voz.elevenlabs import (
    TIPO_CONTEUDO,
    ElevenLabsIndisponivel,
    sintetizar,
)

__all__ = [
    "CONFIANCA_MINIMA",
    "TIPO_CONTEUDO",
    "DeepgramIndisponivel",
    "ElevenLabsIndisponivel",
    "Transcricao",
    "sintetizar",
    "transcrever",
]
