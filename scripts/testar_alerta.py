"""Dispara o alerta P2 de verdade, sem esperar uma falha real acontecer.

Todo sistema de alerta precisa de um jeito de ser testado sob demanda —
senão a primeira vez que ele dispara é também a primeira vez que alguém
descobre se o canal configurado funciona. Este script simula 10 turnos
falhos (a amostra mínima de `observability/alertas.py`), o que cruza o
limiar de 5% de erro e manda o e-mail real, pelo mesmo caminho de código
que roda em produção — não é um e-mail de teste à parte, é o alerta de
verdade sendo exercitado.

Uso, de dentro do container da API (mesmo ambiente real, com as variáveis
de alerta já configuradas):

    docker exec $(docker compose -f docker-compose.prod.yml ps -q api) \\
        python3 scripts/testar_alerta.py

⚠️ Isso consome o cooldown de 1h — rodar duas vezes seguidas na mesma hora
só dispara e-mail na primeira.
"""

from __future__ import annotations

import asyncio

from central_ia.config import settings
from central_ia.observability import alertas


async def main() -> None:
    cfg = settings()
    print(f"Simulando {alertas.AMOSTRA_MINIMA} turnos falhos (amostra mínima)...")
    for i in range(alertas.AMOSTRA_MINIMA):
        disparou = await alertas.registrar_turno(cfg, sucesso=False)
        if disparou:
            print(f"turno {i + 1}/{alertas.AMOSTRA_MINIMA} — ALERTA DISPARADO")
        else:
            print(f"turno {i + 1}/{alertas.AMOSTRA_MINIMA} — registrado, ainda sem disparo")

    print(
        "\nSe o e-mail não chegou, confira ALERTA_EMAIL_REMETENTE, "
        "ALERTA_EMAIL_SENHA_APP e ALERTA_EMAIL_DESTINATARIO no .env.prod."
    )


asyncio.run(main())
