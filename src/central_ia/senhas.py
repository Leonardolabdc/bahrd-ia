"""Senha do painel: hash, conferência e a lista de usuários da configuração.

**Sem cadastro pela tela, de propósito.** Quem entra no painel é decidido por
quem administra o servidor, numa variável de ambiente (`PAINEL_USUARIOS`), e
não por um formulário. Isso tira do caminho a parte que mais dá errado em
login caseiro: troca de senha, recuperação por e-mail, tabela de usuários
exposta a injeção. O que sobra é pequeno o bastante para ser lido inteiro.

**O formato de cada entrada**, separadas por `;`::

    usuario:perfil:scrypt.16384.8.1.<sal>.<hash>

O hash é `hashlib.scrypt` da biblioteca padrão, sem dependência nova, com sal
aleatório por usuário. Sal e hash vão em base64 para URL, sem `=` no fim.

⚠️ **Os campos do hash são separados por ponto, e não por `$`** como no
formato clássico `$scrypt$...`. O motivo foi medido, não suposto: o
`docker compose` interpola `$` nos valores de `env_file`. A linha
`scrypt$16384$8$1$abc$xyz` chegou ao contêiner como `scrypt$$16384$$8$$1`, com
o sal e o hash trocados por string vazia, e o login quebraria sem nenhum erro
que apontasse para o `.env`. Ponto não é especial em lugar nenhum dessa
cadeia: nem no compose, nem no shell, nem no PowerShell. E também não aparece
em base64 para URL, então a separação nunca é ambígua.

Gere a entrada com `scripts/criar_usuario_painel.py`; nunca escreva à mão.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Literal

Perfil = Literal["admin", "operador"]
PERFIS: tuple[Perfil, ...] = ("admin", "operador")

ALGORITMO = "scrypt"

#: Parâmetros do scrypt. N=2^14, r=8, p=1 é o mínimo que a OWASP recomenda e
#: custa uns 16 MB e algumas dezenas de milissegundos por conferência — o
#: bastante para encarecer um ataque de dicionário sobre um hash vazado e
#: pouco para quem entra uma vez por plantão.
N_PADRAO = 2**14
R_PADRAO = 8
P_PADRAO = 1
#: Abaixo disto o hash é recusado no carregamento: um N pequeno colado por
#: engano tornaria a senha barata de quebrar sem ninguém perceber.
N_MINIMO = 2**14
N_MAXIMO = 2**20
TAMANHO_SAL = 16
TAMANHO_HASH = 32

SENHA_MINIMA = 10

_USUARIO_VALIDO = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")


class UsuariosDoPainelInvalidos(RuntimeError):
    """`PAINEL_USUARIOS` malformado.

    ⚠️ **`RuntimeError`, e não `ValueError`, de propósito.** O pydantic embrulha
    `ValueError` de validador num `ValidationError` que repete o valor recebido
    (`input_value=...`) — aqui, a linha inteira com os hashes, direto no log de
    boot. Exceção de outro tipo atravessa o pydantic sem ser embrulhada, e a
    mensagem diz só o que está errado e em qual entrada.
    """


@dataclass(frozen=True)
class UsuarioDoPainel:
    nome: str
    perfil: Perfil
    hash_senha: str


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _scrypt(senha: str, sal: bytes, n: int, r: int, p: int, tamanho: int) -> bytes:
    return hashlib.scrypt(
        senha.encode("utf-8"),
        salt=sal,
        n=n,
        r=r,
        p=p,
        # O padrão do OpenSSL é 32 MB; N=2^20 precisaria de 1 GB. Folga de
        # 1 MB sobre o que o scrypt pede de fato, e nada além disso.
        maxmem=128 * r * n + 1024 * 1024,
        dklen=tamanho,
    )


def gerar_hash(senha: str, *, n: int = N_PADRAO, r: int = R_PADRAO, p: int = P_PADRAO) -> str:
    """O texto que vai no terceiro campo da entrada de `PAINEL_USUARIOS`."""
    sal = secrets.token_bytes(TAMANHO_SAL)
    chave = _scrypt(senha, sal, n, r, p, TAMANHO_HASH)
    return f"{ALGORITMO}.{n}.{r}.{p}.{_b64(sal)}.{_b64(chave)}"


@dataclass(frozen=True)
class _HashLido:
    n: int
    r: int
    p: int
    sal: bytes
    chave: bytes


def _ler_hash(texto: str) -> _HashLido:
    """Desmonta o hash, ou levanta `ValueError` dizendo o que está errado.

    A mensagem nunca repete o hash: ela pode acabar num log.
    """
    partes = texto.split(".")
    if len(partes) != 6 or partes[0] != ALGORITMO:
        raise ValueError(
            "o hash deve ter a forma scrypt.N.r.p.sal.hash "
            "(gere com scripts/criar_usuario_painel.py)"
        )
    try:
        n, r, p = (int(x) for x in partes[1:4])
    except ValueError:
        raise ValueError("N, r e p do hash precisam ser números inteiros") from None
    if n < N_MINIMO or n > N_MAXIMO or n & (n - 1):
        raise ValueError(f"N do hash precisa ser potência de 2 entre {N_MINIMO} e {N_MAXIMO}")
    if not 1 <= r <= 32 or not 1 <= p <= 16:
        raise ValueError("r ou p do hash fora da faixa aceita")
    try:
        sal, chave = _de_b64(partes[4]), _de_b64(partes[5])
    except (binascii.Error, ValueError):
        raise ValueError("sal ou hash não estão em base64 válido") from None
    if len(sal) < TAMANHO_SAL or len(chave) < TAMANHO_HASH:
        raise ValueError("sal ou hash curtos demais")
    return _HashLido(n, r, p, sal, chave)


def verificar_senha(senha: str, hash_senha: str) -> bool:
    """A senha confere com o hash? Formato inválido é `False`, nunca exceção.

    Comparação com `secrets.compare_digest`: `==` em bytes vaza, pelo tempo de
    resposta, quantos bytes iniciais batem.
    """
    try:
        lido = _ler_hash(hash_senha)
    except ValueError:
        return False
    calculado = _scrypt(senha, lido.sal, lido.n, lido.r, lido.p, len(lido.chave))
    return secrets.compare_digest(calculado, lido.chave)


#: Um hash que não pertence a ninguém, conferido quando o usuário não existe.
#:
#: Sem isto, "usuário inexistente" responderia na hora e "senha errada" depois
#: de um scrypt inteiro — e o tempo de resposta diria a quem testa nomes quais
#: deles existem. Gerado uma vez por processo, com os mesmos parâmetros de um
#: hash de verdade, para custar o mesmo.
_HASH_FICTICIO: str | None = None


def hash_ficticio() -> str:
    global _HASH_FICTICIO
    if _HASH_FICTICIO is None:
        _HASH_FICTICIO = gerar_hash(secrets.token_urlsafe(16))
    return _HASH_FICTICIO


def validar_nome(nome: str) -> str:
    """Nome de usuário normalizado, ou `ValueError`. Minúsculo, sem espaço."""
    normalizado = nome.strip().lower()
    if not _USUARIO_VALIDO.fullmatch(normalizado):
        raise ValueError(
            "o usuário deve ter de 2 a 40 caracteres: letras minúsculas sem acento, "
            "números, ponto, hífen ou sublinhado, começando por letra ou número"
        )
    return normalizado


def carregar_usuarios(texto: str | None) -> dict[str, UsuarioDoPainel]:
    """`PAINEL_USUARIOS` → `{nome: usuário}`. Malformado levanta, nunca ignora.

    Ignorar uma entrada torta seria o pior comportamento possível: a API
    subiria, o login daquela pessoa falharia como "senha inválida" e ninguém
    olharia para o `.env`. Falhar na partida, com o número da entrada, aponta
    direto para o defeito.
    """
    usuarios: dict[str, UsuarioDoPainel] = {}
    if not texto or not texto.strip():
        return usuarios

    entradas = [e.strip() for e in texto.split(";")]
    for posicao, entrada in enumerate(entradas, start=1):
        if not entrada:
            # `;` sobrando no fim é comum e inofensivo.
            continue
        campos = entrada.split(":")
        if len(campos) != 3:
            raise UsuariosDoPainelInvalidos(
                f"PAINEL_USUARIOS, entrada {posicao}: esperado usuario:perfil:hash "
                f"(três campos separados por ':'), encontrados {len(campos)}."
            )
        nome_bruto, perfil, hash_senha = (c.strip() for c in campos)
        try:
            nome = validar_nome(nome_bruto)
        except ValueError as erro:
            raise UsuariosDoPainelInvalidos(
                f"PAINEL_USUARIOS, entrada {posicao}: {erro}."
            ) from None
        if perfil not in PERFIS:
            raise UsuariosDoPainelInvalidos(
                f"PAINEL_USUARIOS, entrada {posicao} ({nome}): perfil "
                f"{perfil!r} desconhecido; use 'admin' ou 'operador'."
            )
        try:
            _ler_hash(hash_senha)
        except ValueError as erro:
            raise UsuariosDoPainelInvalidos(
                f"PAINEL_USUARIOS, entrada {posicao} ({nome}): {erro}."
            ) from None
        if nome in usuarios:
            raise UsuariosDoPainelInvalidos(
                f"PAINEL_USUARIOS, entrada {posicao}: o usuário {nome!r} aparece duas vezes."
            )
        perfil_lido: Perfil = "admin" if perfil == "admin" else "operador"
        usuarios[nome] = UsuarioDoPainel(nome=nome, perfil=perfil_lido, hash_senha=hash_senha)
    return usuarios
