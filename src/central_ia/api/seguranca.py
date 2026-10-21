"""Trancas das rotas do painel: o token da borda e o login de quem usa.

São duas, e valem juntas em todo `/painel/*`.

**1. O token da borda (`X-Painel-Token`).** O túnel do Cloudflare é aberto para
o Twilio alcançar `/whatsapp/entrada` — e expõe a API inteira junto. Sem isto,
qualquer um com o endereço lê `/painel/fila` e recebe a fila com nome de
motorista, placa e endereço. Foi verificado em 17/08/2026: estava aberto. O
Caddy injeta o token no caminho servidor-a-servidor; ele nunca chega ao
navegador. É a credencial entre a borda e a API, não de uma pessoa.

**2. O login (`exigir_sessao`, `exigir_admin`).** Fecha a lacuna 12 da
auditoria: antes, quem abria o site entrava. Agora cada pessoa entra com
usuário e senha, definidos na configuração (`PAINEL_USUARIOS`, sem cadastro
pela tela), e recebe um cookie `HttpOnly` com um token de sessão que o Redis
guarda pelo hash (ver `api/sessoes_do_painel.py`). A sessão vale
`PAINEL_SESSAO_HORAS` **sem uso**: cada requisição que passa por
`exigir_sessao` renova o prazo. Dois perfis:

* `operador` — a fila, as ocorrências, os encerrados, os desativados e os
  números removidos: o que se usa para atender.
* `admin` — tudo isso, mais a Visão geral (números agregados de supervisão:
  `/painel/metricas` e `/painel/reincidencia`) e o que muda o sistema ou manda
  mensagem de verdade: a tela de eventos de teste, a troca de modelo e a
  simulação.

A conferência é **no servidor**, em cada requisição. A tela esconde o que o
operador não pode usar, mas quem decide é a dependência: esconder botão não é
controle de acesso.

Sem usuário configurado, o comportamento depende do ambiente. Em produção o
painel **fecha** (503) e o boot loga um erro: painel aberto em produção por
esquecimento de variável é exatamente a falha que o login existe para evitar.
Fora de produção continua aberto, como era, com aviso no boot — é o que mantém
a máquina de desenvolvimento e a suíte de testes funcionando sem configuração.

**O que fica de fora das duas trancas, e por quê:**

* `/saude/*` — é o `HEALTHCHECK` da imagem (`curl /saude/vivo`). Proteger aqui
  deixaria o contêiner permanentemente insalubre.
* `/midia/*` — o Twilio busca o áudio gerado com as credenciais **dele**, não
  as nossas. Exigir token faria a nota de voz nunca chegar ao motorista.
* `/whatsapp/entrada` — já autentica de verdade, pela assinatura HMAC do
  Twilio sobre a URL e os parâmetros. Um token a mais não acrescentaria nada.
* `/eventos/*` — quem chama é o rastreador, de servidor para servidor, e a
  prova de origem é a assinatura HMAC do corpo. Não há pessoa para entrar.
"""

from __future__ import annotations

from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from redis.exceptions import RedisError

from central_ia.api import sessoes_do_painel
from central_ia.config import Settings, settings
from central_ia.observability.logging import logger
from central_ia.senhas import Perfil, UsuarioDoPainel

log = logger(__name__)

CABECALHO = "X-Painel-Token"

#: O cookie da sessão. `HttpOnly`: nenhum JavaScript da página o lê, então um
#: script injetado não o leva embora. `SameSite=Strict`: o navegador não o
#: manda em requisição que nasce em outro site, o que fecha CSRF sem token.
COOKIE_SESSAO = "bahrd_sessao"

LOGIN_NAO_CONFIGURADO = (
    "O login do painel não está configurado neste servidor: defina "
    "PAINEL_USUARIOS (gere a entrada com scripts/criar_usuario_painel.py). "
    "Em produção, sem usuário, o painel fica fechado."
)
SESSAO_AUSENTE = "Sessão ausente ou expirada. Entre de novo."
SO_ADMIN = "Esta função é só do perfil admin."
REDIS_FORA = "Não foi possível conferir a sessão agora. Tente de novo em instantes."


async def exigir_token_do_painel(
    x_painel_token: str | None = Header(default=None, alias=CABECALHO),
) -> None:
    """Barra a requisição quando o token não confere.

    Com `PAINEL_TOKEN` vazio, deixa passar: é o que mantém uma máquina de
    desenvolvimento funcionando sem configuração. O aviso de que está assim sai
    no boot, em `avisar_se_aberto`.
    """
    esperado = settings().painel_token
    if esperado is None:
        return

    # `compare_digest` em vez de `==`: comparação de string vaza o tamanho do
    # prefixo correto pelo tempo de resposta. O ataque é remoto e demorado,
    # mas a defesa custa uma linha.
    if x_painel_token is None or not compare_digest(
        x_painel_token, esperado.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Cabeçalho {CABECALHO} ausente ou inválido.",
        )


def avisar_se_aberto() -> None:
    """Grita no boot quando o painel está sem tranca.

    O modo aberto é conveniente e silencioso — exatamente a combinação que faz
    alguém esquecer dele até o dia em que a fila tem dado real.
    """
    if settings().painel_token is None:
        log.warning(
            "painel_sem_token",
            detalhe=(
                "Rotas /painel/* abertas. Aceitável em desenvolvimento; defina "
                "PAINEL_TOKEN antes de expor por túnel ou receber evento real."
            ),
        )


# ───────────────────────────────── o login ─────────────────────────────────


@dataclass(frozen=True)
class QuemEsta:
    """Quem fez a requisição. `usuario` é `None` quando o login está desligado."""

    usuario: str | None
    perfil: Perfil
    login_ativo: bool


def usuarios_ou_503(cfg: Settings) -> dict[str, UsuarioDoPainel]:
    """Os usuários configurados, ou 503 em produção quando não há nenhum.

    Fora de produção, sem usuário, devolve o dicionário vazio e quem chamou
    decide: as rotas do painel abrem, a de login responde que está desligado.
    """
    usuarios = cfg.usuarios_do_painel()
    if not usuarios and cfg.em_producao:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=LOGIN_NAO_CONFIGURADO
        )
    return usuarios


def _sem_sessao() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SESSAO_AUSENTE)


def redis_fora(erro: Exception) -> HTTPException:
    """503 quando o Redis não responde. Falha fechada, nunca "deixa passar".

    Sem Redis não há como saber quem é quem, e abrir o painel nesse caso seria
    deixá-lo aberto toda vez que o Redis piscar.
    """
    log.error("painel_sessao_sem_redis", erro=type(erro).__name__)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=REDIS_FORA)


async def exigir_sessao(request: Request) -> QuemEsta:
    """Barra a requisição sem sessão válida. Vale para todo `/painel/*`.

    O perfil vem da **configuração atual**, não do que foi gravado no login.
    Assim, tirar alguém de `PAINEL_USUARIOS` (ou rebaixar de admin para
    operador) e reiniciar a API vale na hora, sem esperar a sessão expirar.

    Cada passagem por aqui renova o prazo da sessão no Redis: o prazo conta
    a partir do último uso, não do login.
    """
    cfg = settings()
    usuarios = usuarios_ou_503(cfg)
    if not usuarios:
        # Fora de produção e sem usuário: aberto, como era antes do login. O
        # aviso disso sai no boot, em `avisar_sobre_o_login`.
        return QuemEsta(usuario=None, perfil="admin", login_ativo=False)

    token = request.cookies.get(COOKIE_SESSAO)
    if not token:
        raise _sem_sessao()

    try:
        dados = await sessoes_do_painel.ler_e_renovar(cfg, token)
        usuario = usuarios.get(str(dados.get("usuario", ""))) if dados else None
        if dados is not None and usuario is None:
            # Sessão de alguém que saiu da configuração: some agora, e não
            # depois de doze horas sem uso.
            await sessoes_do_painel.apagar(cfg, token)
    except (RedisError, OSError) as erro:
        raise redis_fora(erro) from erro

    if usuario is None:
        raise _sem_sessao()
    return QuemEsta(usuario=usuario.nome, perfil=usuario.perfil, login_ativo=True)


async def exigir_admin(quem: Annotated[QuemEsta, Depends(exigir_sessao)]) -> QuemEsta:
    """403 para o operador. Visão geral, disparar evento, trocar modelo e
    simular são de admin.

    `Depends(exigir_sessao)` aqui não confere a sessão duas vezes: o FastAPI
    guarda o resultado de cada dependência durante a requisição.
    """
    if quem.perfil != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SO_ADMIN)
    return quem


def avisar_sobre_o_login() -> None:
    """Diz no boot como o login está. Em produção sem usuário, é erro.

    Mesmo raciocínio de `avisar_se_aberto`: o modo aberto é silencioso, e
    silêncio é como ele é esquecido.
    """
    cfg = settings()
    usuarios = cfg.usuarios_do_painel()
    if usuarios:
        log.info(
            "painel_login_ativo",
            usuarios=len(usuarios),
            admins=sum(1 for u in usuarios.values() if u.perfil == "admin"),
            sessao_horas=cfg.painel_sessao_horas,
        )
    elif cfg.em_producao:
        log.error(
            "painel_sem_login",
            detalhe=(
                "PAINEL_USUARIOS vazio em produção: /painel/* responde 503 até "
                "alguém configurar. Gere a entrada com scripts/criar_usuario_painel.py."
            ),
        )
    else:
        log.warning(
            "painel_sem_login",
            detalhe=(
                "PAINEL_USUARIOS vazio: o painel abre sem login, com perfil admin. "
                "Aceitável em desenvolvimento; em produção o painel fecharia."
            ),
        )
