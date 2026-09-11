"""Canais de mensagem. Hoje só Twilio; a Cloud API entra pela mesma porta."""

from central_ia.integrations.mensageria.twilio import (
    ClienteTwilio,
    MensagemEnviada,
    TwilioIndisponivel,
    assinatura_valida,
    numero_autorizado,
    url_do_webhook,
    variantes_do_numero,
)

__all__ = [
    "ClienteTwilio",
    "MensagemEnviada",
    "TwilioIndisponivel",
    "assinatura_valida",
    "numero_autorizado",
    "url_do_webhook",
    "variantes_do_numero",
]
