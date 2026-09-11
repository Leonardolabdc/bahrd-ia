"""Adaptador da WhatsApp Cloud API (Meta) — o destino, não a ponte.

O Twilio (`twilio.py`) é sandbox de teste. Este fala direto com a Meta: mesmo
canal que vai rodar em produção, sem intermediário e sem a taxa de US$ 0,005 por
mensagem que o Twilio cobra por cima da tarifa da própria Meta (doc 06 §4).

Quatro diferenças em relação ao Twilio, e por que cada uma importa:

1. **Assinatura é HMAC-SHA256 sobre o corpo bruto**, não SHA1 sobre a URL.
   Tem de ser o corpo **exatamente como chegou** — reserializar o JSON muda um
   byte e a conferência falha.
2. **O webhook tem aperto de mão.** A Meta faz um `GET` com `hub.challenge` e
   espera o valor de volta em texto puro. Sem isso ela recusa a URL e nada é
   entregue.
3. **Mídia vem em dois tempos.** O payload traz um `id`, não uma URL. É preciso
   pedir a URL e só então baixar — as duas chamadas autenticadas.
4. **Fora da janela de 24 h só sai template.** Texto livre só é aceito depois
   que o cliente falou. É o que torna barato o nosso fluxo (doc 11 §8): um
   template por ocorrência, conversa grátis.

O payload é aninhado e vem em lote. A extração é defensiva de propósito: a Meta
manda eventos que não são mensagem — status de entrega, leitura, reação — e
tratar um `status` como fala do cliente faria a IA responder ao próprio eco.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

import httpx
import structlog

from central_ia.config import Settings

log = structlog.get_logger(__name__)

#: Versão da Graph API. Fixada de propósito: a Meta muda o formato entre
#: versões, e descobrir isso em produção é pior que atualizar de tempo em tempo.
VERSAO_GRAPH = "v26.0"

_BASE = f"https://graph.facebook.com/{VERSAO_GRAPH}"

#: O mesmo do Twilio — falha de rede não pode segurar o webhook.
TEMPO_LIMITE_S = 20.0

#: Teto da Meta para o valor de um `{{n}}` no corpo do modelo.
LIMITE_PARAMETRO = 1024

#: Quantos botões cabem numa mensagem interativa. Passando disso é lista.
LIMITE_BOTOES = 3

#: Rótulo de botão interativo. Curto de doer, e sem emoji — a mesma regra que
#: barrou o template em 27/08/2026.
LIMITE_ROTULO_BOTAO = 20

#: Corpo da mensagem interativa.
LIMITE_CORPO_INTERATIVO = 1024

#: Qualquer corrida de espaço, **quebra de linha inclusive**.
_ESPACO = re.compile(r"\s+")

#: O que entra num `{{n}}` quando não sobrou nada legível.
#:
#: A Meta recusa parâmetro vazio, e recusar o parâmetro é recusar a mensagem
#: inteira. Um traço é feio; não avisar o motorista de que mexeram na bateria
#: do caminhão é grave.
PARAMETRO_VAZIO = "-"


def parametro_seguro(valor: str) -> str:
    """Deixa o texto no formato que a Meta aceita dentro de um `{{n}}`.

    Duas regras dela, e as duas derrubam o envio inteiro quando violadas:
    **parâmetro não pode ter quebra de linha nem tabulação**, e não pode passar
    de 1024 caracteres.

    Isso importa porque o conteúdo não é nosso. O `Local:` cai em cascata até o
    `objeto_geografico` — nome de cerca cadastrado por alguém na plataforma da
    Bahrd, que pode ter vindo colado de qualquer lugar. Um `\\n` ali fazia a Meta
    recusar, e como as duas tentativas (mapa e texto) mandam o mesmo local, as
    duas falhavam: o motorista não recebia nem o mapa **nem o aviso do alarme**.

    Não é validação de segurança — a blindagem da conversa é outra e vive em
    `agent/blindagem.py`. Aqui é compatibilidade com o formato de quem recebe.
    """
    limpo = _ESPACO.sub(" ", valor).strip()
    if len(limpo) > LIMITE_PARAMETRO:
        # Corta no teto e marca o corte, para quem lê saber que continuava.
        limpo = limpo[: LIMITE_PARAMETRO - 1].rstrip() + "…"
    return limpo or PARAMETRO_VAZIO


class MetaIndisponivel(RuntimeError):
    """A Meta não aceitou ou não respondeu. Quem chama decide o que fazer.

    Nunca vira 500 no webhook: a Meta trata erro HTTP como endpoint quebrado e
    reduz as entregas — mesma lógica que já vale para o Twilio.
    """


# ─────────────────────────────── entrada ───────────────────────────────


def assinatura_valida(app_secret: str, corpo_bruto: bytes, enviada: str) -> bool:
    """Confere o `X-Hub-Signature-256`.

    `corpo_bruto` tem de ser o corpo **como chegou**, antes de virar JSON.
    Comparação em tempo constante, pela mesma razão do painel: comparar com `==`
    vaza o prefixo correto pelo tempo de resposta.
    """
    if not enviada.startswith("sha256="):
        return False
    esperada = hmac.new(app_secret.encode("utf-8"), corpo_bruto, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, enviada[len("sha256=") :])


def desafio(parametros: dict[str, str], verify_token: str) -> str | None:
    """O aperto de mão do `GET`. Devolve o `hub.challenge`, ou `None` se recusa.

    A Meta só salva a URL se receber o desafio de volta **em texto puro** — JSON
    não serve. Token errado devolve `None`, e a rota responde 403: quem não sabe
    o token não configura o nosso webhook.
    """
    if parametros.get("hub.mode") != "subscribe":
        return None
    if not hmac.compare_digest(parametros.get("hub.verify_token", ""), verify_token):
        return None
    return parametros.get("hub.challenge")


class MensagemRecebida:
    """Uma fala do cliente, já achatada do payload aninhado da Meta."""

    __slots__ = (
        "de",
        "texto",
        "midia_id",
        "midia_tipo",
        "mensagem_id",
        "botao",
        "botao_id",
        "contexto_id",
    )

    def __init__(
        self,
        de: str,
        texto: str = "",
        midia_id: str | None = None,
        midia_tipo: str | None = None,
        mensagem_id: str | None = None,
        botao: str | None = None,
        botao_id: str | None = None,
        contexto_id: str | None = None,
    ) -> None:
        self.de = de
        self.texto = texto
        self.midia_id = midia_id
        self.midia_tipo = midia_tipo
        self.mensagem_id = mensagem_id
        #: O identificador que **nós** demos ao botão, quando fomos nós que o
        #: montamos. Vazio nas respostas rápidas de template, onde a Meta manda
        #: o rótulo de volta e não há id nosso para carregar.
        self.botao_id = botao_id
        #: O rótulo do botão tocado, quando foi toque e não digitação.
        #:
        #: Separado do `texto` porque as duas coisas se parecem e não são a
        #: mesma: "Preciso de ajuda!" digitado é desabafo, tocado é escolha
        #: num menu que **nós** desenhamos. Só o segundo pode disparar um
        #: caminho fixo — senão a frase certa na conversa vira um comando.
        self.botao = botao
        #: A mensagem NOSSA a que esta responde, quando a Meta diz qual é.
        #:
        #: ⭐ **É o que resolve o cliente de frota.** Vem sempre que a pessoa
        #: toca num botão do template, e também quando ela usa o "responder"
        #: citando uma mensagem. Com cinco caminhões em evento no mesmo
        #: telefone, é este campo que diz de qual placa ela está falando —
        #: sem ele, o sistema teria de chutar na mais recente.
        #:
        #: `None` em mensagem digitada solta, que é o caso em que não há como
        #: saber e o chute é inevitável.
        self.contexto_id = contexto_id

    @property
    def tem_audio(self) -> bool:
        return bool(self.midia_id) and (self.midia_tipo or "").startswith("audio")

    def __repr__(self) -> str:  # pragma: no cover — diagnóstico
        return f"MensagemRecebida(de={self.de!r}, texto={self.texto!r}, midia={self.midia_tipo!r})"


def extrair(payload: dict[str, Any]) -> list[MensagemRecebida]:
    """Achata o payload da Meta em falas do cliente.

    Devolve lista porque a Meta **manda em lote** — vários eventos num POST só.
    Devolve vazio quando não há fala: status de entrega, leitura e reação
    chegam pelo mesmo webhook, e tratá-los como fala faria a IA responder ao
    próprio eco.

    Toda navegação é defensiva. O formato é aninhado em cinco níveis e a Meta
    já mudou campo entre versões; um `KeyError` aqui derrubaria o canal.
    """
    achadas: list[MensagemRecebida] = []

    for entrada in payload.get("entry") or []:
        for mudanca in entrada.get("changes") or []:
            valor = mudanca.get("value") or {}
            for msg in valor.get("messages") or []:
                recebida = _uma(msg)
                if recebida is not None:
                    achadas.append(recebida)

    return achadas


def _uma(msg: dict[str, Any]) -> MensagemRecebida | None:
    de = str(msg.get("from") or "").strip()
    if not de:
        return None

    tipo = msg.get("type")
    identificador = msg.get("id")
    #: A qual mensagem nossa esta responde. Presente em todo toque de botão de
    #: template, e em toda resposta citada. Ver `MensagemRecebida.contexto_id`.
    contexto = str((msg.get("context") or {}).get("id") or "").strip() or None

    if tipo == "text":
        texto = str((msg.get("text") or {}).get("body") or "").strip()
        return MensagemRecebida(
            de=de, texto=texto, mensagem_id=identificador, contexto_id=contexto
        )

    # ── Toque em botão ──────────────────────────────────────────────────────
    #
    # Duas formas, e a diferença é de onde o botão veio:
    #
    #   `button`      resposta rápida de um MODELO — é a nossa, do disparo
    #   `interactive` botão ou lista de uma mensagem interativa da API
    #
    # Antes de 27/08 nenhuma das duas era lida: `_uma` devolvia `None` e o
    # toque sumia. O cliente tocava em "Preciso de ajuda!" e não acontecia
    # nada — pior que não ter botão, porque ele acha que pediu socorro.
    if tipo == "button":
        bloco = msg.get("button") or {}
        rotulo = str(bloco.get("text") or bloco.get("payload") or "").strip()
        return MensagemRecebida(
            de=de,
            texto=rotulo,
            botao=rotulo or None,
            mensagem_id=identificador,
            contexto_id=contexto,
        )

    if tipo == "interactive":
        bloco = msg.get("interactive") or {}
        escolha = bloco.get("button_reply") or bloco.get("list_reply") or {}
        rotulo = str(escolha.get("title") or escolha.get("id") or "").strip()
        return MensagemRecebida(
            de=de,
            texto=rotulo,
            botao=rotulo or None,
            # O `id` é **nosso** — nós o escolhemos ao montar a pergunta. É por
            # ele que a rota decide o caminho, e não pelo rótulo: rótulo é
            # texto que alguém reescreve para caber em 20 caracteres, `id` é
            # contrato. Trocar "Em manutenção" por "Na oficina" não pode mudar
            # o comportamento do sistema.
            botao_id=str(escolha.get("id") or "").strip() or None,
            mensagem_id=identificador,
            contexto_id=contexto,
        )

    # `audio` e `voice` são a mesma coisa para nós: o cliente falou.
    if tipo in ("audio", "voice"):
        bloco = msg.get(tipo) or {}
        return MensagemRecebida(
            de=de,
            midia_id=str(bloco.get("id") or "") or None,
            midia_tipo=str(bloco.get("mime_type") or "audio/ogg"),
            mensagem_id=identificador,
            contexto_id=contexto,
        )

    # Imagem e vídeo chegam e hoje não são lidos. Devolver a fala vazia é
    # deliberado: o fluxo trata como "não entendi" e pede texto, em vez de
    # ignorar em silêncio — que é o defeito que o doc 07 registrou.
    if tipo in ("image", "video", "document", "sticker"):
        bloco = msg.get(tipo) or {}
        return MensagemRecebida(
            de=de,
            texto=str(bloco.get("caption") or "").strip(),
            midia_id=str(bloco.get("id") or "") or None,
            midia_tipo=str(bloco.get("mime_type") or tipo),
            mensagem_id=identificador,
            contexto_id=contexto,
        )

    return None


class StatusDeEntrega:
    """O que aconteceu com a mensagem **depois** do aceite da Meta.

    Existe porque `200` no envio não quer dizer entregue. A Graph API aceita,
    devolve `wamid`, e só então descobre que o destinatário não tem WhatsApp,
    que o template está reprovado ou que a janela fechou — e avisa por este
    webhook. Descartar esse aviso, que era o que fazíamos, deixa a pergunta
    "por que não chegou?" sem resposta possível.

    Custou uma tarde em 24/08: o Bruno recebeu, o Ana não, e os dois
    envios tinham logado sucesso.
    """

    __slots__ = ("mensagem_id", "situacao", "destinatario", "codigo", "titulo", "detalhe")

    def __init__(
        self,
        mensagem_id: str,
        situacao: str,
        destinatario: str,
        codigo: int | None = None,
        titulo: str | None = None,
        detalhe: str | None = None,
    ) -> None:
        self.mensagem_id = mensagem_id
        self.situacao = situacao
        self.destinatario = destinatario
        self.codigo = codigo
        self.titulo = titulo
        self.detalhe = detalhe

    @property
    def falhou(self) -> bool:
        return self.situacao == "failed"


def extrair_status(payload: dict[str, Any]) -> list[StatusDeEntrega]:
    """Os avisos de entrega do mesmo webhook que traz as falas.

    `sent` → aceite · `delivered` → chegou no aparelho · `read` → foi aberta ·
    `failed` → não chegou, e o motivo vem em `errors`.

    Mesma navegação defensiva do `extrair()`, e pelo mesmo motivo.
    """
    achados: list[StatusDeEntrega] = []

    for entrada in payload.get("entry") or []:
        for mudanca in entrada.get("changes") or []:
            for st in (mudanca.get("value") or {}).get("statuses") or []:
                erros = st.get("errors") or []
                primeiro = erros[0] if erros else {}
                dados = primeiro.get("error_data") or {}
                achados.append(
                    StatusDeEntrega(
                        mensagem_id=str(st.get("id") or ""),
                        situacao=str(st.get("status") or "desconhecido"),
                        destinatario=str(st.get("recipient_id") or ""),
                        codigo=primeiro.get("code"),
                        titulo=primeiro.get("title"),
                        detalhe=dados.get("details") or primeiro.get("message"),
                    )
                )

    return achados


def numero_para_whatsapp(numero: str) -> str:
    """`+5541999999999` → `5541999999999`.

    A Meta não usa `+` nem prefixo de canal. O Twilio usa `whatsapp:+55…`.
    Converter num lugar só evita que cada ponto de uso invente o seu.
    """
    return "".join(c for c in numero if c.isdigit())


# ─────────────────────────────── saída ───────────────────────────────


class ClienteMeta:
    """Envio e download pela Graph API. Mesma superfície do `ClienteTwilio`."""

    def __init__(self, cfg: Settings) -> None:
        if cfg.meta_access_token is None or not cfg.meta_phone_number_id:
            raise MetaIndisponivel("META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID ausente.")
        self._token = cfg.meta_access_token.get_secret_value()
        self._numero_id = cfg.meta_phone_number_id
        self._http = httpx.AsyncClient(timeout=TEMPO_LIMITE_S)

    @property
    def _cabecalhos(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _postar(self, corpo: dict[str, Any]) -> dict[str, Any]:
        try:
            resposta = await self._http.post(
                f"{_BASE}/{self._numero_id}/messages",
                headers=self._cabecalhos,
                json=corpo,
            )
        except httpx.HTTPError as erro:
            raise MetaIndisponivel(f"falha de rede: {erro}") from erro

        if resposta.status_code >= 400:
            # O corpo do erro da Meta é numerado e explica de verdade. Guardar
            # só o status esconde justamente a informação que resolve.
            raise MetaIndisponivel(f"HTTP {resposta.status_code}: {resposta.text[:300]}")
        return resposta.json()

    async def enviar_texto(self, para: str, texto: str) -> dict[str, Any]:
        """Só funciona dentro da janela de 24 h. Fora dela, use template."""
        return await self._postar(
            {
                "messaging_product": "whatsapp",
                "to": numero_para_whatsapp(para),
                "type": "text",
                "text": {"preview_url": False, "body": texto},
            }
        )

    async def enviar_template(
        self,
        para: str,
        nome: str,
        idioma: str = "pt_BR",
        parametros: list[str] | None = None,
        localizacao: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Abre a conversa. É a única mensagem cobrada (doc 11 §8).

        `localizacao` preenche o cabeçalho de mapa dos modelos `*_mapa` — o
        cartãozinho do WhatsApp que abre no Waze. Exige `latitude` e
        `longitude`; `name` e `address` são opcionais.

        ⚠️ **Modelo com cabeçalho de localização exige o bloco.** Não é
        opcional, é campo obrigatório como qualquer `{{1}}`: mandar sem ele faz
        a Meta recusar, e aí não sai notificação nenhuma. Quem escolhe entre o
        modelo com mapa e o de texto é a rota, olhando se o evento tem
        coordenada — ver `eventos.py`.
        """
        modelo: dict[str, Any] = {"name": nome, "language": {"code": idioma}}
        componentes: list[dict[str, Any]] = []

        if localizacao:
            componentes.append(
                {
                    "type": "header",
                    "parameters": [{"type": "location", "location": localizacao}],
                }
            )
        if parametros:
            componentes.append(
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": parametro_seguro(p)} for p in parametros
                    ],
                }
            )
        if componentes:
            modelo["components"] = componentes

        return await self._postar(
            {
                "messaging_product": "whatsapp",
                "to": numero_para_whatsapp(para),
                "type": "template",
                "template": modelo,
            }
        )

    async def mostrar_digitando(self, mensagem_id: str) -> None:
        """Marca a mensagem como lida e acende o "digitando…" no celular.

        **Não é uma mensagem, e por isso não é cobrada.** A Meta fatura por
        mensagem entregue; confirmação de leitura não é entrega de nada, e o
        indicador pega carona nessa mesma chamada. É o raro caso em que a
        melhoria de experiência sai de graça.

        Existe porque a IA leva uns três segundos para responder — é o tempo do
        modelo, e não dá para encurtar muito. Três segundos de silêncio depois
        de tocar num botão parecem travamento, e quem acha que travou toca de
        novo. O indicador transforma espera em espera **visível**, que é outra
        coisa para quem está do outro lado.

        O WhatsApp apaga sozinho quando a resposta chega, ou depois de 25
        segundos. Não há o que desligar.

        **Nunca levanta.** Falhar aqui não pode custar o atendimento: o pior
        que acontece sem o indicador é a conversa ficar como era ontem.
        """
        try:
            resposta = await self._postar(
                {
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": mensagem_id,
                    "typing_indicator": {"type": "text"},
                }
            )
        except MetaIndisponivel as erro:
            log.info("digitando_falhou", erro=str(erro), mensagem_id=mensagem_id)
            return

        # A resposta vai para o log porque `200` aqui não prova que apareceu na
        # tela. Em 27/08/2026 o indicador foi aceito e o gestor não o viu, e
        # sem isto não havia como saber se a Meta tinha recusado em silêncio ou
        # se o aparelho dele simplesmente não mostra.
        log.info("digitando", mensagem_id=mensagem_id, resposta=resposta)

    async def enviar_botoes(
        self, para: str, texto: str, botoes: list[tuple[str, str]]
    ) -> dict[str, Any]:
        """Pergunta com botões, **dentro da janela** — não é template.

        **Esta é a diferença que destrava o fluxo dos gestores.** Botão de
        template precisa de aprovação da Meta e vale para toda a base; botão de
        mensagem interativa a IA decide na hora, muda quando quiser, e não passa
        por análise nenhuma. O que os dois têm em comum é o que importa: o toque
        volta como webhook e a conversa continua.

        Só funciona com a janela de 24 h aberta, que é justamente o caso — a
        pessoa já respondeu ao template para chegar aqui.

        `botoes` é `[(id, rótulo)]`. O `id` é o que volta no webhook e é nosso;
        o rótulo é o que a pessoa lê.
        """
        if not botoes:
            raise MetaIndisponivel("mensagem interativa sem botão nenhum")
        if len(botoes) > LIMITE_BOTOES:
            raise MetaIndisponivel(
                f"a Meta aceita no máximo {LIMITE_BOTOES} botões; vieram {len(botoes)}"
            )

        # Recorta em vez de recusar: perder a pergunta inteira porque um rótulo
        # tem 22 caracteres seria trocar um defeito visível por um grave.
        # Emoji nem entra em discussão — a Meta rejeita, e descobrimos isso
        # publicando o template em 27/08/2026.
        acoes = [
            {
                "type": "reply",
                "reply": {"id": ident, "title": parametro_seguro(rotulo)[:LIMITE_ROTULO_BOTAO]},
            }
            for ident, rotulo in botoes
        ]

        return await self._postar(
            {
                "messaging_product": "whatsapp",
                "to": numero_para_whatsapp(para),
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": parametro_seguro(texto)[:LIMITE_CORPO_INTERATIVO]},
                    "action": {"buttons": acoes},
                },
            }
        )

    async def enviar_audio(self, para: str, url: str) -> dict[str, Any]:
        """A Meta busca a URL sozinha — ela precisa ser pública e alcançável."""
        return await self._postar(
            {
                "messaging_product": "whatsapp",
                "to": numero_para_whatsapp(para),
                "type": "audio",
                "audio": {"link": url},
            }
        )

    async def baixar_midia(self, midia_id: str) -> tuple[bytes, str | None]:
        """Dois tempos: pedir a URL, depois baixar. As duas autenticadas.

        A URL devolvida expira em minutos e **não** é pública — baixar sem o
        cabeçalho de autorização devolve 401.
        """
        try:
            meta = await self._http.get(f"{_BASE}/{midia_id}", headers=self._cabecalhos)
            if meta.status_code >= 400:
                raise MetaIndisponivel(f"mídia {midia_id}: HTTP {meta.status_code}")

            url = (meta.json() or {}).get("url")
            if not url:
                raise MetaIndisponivel(f"mídia {midia_id} sem URL na resposta")

            arquivo = await self._http.get(url, headers=self._cabecalhos)
            if arquivo.status_code >= 400:
                raise MetaIndisponivel(f"download de {midia_id}: HTTP {arquivo.status_code}")
        except httpx.HTTPError as erro:
            raise MetaIndisponivel(f"falha de rede na mídia: {erro}") from erro

        return arquivo.content, arquivo.headers.get("content-type")

    async def fechar(self) -> None:
        await self._http.aclose()
