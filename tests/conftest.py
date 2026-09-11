"""A suíte não fala com o mundo, e não deixa rastro em serviço de ninguém.

**Descoberto em 26/08/2026, olhando o Langfuse do projeto.** Dos 35 traces de um
export, 29 tinham `net.peer.ip: "testclient"` e `http.url: http://testserver/…`
— a assinatura do `TestClient` do FastAPI. Ou seja, **eram os testes**.

Duas coisas estavam vazando, e nenhuma das duas era intencional:

* **Telemetria.** `criar_app()` chama `configurar_tracing(settings())`, e
  `settings()` lê o `.env` da máquina. Com as chaves do Langfuse configuradas
  ali, todo teste que subia o app exportava spans para o projeto de verdade —
  inclusive conversas de fixture, com nome e placa inventados, que ficavam
  guardadas ao lado dos atendimentos reais. Consumia cota e sujava a medição.
* **Chamada externa.** `ClienteMeta` só recusa quando falta credencial. Como o
  `.env` tinha, os testes que exercitam a rota inteira **postavam de verdade**
  na Graph API — 13 chamadas num único `pytest`, todas devolvendo 400.

O arquivo `test_rota_eventos_link.py` já dizia, desde antes, que "os testes não
dependem do `.env`: sem isso a suíte passaria ou falharia conforme a máquina de
quem roda, que é o pior tipo de teste". Era verdade para a lógica de negócio e
mentira para tudo que fala com fora. Este arquivo faz a frase valer.

O jeito é limpar **variável de ambiente**, não remendar cada teste: assim vale
para o que já existe e para o que for escrito amanhã, sem ninguém precisar
lembrar.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from central_ia.config import settings
from central_ia.observability import tracing

#: Tudo que faz o processo procurar alguém do lado de fora.
#:
#: Não é lista de segredo — é lista de **saída**. Uma chave a mais aqui só
#: deixa a suíte mais isolada; uma a menos deixa um teste ligando para a rua
#: sem ninguém perceber, que foi exatamente o que aconteceu.
SAIDAS_EXTERNAS = (
    # Observabilidade: sem estas, `configurar_tracing` devolve False e todo
    # span vira no-op.
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_ENVIAR_CONTEUDO",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    # WhatsApp: sem token, `ClienteMeta` levanta `MetaIndisponivel` no
    # construtor, e a rota já trata isso como "template não saiu".
    "META_ACCESS_TOKEN",
    "META_PHONE_NUMBER_ID",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    # Modelo: nenhum teste deveria gastar crédito, e sem chave não gasta nem
    # por acidente.
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    # Voz.
    "DEEPGRAM_API_KEY",
    "ELEVENLABS_API_KEY",
    "CARTESIA_API_KEY",
)


@pytest.fixture(autouse=True)
def sem_saida_para_o_mundo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Autouse: vale para toda a suíte, sem ninguém precisar pedir.

    `settings()` é `lru_cache`, então limpar o ambiente sem limpar o cache não
    faria efeito nenhum — a primeira chamada de qualquer teste congelaria os
    valores do `.env` para todas as outras. Por isso o cache cai antes e depois.

    Um teste que precise de credencial declara a dele com `monkeypatch.setenv`,
    e aí a intenção fica escrita no próprio teste em vez de herdada da máquina.
    """
    for variavel in SAIDAS_EXTERNAS:
        monkeypatch.delenv(variavel, raising=False)

    # `_tracer` e `_conteudo` são globais de módulo que `configurar_tracing`
    # escreve com `global` — e globais não voltam sozinhos no fim do teste.
    #
    # Limpar o ambiente sozinho não bastava: **um** teste que ligasse o tracing
    # contaminava todos os seguintes, e um deles exportou para o Langfuse de
    # verdade uma conversa de fixture, com nome e placa inventados. Levou uma
    # investigação para achar, porque o teste culpado passava e quem vazava era
    # outro, minutos depois na ordem alfabética dos arquivos.
    tracing._tracer = None
    tracing._conteudo = False

    settings.cache_clear()
    yield
    tracing._tracer = None
    tracing._conteudo = False
    settings.cache_clear()
