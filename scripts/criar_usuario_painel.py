"""Gera a entrada de um usuário do painel, para colar em `PAINEL_USUARIOS`.

Pede a senha duas vezes, sem eco, e imprime **só** a entrada
`usuario:perfil:hash`. A senha não é impressa, não é gravada em arquivo e não
passa pela linha de comando — onde ficaria no histórico do shell e na lista de
processos de quem estivesse olhando.

Uso, de dentro do contêiner da API (o caminho de produção; `-it` porque a
senha é digitada):

    docker exec -it $(docker compose -f docker-compose.prod.yml ps -q api) \\
        python3 scripts/criar_usuario_painel.py ana admin

Ou na máquina local, a partir da raiz do repositório:

    PYTHONPATH=src py -3.13 scripts/criar_usuario_painel.py beto operador

Depois, no `.env` do servidor, junte as entradas com `;` e reinicie a API:

    PAINEL_USUARIOS=ana:admin:scrypt.16384...;beto:operador:scrypt.16384...

Trocar a senha de alguém é gerar a entrada de novo e substituir a antiga.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from central_ia.senhas import PERFIS, SENHA_MINIMA, gerar_hash, validar_nome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera a entrada usuario:perfil:hash para PAINEL_USUARIOS."
    )
    parser.add_argument("usuario", help="nome de login, minúsculo, sem espaço (ex.: ana)")
    parser.add_argument("perfil", choices=PERFIS, help="admin ou operador")
    args = parser.parse_args(argv)

    try:
        usuario = validar_nome(args.usuario)
    except ValueError as erro:
        print(f"Usuário inválido: {erro}.", file=sys.stderr)
        return 2

    # Os avisos vão para stderr, e só a entrada para stdout: assim
    # `... > entrada.txt` ou um pipe pegam a linha limpa, sem texto em volta.
    senha = getpass.getpass(f"Senha para {usuario}: ")
    if len(senha) < SENHA_MINIMA:
        print(f"Senha curta demais: o mínimo é {SENHA_MINIMA} caracteres.", file=sys.stderr)
        return 1
    if getpass.getpass("Repita a senha: ") != senha:
        print("As duas senhas não conferem. Nada foi gerado.", file=sys.stderr)
        return 1

    print(f"{usuario}:{args.perfil}:{gerar_hash(senha)}")
    print(
        "\nCole a linha acima em PAINEL_USUARIOS no .env do servidor (várias "
        "entradas separadas por ';') e reinicie a API.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
