"""Verificação das credenciais de terceiros — barata e sem efeito colateral.

Cada provedor é checado pelo endpoint mais barato que prova a chave: nenhum
deles transcreve, sintetiza ou gera texto. O objetivo é descobrir chave errada
agora, e não no meio de um atendimento.

    python -m central_ia.diagnostico

Chave ausente aparece como "não configurado", não como falha: a POC avança em
camadas, e não ter voz configurada no Sprint 1 é o esperado.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import httpx

from central_ia.config import Settings, settings

TEMPO_LIMITE = httpx.Timeout(20.0, connect=8.0)


@dataclass
class Resultado:
    servico: str
    estado: str  # "ok" | "falhou" | "ausente"
    detalhe: str = ""

    @property
    def simbolo(self) -> str:
        return {"ok": "OK  ", "falhou": "ERRO", "ausente": "--  "}[self.estado]


async def _deepgram(cfg: Settings) -> Resultado:
    """`GET /v1/projects` — lista projetos. Não consome minutos de transcrição."""
    if cfg.deepgram_api_key is None:
        return Resultado("Deepgram (STT)", "ausente", "DEEPGRAM_API_KEY não preenchida")

    async with httpx.AsyncClient(timeout=TEMPO_LIMITE) as http:
        try:
            r = await http.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {cfg.deepgram_api_key.get_secret_value()}"},
            )
        except httpx.HTTPError as erro:
            return Resultado("Deepgram (STT)", "falhou", f"rede: {erro}")

    if r.status_code == 401:
        return Resultado("Deepgram (STT)", "falhou", "chave recusada (401)")
    if r.status_code >= 400:
        return Resultado("Deepgram (STT)", "falhou", f"HTTP {r.status_code}: {r.text[:120]}")

    projetos = r.json().get("projects", [])
    nomes = ", ".join(p.get("name", "?") for p in projetos[:3]) or "nenhum projeto"
    return Resultado("Deepgram (STT)", "ok", f"{len(projetos)} projeto(s): {nomes}")


async def _elevenlabs(cfg: Settings) -> Resultado:
    """`GET /v1/voices` — não consome caracteres e valida o que de fato usamos.

    A checagem é pelas vozes, e não pelo perfil, por dois motivos: as chaves da
    ElevenLabs têm permissões granulares, e uma chave criada só para síntese
    legitimamente não lê o perfil; e é aqui que dá para conferir se o
    `ELEVENLABS_VOICE_ID` configurado realmente existe — errar o ID só
    apareceria na primeira ligação, no pior momento.
    """
    nome = "ElevenLabs (TTS)"
    if cfg.elevenlabs_api_key is None:
        return Resultado(nome, "ausente", "ELEVENLABS_API_KEY não preenchida")

    async with httpx.AsyncClient(timeout=TEMPO_LIMITE) as http:
        try:
            r = await http.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": cfg.elevenlabs_api_key.get_secret_value()},
            )
        except httpx.HTTPError as erro:
            return Resultado(nome, "falhou", f"rede: {erro}")

    if r.status_code == 401:
        detalhe = (
            r.json().get("detail", {})
            if r.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        mensagem = detalhe.get("message", "") if isinstance(detalhe, dict) else ""

        # "falta a permissão X" só é possível depois de autenticar: a chave é
        # boa, o escopo é que é estreito. Ler vozes é conveniência; a permissão
        # que importa é Text to Speech. Recusar aqui travaria a POC por um
        # detalhe que não impede a IA de falar.
        if "permission" in mensagem.lower():
            return Resultado(
                nome,
                "ok",
                "chave válida, sem permissão de leitura de vozes — "
                "não dá para conferir o VOICE_ID aqui",
            )

        return Resultado(nome, "falhou", mensagem or "chave recusada (401)")

    if r.status_code >= 400:
        return Resultado(nome, "falhou", f"HTTP {r.status_code}: {r.text[:160]}")

    vozes = r.json().get("voices", []) or []

    if not cfg.elevenlabs_voice_id:
        return Resultado(nome, "ok", f"{len(vozes)} voz(es) · VOICE_ID ainda não escolhido")

    escolhida = next(
        (v for v in vozes if v.get("voice_id") == cfg.elevenlabs_voice_id), None
    )
    if escolhida is None:
        return Resultado(
            nome, "falhou", f"VOICE_ID '{cfg.elevenlabs_voice_id}' não está entre as suas vozes"
        )

    # A voz aparecer em `/v1/voices` **não** quer dizer que dá para usá-la.
    # No plano gratuito, só `premade` sintetiza via API: `professional` e as
    # da biblioteca devolvem 402 na hora de gerar o áudio — e o sintoma é a IA
    # respondendo em texto sem explicação. Melhor descobrir aqui.
    categoria = escolhida.get("category", "?")
    if categoria != "premade":
        premade = sum(1 for v in vozes if v.get("category") == "premade")
        return Resultado(
            nome,
            "falhou",
            f"'{escolhida.get('name')}' é categoria '{categoria}' — plano gratuito "
            f"devolve 402 ao sintetizar. Use uma das {premade} vozes 'premade' "
            "(`.\\dev.ps1 vozes`) ou assine o plano pago.",
        )

    return Resultado(
        nome, "ok", f"{len(vozes)} voz(es) · usando '{escolhida.get('name')}' ({categoria})"
    )


async def _twilio(cfg: Settings) -> Resultado:
    """`GET /Accounts/{sid}.json` — lê a conta. Não envia mensagem, não gasta."""
    nome = "Twilio (WhatsApp)"
    if not cfg.twilio_account_sid or cfg.twilio_auth_token is None:
        return Resultado(nome, "ausente", "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN vazios")

    url = f"{cfg.twilio_base_url}/2010-04-01/Accounts/{cfg.twilio_account_sid}.json"
    async with httpx.AsyncClient(timeout=TEMPO_LIMITE) as http:
        try:
            r = await http.get(
                url, auth=(cfg.twilio_account_sid, cfg.twilio_auth_token.get_secret_value())
            )
        except httpx.HTTPError as erro:
            return Resultado(nome, "falhou", f"rede: {erro}")

    if r.status_code == 401:
        return Resultado(nome, "falhou", "SID ou auth token recusados (401)")
    if r.status_code >= 400:
        return Resultado(nome, "falhou", f"HTTP {r.status_code}: {r.text[:160]}")

    dados = r.json()
    if not cfg.numeros_de_teste:
        return Resultado(
            nome,
            "ok",
            f"{dados.get('friendly_name', '?')} · {dados.get('status', '?')} · "
            "⚠ TWILIO_NUMEROS_DE_TESTE vazio, ninguém pode abrir ocorrência",
        )

    return Resultado(
        nome,
        "ok",
        f"{dados.get('friendly_name', '?')} · {dados.get('status', '?')} · "
        f"{len(cfg.numeros_de_teste)} número(s) de teste",
    )


async def _modelo(cfg: Settings) -> Resultado:
    """Não chama o modelo — só confirma que há credencial para o provedor ativo.

    A chamada de verdade é `python -m central_ia.agent.diagnostico`, que gasta.
    """
    nome = f"Modelo ({cfg.llm_provider})"
    if cfg.llm_provider == "openrouter":
        if cfg.openrouter_api_key is None:
            return Resultado(nome, "ausente", "OPENROUTER_API_KEY não preenchida")
        return Resultado(nome, "ok", cfg.openrouter_modelo)

    if cfg.anthropic_api_key is None:
        return Resultado(nome, "ausente", "ANTHROPIC_API_KEY não preenchida")
    return Resultado(nome, "ok", cfg.anthropic_modelo_principal)


async def executar() -> int:
    cfg = settings()
    print(f"ambiente: {cfg.app_env}\n")

    resultados = [
        await _modelo(cfg),
        await _deepgram(cfg),
        await _elevenlabs(cfg),
        await _twilio(cfg),
    ]

    for r in resultados:
        print(f"{r.simbolo} {r.servico:<22} {r.detalhe}")

    falhas = [r for r in resultados if r.estado == "falhou"]
    ausentes = [r for r in resultados if r.estado == "ausente"]

    print()
    if falhas:
        print(f"{len(falhas)} credencial(is) com problema.", file=sys.stderr)
        return 1
    if ausentes:
        print(f"Tudo certo com o que está configurado. {len(ausentes)} ainda não preenchida(s).")
    else:
        print("Todas as credenciais respondem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(executar()))
