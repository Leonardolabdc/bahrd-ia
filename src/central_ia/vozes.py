"""Lista as vozes da conta da ElevenLabs, com o `voice_id` de cada uma.

Existe porque o ID é fácil de copiar errado: a página mostra vários
identificadores, e o `voice_id` são ~20 caracteres alfanuméricos misturando
maiúsculas e minúsculas (por exemplo `JBFqnCBsd6RMkjVDRZzb`). Qualquer coisa
muito mais longa, ou só com dígitos e letras de `a` a `f`, é outro campo.

Não consome créditos: apenas lê o catálogo.

    python -m central_ia.vozes

Exige a permissão **Voices → Read** na chave. Sem ela, a saída explica o que
conceder.
"""

from __future__ import annotations

import asyncio
import re
import sys

import httpx

from central_ia.config import settings

#: Formato do identificador segundo a documentação da ElevenLabs.
FORMATO_ID = re.compile(r"^[A-Za-z0-9]{15,30}$")


async def executar() -> int:
    cfg = settings()

    if cfg.elevenlabs_api_key is None:
        print("ELEVENLABS_API_KEY não preenchida no .env.", file=sys.stderr)
        return 1

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as http:
        resposta = await http.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": cfg.elevenlabs_api_key.get_secret_value()},
        )

    if resposta.status_code == 401:
        print(
            "A chave não tem permissão para ler vozes.\n\n"
            "Na ElevenLabs, crie uma chave marcando 'Voices → Read' (além de\n"
            "'Text to Speech') e cole em ELEVENLABS_API_KEY.",
            file=sys.stderr,
        )
        return 1

    if resposta.status_code >= 400:
        print(f"HTTP {resposta.status_code}: {resposta.text[:200]}", file=sys.stderr)
        return 1

    vozes = resposta.json().get("voices", []) or []
    if not vozes:
        print(
            "Nenhuma voz na conta. Adicione uma em elevenlabs.io/app/voice-library\n"
            "— voz que não está na sua conta não pode ser usada pela API."
        )
        return 1

    atual = cfg.elevenlabs_voice_id
    livres = [v for v in vozes if v.get("category") == "premade"]
    presas = [v for v in vozes if v.get("category") != "premade"]

    def linha(voz: dict) -> str:
        vid = voz.get("voice_id", "")
        nome = (voz.get("name") or "")[:26]
        rotulos = voz.get("labels") or {}
        # `language` nem sempre vem; sotaque e descrição ajudam a escolher.
        descricao = " · ".join(
            str(v) for k, v in rotulos.items() if k in ("language", "accent", "description") and v
        )
        marca = "  ←  configurado" if vid == atual else ""
        return f"  {vid:<24} {nome:<26} {descricao}{marca}"

    # A separação existe porque a lista inteira engana: aparecer aqui não quer
    # dizer que dá para usar. No plano gratuito, só `premade` sintetiza via
    # API — o resto devolve 402 na hora de gerar o áudio.
    print(f"{len(vozes)} voz(es) na conta.\n")
    print(f"FUNCIONAM NO PLANO GRATUITO ({len(livres)}):")
    print(f"  {'VOICE_ID':<24} {'NOME':<26} IDIOMA / RÓTULOS")
    print(f"  {'-' * 24} {'-' * 26} {'-' * 30}")
    for voz in livres:
        print(linha(voz))

    if presas:
        print(f"\nEXIGEM PLANO PAGO ({len(presas)} · categoria 'professional' ou biblioteca):")
        for voz in presas:
            print(linha(voz))

    print()
    if not atual:
        print("ELEVENLABS_VOICE_ID ainda não está preenchido no .env.")
    elif not any(v.get("voice_id") == atual for v in vozes):
        problema = (
            "não parece um voice_id (o formato é ~20 caracteres alfanuméricos)"
            if not FORMATO_ID.match(atual)
            else "não está entre as vozes da sua conta"
        )
        print(f"O ELEVENLABS_VOICE_ID atual {problema}.")
        print(f"  atual: {atual}")
        print("\nCopie um dos VOICE_ID acima para o .env.")
        return 1
    else:
        print("O ELEVENLABS_VOICE_ID configurado está correto.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(executar()))
