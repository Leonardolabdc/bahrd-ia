"""Configuração da aplicação.

Regra não negociável (doc 02 §3.4, armadilha 2): **o código nunca lê arquivo de
configuração**. Nada de ``open(".env")``, nada de YAML de settings. Tudo chega
por ``os.environ``, atrás deste ``Settings``.

O motivo é a migração para a OCI: lá não existe ``.env``. Quem carrega o
arquivo em desenvolvimento é o ``docker compose``, não a aplicação — então
trocar de ambiente é trocar a origem das variáveis, não caçar ``open()`` pelo
projeto.

Segredos seguem o mesmo princípio, mas por uma porta separada
(:mod:`central_ia.ports.secrets`), porque na Fase 2 eles vêm do OCI Vault.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _vazio_e_ausente(valor: object) -> object:
    """Trata string vazia como credencial não configurada.

    O `.env` mantém a linha da chave presente e vazia até alguém preenchê-la.
    Sem esta conversão, `""` vira `SecretStr("")` — que não é `None` — e o
    adaptador manda uma credencial vazia ao provedor. A resposta é `401`, e o
    diagnóstico acusa "chave inválida" quando o correto seria "chave ausente".
    """
    if isinstance(valor, str):
        return valor.strip() or None
    return valor


#: Segredo que pode legitimamente não existir ainda nesta fase da POC.
SegredoOpcional = Annotated[SecretStr | None, BeforeValidator(_vazio_e_ausente)]


def _por_virgula(valor: str) -> list[str]:
    """`a, b , c` → `["a", "b", "c"]`. Aceita também `["a","b"]`.

    Toda lista que vem do ambiente é declarada como **texto** e convertida
    aqui, nunca como `list[str]`. O motivo é concreto: o pydantic-settings
    tenta `json.loads` em qualquer campo de tipo complexo **antes** de qualquer
    validador rodar. Escrever `TWILIO_NUMEROS_DE_TESTE=whatsapp:+5511...` no
    `.env` derruba a aplicação no boot com um `JSONDecodeError` que não diz
    qual variável está torta — e a correção "certa" seria digitar
    `["whatsapp:+5511..."]`, que ninguém adivinha.

    O formato JSON continua aceito porque `.env` que já existem por aí usam
    ele. Ignorar isso quebrou o CORS do painel uma vez: a lista virava
    `['["http://localhost:5173"', '"http://127.0.0.1:5173"]']`, nenhuma origem
    batia, e o sintoma no browser era só "Failed to fetch".
    """
    texto = valor.strip()
    if not texto:
        return []

    if texto.startswith("["):
        try:
            carregado = json.loads(texto)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(carregado, list):
                return [str(parte).strip() for parte in carregado if str(parte).strip()]

    return [parte.strip() for parte in texto.split(",") if parte.strip()]

Ambiente = Literal["dev", "hml", "prd-poc"]
ModoVoz = Literal["voz_simulada", "voz_livekit_sip"]
OrigemSegredo = Literal["env", "oci_vault"]
ProvedorLLM = Literal["anthropic", "openrouter"]
CanalWhatsApp = Literal["twilio", "meta"]
FonteDeRastreamento = Literal["amostra", "link"]


#: Nomes de variável que o código deixou de ler, e para onde foram.
#:
#: Não é documentação: `_recusar_variaveis_mortas` usa este mapa para derrubar
#: a partida quando alguém preenche o nome antigo. Cresce quando uma variável
#: for renomeada de novo — é mais barato do que descobrir em produção que o
#: canal está mudo.
_WHATSAPP_RENOMEADAS = {
    "WHATSAPP_TOKEN": "META_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID": "META_PHONE_NUMBER_ID",
    "WHATSAPP_VERIFY_TOKEN": "META_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET": "META_APP_SECRET",
    "WHATSAPP_API_VERSION": "META_API_VERSION",
}


class Settings(BaseSettings):
    """Configuração completa, montada a partir do ambiente."""

    # `env_file` fica deliberadamente ausente: em dev o compose exporta as
    # variáveis; na OCI elas vêm do Vault e do manifesto.
    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
        env_nested_delimiter="__",
    )

    # ─────────── Aplicação ───────────
    app_env: Ambiente = "dev"
    app_nome: str = "central-ia"
    public_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    log_formato: Literal["json", "console"] = "json"
    kill_switch_ativo: bool = False
    modo_voz: ModoVoz = "voz_simulada"
    secret_provider: OrigemSegredo = "env"

    # Origens autorizadas a chamar a API a partir do browser. Em produção é o
    # domínio do painel; nunca "*", porque o painel usa credencial.
    # Texto separado por vírgula — ver `_por_virgula`.
    cors_origens: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Token exigido nas rotas `/painel/*`, no cabeçalho `X-Painel-Token`.
    #
    # Existe por causa do túnel: ele é aberto para o Twilio alcançar
    # `/whatsapp/entrada`, e expõe **a API inteira** junto. Sem isto, qualquer
    # um com o endereço lê a fila com nome, placa e endereço.
    #
    # Vazio deixa o painel aberto — é o que mantém `.\dev.ps1 up` funcionando
    # sem configuração numa máquina de desenvolvimento. A API avisa no boot
    # quando está assim, e **precisa estar preenchido antes do primeiro evento
    # real**, que é quando o dado deixa de ser fictício.
    #
    # Não é autenticação de usuário: é uma tranca contra acesso anônimo. Login
    # de operador está no roteiro de segurança (`docs/07-seguranca.md`).
    painel_token: SegredoOpcional = None

    #: A Central pode disparar evento de teste pelo painel?
    #:
    #: Nasce **desligada**. Ligada, a tela manda WhatsApp de verdade, pelo
    #: número oficial verificado da Bahrd, para um celular escolhido por uma
    #: pessoa. É a única parte do sistema em que o destino não vem de um evento
    #: de veículo, e por isso é a mais travada.
    #:
    #: Quem lê isto não é o `.env`, é `testes_pelo_painel`: `em_producao` vence
    #: a variável, do mesmo jeito que vence em `langfuse_com_conteudo`.
    painel_testes_ativo: bool = False

    # ─────────── Canal de WhatsApp ───────────
    # `twilio` é o sandbox que roda hoje; `meta` é a API oficial, que é o
    # destino — sem intermediário e sem a taxa por mensagem que o Twilio cobra
    # por cima da tarifa da própria Meta (doc 06 §4). Os dois adaptadores
    # convivem: a variável escolhe, e o que já funciona não é tocado.
    canal_whatsapp: CanalWhatsApp = "twilio"

    meta_access_token: SegredoOpcional = None
    meta_phone_number_id: str = ""
    #: Chave do `X-Hub-Signature-256`. Sem ele não há como distinguir a Meta de
    #: qualquer um que descubra a URL — ver doc 11 §6.
    meta_app_secret: SegredoOpcional = None
    #: Frase que você inventa e repete no painel da Meta, para o aperto de mão.
    meta_verify_token: SegredoOpcional = None

    # ─────────── Modelo de linguagem ───────────
    # `anthropic` é o destino pela latência (um salto de rede a menos) e pelas
    # saídas estruturadas. Cache de prompt **não** é o motivo: a OpenRouter
    # aceita `cache_control` para Claude — o nosso adaptador é que ainda não o
    # envia. `openrouter` serve de ponte e de banco de provas: uma chave só
    # compara Claude e Gemini por variável, sem tocar em código.
    llm_provider: ProvedorLLM = "anthropic"

    openrouter_api_key: SegredoOpcional = None
    #: ⚠️ **Passou a ser o Flash Lite em 03/09/2026, a pedido da operação**, que
    #: quis o mais barato como padrão da tela de teste.
    #:
    #: ⛔ E ele está **reprovado para produção**: em 55 conversas medidas tratou
    #: um possível roubo como rotina e 9% das conversas morreram mudas, uma delas
    #: depois de o cliente pedir para falar com uma pessoa (docs/arquivo/26). Um
    #: ambiente novo que não declarar nada sobe nele.
    #:
    #: Vale para teste, e a economia real é menor do que a tabela sugere: o
    #: template `UTILITY` da Meta custa R$ 0,035 nos dois, então o atendimento
    #: inteiro fica em R$ 0,04 contra R$ 0,13. Cerca de 3x, não 26x.
    #:
    #: **Antes de qualquer demonstração, volte para `anthropic/claude-sonnet-5`.**
    openrouter_modelo: str = "google/gemini-2.5-flash-lite"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ─────────── Claude (Anthropic) ───────────
    anthropic_api_key: SegredoOpcional = None
    # Sonnet, não Opus: é o mesmo modelo que roda hoje pela OpenRouter. Trocar
    # de provedor **não pode** trocar de modelo em silêncio — Opus custa +67%
    # (US$ 5/25 contra US$ 3/15), o que são ~R$ 5.500/mês a mais no volume de
    # 41.000. Subir para Opus é decisão consciente, não efeito colateral.
    anthropic_modelo_principal: str = "claude-sonnet-5"

    # Esforço de raciocínio por tipo de chamada. Os padrões são **exatamente o
    # que roda hoje** — mudá-los aqui muda custo e latência de verdade.
    #: Ligação: turnos curtos por design, o plano já previa `low`.
    anthropic_effort_voz: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    #: WhatsApp: o texto tem tempo de pensar que a voz não tem.
    anthropic_effort_texto: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    #: Triagem de pânico. Era `high` aqui e `medium` no código — o código
    #: vencia, porque ninguém lia esta configuração. Alinhado com o que roda.
    anthropic_effort_triagem: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    # ─────────── STT / TTS ───────────
    deepgram_api_key: SegredoOpcional = None
    deepgram_model: str = "nova-3"
    deepgram_language: str = "pt-BR"
    elevenlabs_api_key: SegredoOpcional = None
    elevenlabs_voice_id: str = ""
    elevenlabs_model_voz: str = "eleven_flash_v2_5"
    elevenlabs_model_audio: str = "eleven_v3"
    elevenlabs_output_format: str = "ulaw_8000"

    # ─────────── Twilio (WhatsApp de teste) ───────────
    # Ponte para a POC, não destino. O sandbox do Twilio manda e recebe WhatsApp
    # sem verificação de empresa na Meta e sem depender da TI da Bahrd — que é o
    # que estava travando o teste ponta a ponta. Limitações que importam: só
    # fala com número que entrou no sandbox, a sessão expira em 24 h, e não há
    # template aprovado (fora da janela, nada sai). Para produção, o caminho
    # continua sendo a WhatsApp Cloud API abaixo.
    twilio_account_sid: str = ""
    twilio_auth_token: SegredoOpcional = None
    twilio_whatsapp_from: str = Field(
        default="whatsapp:+14155238886",
        description="Número do sandbox. O prefixo `whatsapp:` faz parte do valor.",
    )
    twilio_base_url: str = "https://api.twilio.com"
    #: Números autorizados a abrir evento por mensagem, no formato
    #: `whatsapp:+55...`, separados por vírgula. Vazio = ninguém abre. Sem esta
    #: lista, qualquer pessoa que descobrisse a URL do webhook poderia disparar
    #: atendimento em nome da central.
    twilio_numeros_de_teste: str = ""

    #: A IA responde em áudio quando o cliente manda áudio?
    #:
    #: Espelhar o canal é o padrão certo: quem mandou nota de voz está dirigindo
    #: e não vai parar para ler. Desligar isso é útil para demonstrar sem gastar
    #: caracteres da ElevenLabs.
    whatsapp_responder_em_audio: bool = True

    # ─────────── WhatsApp Cloud API ───────────
    #
    # ⛔ **As credenciais moram em `meta_*`, não aqui.** Existiam cinco campos
    # `whatsapp_*` neste ponto — `whatsapp_token`, `whatsapp_phone_number_id`,
    # `whatsapp_verify_token`, `whatsapp_app_secret` e `whatsapp_api_version` —
    # e **nenhum era lido por lugar nenhum**: o adaptador sempre leu `meta_*`
    # (`integrations/mensageria/meta.py`). Saíram em 09/09/2026.
    #
    # Enquanto existiam, preencher `WHATSAPP_TOKEN` no `.env` era aceito em
    # silêncio e não ligava canal nenhum. Apagar os campos sozinho não resolve:
    # com `extra="ignore"`, a variável continuaria sendo engolida sem uma
    # palavra. Por isso existe `_recusar_variaveis_mortas` mais abaixo, que
    # transforma o engano em erro de partida com o nome certo ao lado.

    # ─────────── GoTo Connect (SIP) ───────────
    sip_domain: str = "reg.jiveip.net"
    sip_outbound_proxy: str = ""
    sip_port: int = 5060
    sip_username: str = ""
    sip_password: SegredoOpcional = None
    sip_caller_id: str = ""
    sip_codec: str = "PCMU"
    sip_ramal_operador: str = ""

    # ─────────── LiveKit ───────────
    livekit_url: str = "ws://livekit:7880"
    livekit_api_key: SegredoOpcional = None
    livekit_api_secret: SegredoOpcional = None

    # ─────────── Oracle (registro) ───────────
    oracle_user: str = "CENTRAL_IA"
    oracle_password: SecretStr = SecretStr("")
    oracle_dsn: str = "oracle:1521/FREEPDB1"
    oracle_wallet_dir: str = ""
    oracle_wallet_password: SegredoOpcional = None
    oracle_pool_min: int = 2
    oracle_pool_max: int = 10
    oracle_auditoria_dias_idle: int = Field(
        default=0,
        description=(
            "Retenção da BLOCKCHAIN TABLE de auditoria. 0 em dev, 16 em hml/prd-poc. "
            "16 é o teto do Autonomous Database (ORA-05807), não uma escolha — o banco "
            "em contêiner aceita mais e não reclama."
        ),
    )

    # ─────────── MySQL (operacional) ───────────
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_database: str = "central_ia_op"
    mysql_user: str = "central_ia"
    mysql_password: SecretStr = SecretStr("")
    mysql_ssl_mode: Literal["DISABLED", "PREFERRED", "REQUIRED"] = "DISABLED"

    # ─────────── Redis (barramento / cache) ───────────
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_auth_token: SegredoOpcional = None
    redis_stream_eventos: str = "eventos.rastreamento"

    # ─────────── Object storage ───────────
    s3_endpoint: str = "http://minio:9000"
    s3_regiao: str = "sa-saopaulo-1"
    s3_bucket: str = "poc-ia-audio"
    s3_access_key: SegredoOpcional = None
    s3_secret_key: SegredoOpcional = None

    # ─────────── Sistema próprio da Bahrd ───────────
    # `amostra` até existir acesso de leitura à plataforma. Ver
    # `integrations/rastreamento/bahrd_api.py`.
    fonte_rastreamento: FonteDeRastreamento = "amostra"

    # ⚠️ Modo de demonstração. Com `True`, a IA encerra sozinha um pânico que
    # ela classificou como falso positivo com confiança alta — o caso não chega
    # ao operador. Contraria o princípio 3 (evento crítico é exclusivamente
    # humano) e existe para medir a classificação contra dados reais antes de
    # qualquer decisão sobre supressão. **Não vai para produção assim.**
    panico_autonomo: bool = False

    # ⛔ **A triagem prévia do pânico. Com `False` ela não roda.**
    #
    # Ligada (o padrão), todo evento com `exige_triagem_previa` passa por uma
    # classificação **antes de qualquer contato**: acima de
    # `LIMIAR_ESCALONAMENTO` o caso é de uma pessoa e ninguém escreve para o
    # motorista. É o princípio de que a IA não conversa com quem pode estar sob
    # coação — se o botão foi apertado de verdade, uma mensagem avisa quem
    # estiver do lado dele que a central percebeu.
    #
    # Desligada, o pânico se comporta como remoção de bateria: a IA abre com o
    # template, conduz pelo `PB-PANICO` e pode encerrar sozinha.
    #
    # ⚠️ **Existe por causa da fonte de amostra, e some com ela.** Sem acesso à
    # plataforma da Bahrd, um veículo fora dos três de `rastreamento/amostra.py`
    # chega à triagem sem posição, sem velocidade, sem rota e sem histórico. O
    # prompt manda arredondar para cima diante de dado ausente — e faz certo —
    # então **todo pânico de teste pontua alto** e nenhum é conduzido pela IA.
    # Não é a triagem errando; é ela decidindo no escuro.
    #
    # Em 02/09/2026 a triagem falhou em 8 de 9 disparos de teste, e a decisão do
    # A operação foi desligá-la para conseguir exercitar o playbook. A alternativa
    # sem chave nenhuma é usar `"rotulo": "XYZ4E56"`, que traz o contexto
    # completo de um acionamento acidental.
    #
    # ⛔ **`False` em produção é um pânico real atendido por robô, sem nenhuma
    # avaliação prévia.** O dia em que a `fonte_rastreamento` virar `link`, esta
    # chave sai do `.env` e o padrão volta a valer sozinho.
    triagem_previa_ativa: bool = True

    # ⚠️ Modo de demonstração. Com `False`, **não existe escalonamento**: tudo
    # que a IA passaria para um operador ela encerra sozinha, registrando na
    # trilha o motivo pelo qual teria escalado.
    #
    # Existe porque nesta fase não há operador, não há cliente real e não há o
    # dado interno da Bahrd para cruzar — escalar é entregar o caso a ninguém, e
    # a fila humana fica cheia de ocorrências que ninguém vai olhar.
    #
    # **A decisão da IA não muda**: ela continua concluindo "isto é de um
    # humano" exatamente como antes, e isso continua indo para a auditoria. O
    # que muda é o destino. Quando houver operador e leitura do Oracle da Bahrd,
    # `True` devolve o comportamento sem tocar em prompt nem em playbook.
    escalonamento_humano_ativo: bool = False

    bahrd_webhook_hmac_secret: SegredoOpcional = None
    bahrd_api_base_url: str = ""
    bahrd_api_token: SegredoOpcional = None
    bahrd_modo_ingestao: Literal["webhook", "polling"] = "webhook"

    # ─────────── OCI (Fase 2) ───────────
    oci_region: str = "sa-saopaulo-1"
    oci_compartment_ocid: str = ""
    oci_vault_ocid: str = ""

    # ─────────── Observabilidade ───────────
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""

    # ─────────── Langfuse ───────────
    # Segundo destino dos mesmos spans, especializado em LLM: mostra a conversa
    # turno a turno, agrupada por ocorrência, com custo e tokens ao lado. O
    # Jaeger continua recebendo tudo — um não substitui o outro.
    #
    # Sem as duas chaves, nada é enviado e nenhum código extra roda.
    langfuse_public_key: str = ""
    langfuse_secret_key: SegredoOpcional = None
    #: `cloud.langfuse.com` é a região da UE. Outras: `us.`, `jp.`. Para uma
    #: instância própria, a URL dela.
    langfuse_host: str = "https://cloud.langfuse.com"

    #: **A tranca do conteúdo.** Desligada, o Langfuse recebe só metadado, igual
    #: ao Jaeger — que é a regra geral de `observability/tracing.py`.
    #:
    #: Ligar manda prompt e resposta para fora, e num atendimento real isso
    #: inclui nome de motorista, placa e endereço. Por isso nasce `False` e a
    #: decisão de ligar é sempre explícita, num `.env` que ninguém versiona.
    #: Em produção, `langfuse_com_conteudo` ignora esta variável — ver lá.
    langfuse_enviar_conteudo: bool = False

    @model_validator(mode="before")
    @classmethod
    def _recusar_variaveis_mortas(cls, valores: object) -> object:
        """Recusa subir com credencial de WhatsApp no nome antigo.

        ⛔ **Existe para um erro que não dá sintoma.** O canal de WhatsApp lê
        `META_*`. Quem escrever `WHATSAPP_TOKEN` no `.env` — nome plausível, e
        o que estava no `config.py` até 09/09/2026 — não recebe aviso nenhum:
        `extra="ignore"` engole a variável, a aplicação sobe inteira, os
        healthchecks passam, e o WhatsApp simplesmente não responde. Numa POC
        de monitoramento, isso é o alarme de um cliente não chegando a
        ninguém.

        Falhar na partida é o comportamento certo aqui: o deploy quebra na
        hora, com o nome novo na mensagem, em vez de quebrar no primeiro
        evento real.

        ⚠️ `WHATSAPP_RESPONDER_EM_AUDIO` **continua válida** — é campo vivo. A
        checagem lista nomes, e não o prefixo, exatamente por causa dela.
        """
        if not isinstance(valores, dict):
            return valores

        presentes = {
            chave.upper(): valores[chave]
            for chave in valores
            if chave.upper() in _WHATSAPP_RENOMEADAS
        }
        # Só reclama do que foi preenchido. Variável declarada e vazia é sobra
        # de `.env.example` copiado, e derrubar por causa dela seria trocar um
        # susto silencioso por um barulhento e inútil.
        preenchidas = sorted(k for k, v in presentes.items() if str(v or "").strip())
        if preenchidas:
            linhas = "\n".join(f"  {k}  →  {_WHATSAPP_RENOMEADAS[k]}" for k in preenchidas)
            raise ValueError(
                "Variável de WhatsApp com nome que o código não lê mais.\n"
                "O canal usa META_*; estes nomes são ignorados em silêncio e o "
                "WhatsApp ficaria mudo sem nenhum erro.\n\n"
                f"{linhas}\n\n"
                "Renomeie no .env (ou no Vault) e suba de novo."
            )
        return valores

    @model_validator(mode="before")
    @classmethod
    def _remover_espacos(cls, valores: object) -> object:
        """Remove espaço em volta de todo valor vindo do ambiente.

        Colar uma chave com um espaço à frente é o erro mais comum ao editar
        `.env` — e o sintoma é péssimo: o header HTTP sai malformado e a
        biblioteca reclama de "illegal header value", que não diz nada sobre a
        causa. Espaço nas pontas nunca é significativo em variável de
        ambiente, então limpar aqui é seguro.
        """
        if isinstance(valores, dict):
            return {
                chave: (valor.strip() if isinstance(valor, str) else valor)
                for chave, valor in valores.items()
            }
        return valores

    # ─────────── Derivados ───────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def origens_cors(self) -> list[str]:
        return _por_virgula(self.cors_origens)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def numeros_de_teste(self) -> list[str]:
        return _por_virgula(self.twilio_numeros_de_teste)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def testes_pelo_painel(self) -> bool:
        """Duas travas, e a segunda não tem chave.

        A primeira é `painel_testes_ativo`, que nasce desligada: a tela nunca
        existe por descuido, só por decisão.

        A segunda é `em_producao`, e ela vence a primeira. Não existe valor de
        `.env` que faça um alarme de mentira sair para o celular de um cliente
        real. Quem esquecer a variável ligada ao promover o ambiente não manda
        nada. É o mesmo raciocínio de `langfuse_com_conteudo`, e é de propósito
        que a forma é idêntica: uma decisão dessas mora no código, à vista, não
        numa variável de ambiente de madrugada.
        """
        return self.painel_testes_ativo and not self.em_producao

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        senha = self.redis_auth_token.get_secret_value() if self.redis_auth_token else ""
        credencial = f":{senha}@" if senha else ""
        return f"redis://{credencial}{self.redis_host}:{self.redis_port}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mysql_url(self) -> str:
        """DSN assíncrono do SQLAlchemy. TLS entra por ``connect_args``, não aqui."""
        senha = self.mysql_password.get_secret_value()
        return (
            f"mysql+aiomysql://{self.mysql_user}:{senha}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mysql_url_sincrono(self) -> str:
        """Usado só pelo Alembic, que roda migração de forma síncrona."""
        senha = self.mysql_password.get_secret_value()
        return (
            f"mysql+pymysql://{self.mysql_user}:{senha}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def em_producao(self) -> bool:
        return self.app_env != "dev"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def modelo_em_uso(self) -> str:
        """Qual cérebro atende agora, sem o chamador precisar saber o provedor.

        Existe para a sessão poder carimbar o modelo na abertura sem repetir o
        `if llm_provider` em cada ponto de chamada. Quando alguém da Central
        troca o modelo, é este valor que muda, e ele passa a valer **da próxima
        conversa em diante**.
        """
        if self.llm_provider == "openrouter":
            return self.openrouter_modelo
        return self.anthropic_modelo_principal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def langfuse_ativo(self) -> bool:
        """Só liga com o par completo. Meia credencial é erro de `.env`, não modo."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def langfuse_com_conteudo(self) -> bool:
        """Duas travas, e a segunda não tem chave.

        A primeira é `langfuse_enviar_conteudo`, que nasce desligada: conteúdo
        nunca sai por descuido, só por decisão.

        A segunda é `em_producao`, e ela vence a primeira. Não existe valor de
        `.env` que faça a conversa de um motorista real sair da produção para
        um serviço de terceiro — quem esquecer a variável ligada ao promover o
        ambiente não vaza nada. Se um dia isso precisar mudar, muda aqui, à
        vista, e não numa variável de ambiente de madrugada.
        """
        return self.langfuse_ativo and self.langfuse_enviar_conteudo and not self.em_producao

    def exigir(self, *campos: str) -> None:
        """Falha cedo se um campo obrigatório para o caminho em uso estiver vazio.

        Usado por adaptadores que só existem em alguns ambientes — o agente de
        voz real exige credencial SIP, o `voz_simulada` não.
        """
        faltando = [c for c in campos if not getattr(self, c, None)]
        if faltando:
            raise RuntimeError(
                "Configuração obrigatória ausente: " + ", ".join(sorted(faltando))
            )


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Instância única. O cache existe para não reler o ambiente a cada request."""
    return Settings()
