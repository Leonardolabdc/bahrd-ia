"""Tranca das rotas do painel.

**Por que existe.** O túnel do Cloudflare é aberto para o Twilio alcançar
`/whatsapp/entrada` — e expõe a API inteira junto. Sem isto, qualquer um com o
endereço lê `/painel/fila` e recebe a fila com nome de motorista, placa e
endereço. Foi verificado em 17/08/2026: estava aberto.

**O que isto não é.** Não é autenticação de usuário. É um segredo compartilhado
que impede acesso anônimo — a diferença entre "qualquer um que descobrir a URL"
e "quem tem a chave". Login de operador, sessão e perfil estão no roteiro em
`docs/07-seguranca.md`, para quando a POC virar sistema.

**O que fica de fora, e por quê:**

* `/saude/*` — é o `HEALTHCHECK` da imagem (`curl /saude/vivo`). Proteger aqui
  deixaria o contêiner permanentemente insalubre.
* `/midia/*` — o Twilio busca o áudio gerado com as credenciais **dele**, não
  as nossas. Exigir token faria a nota de voz nunca chegar ao motorista.
* `/whatsapp/entrada` — já autentica de verdade, pela assinatura HMAC do
  Twilio sobre a URL e os parâmetros. Um token a mais não acrescentaria nada.
"""

from __future__ import annotations

from secrets import compare_digest

from fastapi import Header, HTTPException, status

from central_ia.config import settings
from central_ia.observability.logging import logger

log = logger(__name__)

CABECALHO = "X-Painel-Token"


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
