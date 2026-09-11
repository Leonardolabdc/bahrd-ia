"""Portas — tudo que muda entre Docker local e OCI vive atrás de uma destas.

Doc 02 §3.4: `SecretProvider`, `ObjectStorage`, `EventBus`, `Telephony`, `STT`,
`TTS`. Trocar de ambiente é trocar a implementação na composição, nunca editar
o código que consome.
"""
