"""Adaptador do Twilio para WhatsApp — ponte de teste, não destino.

O sandbox do Twilio manda e recebe WhatsApp sem verificação de empresa na Meta
e sem depender de credencial da Bahrd. É o que permite testar a conversa real
com um celular hoje.

O que se perde em relação à WhatsApp Cloud API, e por que importa:

* **Sem template aprovado.** Fora da janela de 24 h desde a última mensagem do
  cliente, nada sai. Na operação real é a IA que inicia o contato — então o
  fluxo "evento chega, IA liga primeiro" só é testável aqui se o celular
  responder algo antes.
* **Só fala com quem entrou no sandbox.** Cada número precisa mandar
  `join <duas-palavras>` uma vez.
* **O número remetente é do Twilio**, não da Bahrd. O cliente vê um número
  americano.

Nada disso invalida o teste do que interessa: o texto que a IA escreve, o
tempo de resposta e o comportamento do playbook.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from central_ia.config import Settings
from central_ia.observability.logging import logger

log = logger(__name__)


@dataclass(frozen=True)
class MensagemEnviada:
    sid: str
    status: str


class TwilioIndisponivel(RuntimeError):
    """Falha ao falar com o Twilio. Nunca vira mensagem entregue por engano."""


def assinatura_valida(auth_token: str, url: str, parametros: dict[str, str], enviada: str) -> bool:
    """Confere o cabeçalho `X-Twilio-Signature`.

    Sem esta checagem, qualquer pessoa que descobrisse a URL do webhook poderia
    injetar mensagens como se fossem de um cliente — e a IA responderia. O
    algoritmo é o do Twilio: concatena a URL com cada par chave+valor em ordem
    alfabética de chave, assina com HMAC-SHA1 usando o auth token, e compara em
    Base64.

    A comparação é `compare_digest` de propósito: comparar assinatura com `==`
    vaza informação pelo tempo de resposta.
    """
    if not auth_token or not enviada:
        return False

    base = url + "".join(f"{c}{parametros[c]}" for c in sorted(parametros))
    esperada = base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), base.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    return hmac.compare_digest(esperada, enviada)


class ClienteTwilio:
    def __init__(self, cfg: Settings) -> None:
        if not cfg.twilio_account_sid or cfg.twilio_auth_token is None:
            raise TwilioIndisponivel(
                "TWILIO_ACCOUNT_SID e TWILIO_AUTH_TOKEN não estão preenchidos no .env."
            )

        self._sid = cfg.twilio_account_sid
        self._remetente = cfg.twilio_whatsapp_from
        self._http = httpx.AsyncClient(
            base_url=f"{cfg.twilio_base_url}/2010-04-01/Accounts/{self._sid}",
            timeout=httpx.Timeout(30.0, connect=10.0),
            auth=(self._sid, cfg.twilio_auth_token.get_secret_value()),
        )

    async def enviar_texto(self, para: str, corpo: str) -> MensagemEnviada:
        """`para` no formato `whatsapp:+5511999999999`."""
        resposta = await self._http.post(
            "/Messages.json",
            data={"From": self._remetente, "To": para, "Body": corpo},
        )

        if resposta.status_code >= 400:
            # O 63016 é o erro mais provável nesta POC: janela de 24 h fechada.
            # Sem esta mensagem o sintoma chega como "não recebi nada".
            corpo_erro = resposta.text[:400]
            if "63016" in corpo_erro:
                raise TwilioIndisponivel(
                    "Janela de 24 h fechada: o Twilio só deixa enviar depois que o "
                    "número escreveu para o sandbox. Mande qualquer mensagem do "
                    "celular e tente de novo."
                )
            raise TwilioIndisponivel(f"Twilio respondeu {resposta.status_code}: {corpo_erro}")

        dados = resposta.json()
        log.info("whatsapp_enviado", sid=dados.get("sid"), status=dados.get("status"))
        return MensagemEnviada(sid=dados.get("sid", ""), status=dados.get("status", ""))

    async def enviar_audio(
        self, para: str, url_do_audio: str, legenda: str = ""
    ) -> MensagemEnviada:
        """Manda uma nota de voz. `url_do_audio` precisa ser pública.

        O Twilio não recebe o arquivo: ele recebe o endereço e busca depois.
        Se a URL não for alcançável de fora, a mensagem falha do lado deles e
        o motorista simplesmente não recebe nada.
        """
        dados = {"From": self._remetente, "To": para, "MediaUrl": url_do_audio}
        if legenda:
            dados["Body"] = legenda

        resposta = await self._http.post("/Messages.json", data=dados)
        if resposta.status_code >= 400:
            raise TwilioIndisponivel(
                f"Twilio recusou o áudio ({resposta.status_code}): {resposta.text[:300]}"
            )

        corpo = resposta.json()
        log.info("whatsapp_audio_enviado", sid=corpo.get("sid"), status=corpo.get("status"))
        return MensagemEnviada(sid=corpo.get("sid", ""), status=corpo.get("status", ""))

    async def baixar_midia(self, url: str) -> tuple[bytes, str]:
        """Busca o áudio que o cliente mandou. Devolve `(bytes, content-type)`.

        A URL é do próprio Twilio e **exige autenticação** — a mesma da conta.
        Baixar sem credencial devolve 401, e o sintoma seria "o cliente mandou
        áudio e a IA não respondeu".
        """
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            auth=self._http.auth,
            follow_redirects=True,
        ) as http:
            resposta = await http.get(url)

        if resposta.status_code >= 400:
            raise TwilioIndisponivel(
                f"Não foi possível baixar a mídia ({resposta.status_code})."
            )

        tipo = resposta.headers.get("Content-Type", "application/octet-stream")
        return resposta.content, tipo

    async def saldo_ok(self) -> str:
        """Consulta a conta. Não envia mensagem e não consome crédito."""
        resposta = await self._http.get(".json")
        if resposta.status_code >= 400:
            raise TwilioIndisponivel(
                f"Twilio respondeu {resposta.status_code}: {resposta.text[:200]}"
            )
        dados = resposta.json()
        return f"{dados.get('friendly_name', '?')} · {dados.get('status', '?')}"

    async def fechar(self) -> None:
        await self._http.aclose()


#: O `+` é **opcional** de propósito — ver `variantes_do_numero`.
_CELULAR_BR = re.compile(r"^\+?55(\d{2})(\d{8,9})$")


def variantes_do_numero(numero: str) -> set[str]:
    """As grafias possíveis do mesmo celular brasileiro, em forma canônica.

    Desde 2016 os celulares no Brasil têm 9 dígitos, mas o nono é omitido em
    boa parte dos cadastros e — o que importa aqui — cada interlocutor entrega
    o número de um jeito. Todas estas linhas são a mesma pessoa:

        +5541999999999        Twilio, e o payload da Bahrd
        whatsapp:+5541999999999
        554199999999          a Meta, no webhook: sem `+` e sem o nono dígito

    Comparar texto puro faz o webhook recusar o dono do celular, e o sintoma é
    "não está autorizado" para quem está autorizado. Por isso a comparação é
    feita sobre o conjunto de grafias.

    **Corrigido em 25/08/2026, depois de o bug aparecer no celular de um
    motorista.** O regex exigia o `+` inicial, e a Meta não manda `+`. Isso
    fazia *toda* mensagem vinda do WhatsApp cair fora da lista de autorizados —
    e passava despercebido porque, quando a IA abre a conversa pelo evento, a
    sessão já existe e este teste nem chega a rodar. Bastou um restart perder a
    sessão para um "Diamante" no meio do atendimento virar recusa.

    A saída é **canônica**: sempre `+55...`, sempre sem o prefixo `whatsapp:`.
    Antes ela preservava o prefixo, e aí `whatsapp:+5541...` e `+5541...`
    geravam conjuntos que nunca se cruzavam — só funcionava porque a lista
    trazia as duas formas escritas à mão. Comparação só é confiável quando os
    dois lados são normalizados para a mesma coisa.

    Só mexe em celular brasileiro: número de outro país volta limpo, mas sem
    variante nova inventada.
    """
    limpo = numero.removeprefix("whatsapp:").strip()

    achado = _CELULAR_BR.match(limpo)
    if achado is None:
        return {limpo}

    ddd, assinante = achado.groups()
    if len(assinante) == 9 and assinante.startswith("9"):
        outra = assinante[1:]
    elif len(assinante) == 8 and assinante[0] in "6789":
        outra = "9" + assinante
    else:
        return {f"+55{ddd}{assinante}"}

    return {f"+55{ddd}{assinante}", f"+55{ddd}{outra}"}


def numero_autorizado(recebido: str, autorizados: list[str]) -> bool:
    """O número que chegou está na lista, em qualquer uma das duas grafias?"""
    grafias = variantes_do_numero(recebido)
    return any(grafias & variantes_do_numero(a) for a in autorizados)


def url_do_webhook(base: str) -> str:
    """A URL exata que o Twilio precisa ter cadastrada.

    Existe como função porque a assinatura é calculada **sobre a URL**: um
    `/` a mais ou a menos entre o que está cadastrado no Twilio e o que o
    servidor reconstrói invalida a assinatura, e o sintoma é um 403 sem pista.
    """
    return base.rstrip("/") + "/whatsapp/entrada"


def montar_url_assinada(base: str, parametros: dict[str, str]) -> str:
    """Só para teste local: reproduz a URL que o Twilio assinaria."""
    return url_do_webhook(base) + ("?" + urlencode(parametros) if parametros else "")
