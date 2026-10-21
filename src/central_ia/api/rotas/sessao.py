"""Entrar, sair e saber quem está: `/painel/sessao`.

Fica num router à parte, e não em `rotas/painel.py`, por um motivo só: o
router do painel exige sessão em **todas** as rotas, e a rota de login é
justamente a que precisa funcionar sem sessão. Pôr uma exceção dentro do
router protegido seria a primeira rota do painel a nascer aberta por
descuido; separar deixa a regra sem exceção.

O token da borda (`X-Painel-Token`) continua valendo aqui também.

As respostas:

* `POST /painel/sessao` — 204 com o cookie; 401 "Usuário ou senha inválidos"
  para usuário inexistente **e** para senha errada, com o mesmo custo de tempo;
  429 depois de cinco falhas em quinze minutos para o mesmo IP e usuário; 409
  fora de produção sem usuário configurado (não há login para fazer); 503 em
  produção sem usuário configurado, ou com o Redis fora.
* `DELETE /painel/sessao` — 204 sempre: apaga a sessão, se houver, e o cookie.
* `GET /painel/sessao` — `{usuario, perfil, login_ativo}`, ou 401.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from central_ia.api import sessoes_do_painel
from central_ia.api.seguranca import (
    COOKIE_SESSAO,
    QuemEsta,
    exigir_sessao,
    exigir_token_do_painel,
    redis_fora,
    usuarios_ou_503,
)
from central_ia.config import settings
from central_ia.observability.logging import logger
from central_ia.senhas import Perfil, hash_ficticio, verificar_senha

log = logger(__name__)

router = APIRouter(
    prefix="/painel",
    tags=["painel"],
    dependencies=[Depends(exigir_token_do_painel)],
)

#: A mesma frase para usuário inexistente e senha errada. Dizer qual dos dois
#: falhou entregaria, a quem testa nomes, a lista de quem existe.
CREDENCIAIS_INVALIDAS = "Usuário ou senha inválidos."
MUITAS_TENTATIVAS = "Muitas tentativas. Tente de novo em alguns minutos."
LOGIN_DESLIGADO = (
    "O login está desligado neste ambiente: PAINEL_USUARIOS está vazio e o "
    "painel abre sem senha."
)


class PedidoDeLogin(BaseModel):
    usuario: str = Field(min_length=1, max_length=64)
    # Teto generoso, mas teto: o scrypt de uma "senha" de megabytes ainda é
    # barato, só que não há motivo para aceitar.
    senha: str = Field(min_length=1, max_length=256)


class SessaoAtual(BaseModel):
    usuario: str | None
    perfil: Perfil
    login_ativo: bool


def ip_do_cliente(request: Request) -> str:
    """O IP de quem está do outro lado, para o contador de tentativas.

    Atrás do Caddy, `request.client.host` é o próprio Caddy, e o IP de verdade
    vem em `X-Forwarded-For`. Usa-se o **último** valor da lista: é o que o
    proxy mais próximo escreveu. Os anteriores, se houver, vieram de quem fez a
    requisição e podem ser inventados à vontade.

    ⚠️ Com a API alcançada direto, sem proxy na frente (o desenvolvimento
    local), o cabeçalho inteiro vem do cliente e pode ser trocado a cada
    tentativa. Em produção a porta 8000 não é publicada; quem fala com a API é
    só o Caddy.
    """
    encaminhado = request.headers.get("x-forwarded-for", "")
    if encaminhado.strip():
        return encaminhado.split(",")[-1].strip()
    return request.client.host if request.client else "desconhecido"


def _por_https(request: Request) -> bool:
    """A requisição chegou por HTTPS? Decide se o cookie sai `Secure`.

    Dev e produção publicados ficam atrás do Caddy, que termina o TLS e avisa
    em `X-Forwarded-Proto: https`. Na máquina local é HTTP puro, e um cookie
    `Secure` lá simplesmente não seria guardado: o login local quebraria.
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return proto.split(",")[0].strip().lower() == "https"


@router.post(
    "/sessao",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Entra no painel com usuário e senha",
)
async def entrar(pedido: PedidoDeLogin, request: Request) -> Response:
    cfg = settings()
    usuarios = usuarios_ou_503(cfg)
    if not usuarios:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=LOGIN_DESLIGADO)

    nome = pedido.usuario.strip().lower()
    ip = ip_do_cliente(request)

    try:
        espera = await sessoes_do_painel.segundos_de_bloqueio(cfg, ip=ip, usuario=nome)
        if espera:
            log.warning("painel_login_bloqueado", janela_restante_s=espera)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=MUITAS_TENTATIVAS,
                headers={"Retry-After": str(espera)},
            )

        usuario = usuarios.get(nome)
        # O scrypt roda mesmo quando o usuário não existe, contra um hash que
        # não é de ninguém: o tempo de resposta não pode dizer quem existe.
        # Em thread, porque são dezenas de milissegundos de CPU, e no laço de
        # eventos isso pararia todas as outras requisições junto.
        confere = await run_in_threadpool(
            verificar_senha,
            pedido.senha,
            usuario.hash_senha if usuario else hash_ficticio(),
        )

        if usuario is None or not confere:
            await sessoes_do_painel.registrar_falha(cfg, ip=ip, usuario=nome)
            # O nome só vai para o log se existir. Um nome que não existe é,
            # muitas vezes, a senha de alguém digitada no campo errado.
            log.warning(
                "painel_login_recusado",
                motivo="usuario_inexistente" if usuario is None else "senha_errada",
                usuario=usuario.nome if usuario else None,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=CREDENCIAIS_INVALIDAS
            )

        await sessoes_do_painel.zerar_falhas(cfg, ip=ip, usuario=nome)
        token = await sessoes_do_painel.criar(cfg, usuario=usuario.nome, perfil=usuario.perfil)
    except (RedisError, OSError) as erro:
        raise redis_fora(erro) from erro

    log.info("painel_login", usuario=usuario.nome, perfil=usuario.perfil)
    resposta = Response(status_code=status.HTTP_204_NO_CONTENT)
    resposta.set_cookie(
        COOKIE_SESSAO,
        token,
        max_age=sessoes_do_painel.duracao_s(cfg),
        path="/",
        httponly=True,
        samesite="strict",
        secure=_por_https(request),
    )
    return resposta


@router.delete(
    "/sessao",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Sai do painel",
)
async def sair(request: Request) -> Response:
    cfg = settings()
    usuarios_ou_503(cfg)

    token = request.cookies.get(COOKIE_SESSAO)
    if token:
        try:
            await sessoes_do_painel.apagar(cfg, token)
        except (RedisError, OSError) as erro:
            # O cookie sai mesmo assim. A sessão no Redis, se ele voltar, vence
            # sozinha pelo TTL — e sem o cookie ninguém mais a apresenta.
            log.error("painel_logout_sem_redis", erro=type(erro).__name__)

    resposta = Response(status_code=status.HTTP_204_NO_CONTENT)
    resposta.delete_cookie(
        COOKIE_SESSAO,
        path="/",
        httponly=True,
        samesite="strict",
        secure=_por_https(request),
    )
    return resposta


@router.get(
    "/sessao",
    response_model=SessaoAtual,
    summary="Quem está no painel, e com que perfil",
)
async def sessao_atual(quem: Annotated[QuemEsta, Depends(exigir_sessao)]) -> SessaoAtual:
    return SessaoAtual(usuario=quem.usuario, perfil=quem.perfil, login_ativo=quem.login_ativo)
