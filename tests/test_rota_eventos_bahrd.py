"""A rota que recebe o evento real da Bahrd.

O que estes testes guardam é o **contrato com quem dispara**: o que devolve
200, o que devolve 422, e o que nunca vira atendimento automático.

A regra que mais importa: **falha nossa não pode virar 5xx.** Quem dispara
webhook trata erro HTTP como endpoint quebrado e reduz as entregas — perder o
canal é pior que perder um evento.

Os testes **não dependem do `.env`**: cada um declara se há segredo
configurado. Sem isso a suíte passaria ou falharia conforme a máquina de quem
roda, que é o pior tipo de teste.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from central_ia.api.main import criar_app
from central_ia.api.rotas.eventos import assinatura_confere
from central_ia.config import settings

PAYLOAD = {
    "rotulo": "Veículo ABC-1234",
    "data_hora_evento": "2026-08-19 15:10:00",
    "latitude": -25.4504094,
    "longitude": -49.256198,
    "tipo_evento": "Movimento com ignição desligada",
    "contato_nome": "João da Silva",
    "contato_telefone": "41999999999",
}

SEGREDO = "segredo-combinado-com-a-ti"


@pytest.fixture
def aberto(monkeypatch) -> TestClient:
    """Sem segredo configurado — é o estado de hoje, para testar com Postman.

    A lista de destinos é declarada aqui, não herdada do `.env`: sem segredo a
    rota só escreve para número autorizado, e o teste não pode passar ou falhar
    conforme o que estiver na máquina de quem roda.
    """
    monkeypatch.delenv("BAHRD_WEBHOOK_HMAC_SECRET", raising=False)
    # Em E.164, que é como o tradutor entrega — ver `bahrd_webhook._telefone`.
    monkeypatch.setenv("TWILIO_NUMEROS_DE_TESTE", "+5541999999999")
    settings.cache_clear()
    cliente = TestClient(criar_app())
    yield cliente
    settings.cache_clear()


@pytest.fixture
def trancado(monkeypatch) -> TestClient:
    """Com segredo — é o estado do dia em que a TI combinar a chave.

    ⚠️ **A lista de destinos passou a ser declarada aqui em 03/09/2026.** Antes
    não era, porque o segredo desligava a lista. Hoje ela vale fora de produção
    com assinatura ou sem, e sem declarar a lista este fixture herdaria o que
    estivesse no ambiente de quem roda: os testes de assinatura passariam a
    devolver `destino_nao_autorizado` e continuariam verdes, porque a rota
    responde 200 nos dois casos. Verde pelo motivo errado é pior que vermelho.
    """
    monkeypatch.setenv("BAHRD_WEBHOOK_HMAC_SECRET", SEGREDO)
    monkeypatch.setenv("TWILIO_NUMEROS_DE_TESTE", "+5541999999999")
    settings.cache_clear()
    cliente = TestClient(criar_app())
    yield cliente
    settings.cache_clear()


@pytest.fixture
def trancado_sem_lista(monkeypatch) -> TestClient:
    """Com segredo e **sem** destino autorizado: a configuração de 02/09/2026.

    Era exatamente esta a situação do `.env` até a correção: segredo preenchido
    com o placeholder versionado, lista de destinos vazia. A rota aceitava a
    assinatura e escrevia para qualquer celular que viesse no corpo.
    """
    monkeypatch.setenv("BAHRD_WEBHOOK_HMAC_SECRET", SEGREDO)
    monkeypatch.setenv("TWILIO_NUMEROS_DE_TESTE", "")
    settings.cache_clear()
    cliente = TestClient(criar_app())
    yield cliente
    settings.cache_clear()


def _post(cliente: TestClient, payload: dict | None = None, **kwargs):
    corpo = payload if payload is not None else PAYLOAD
    return cliente.post("/eventos/link", json=corpo, **kwargs)


def _assinado(cliente: TestClient, payload: dict | None = None):
    """POST com assinatura válida, calculada sobre o corpo exato enviado."""
    corpo = json.dumps(payload if payload is not None else PAYLOAD).encode()
    mac = hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
    return cliente.post(
        "/eventos/link",
        content=corpo,
        headers={"Content-Type": "application/json", "X-Assinatura": f"sha256={mac}"},
    )


# ─────────────────────────────── contrato ───────────────────────────────


def test_payload_valido_devolve_200(aberto: TestClient) -> None:
    assert _post(aberto).status_code == 200


def test_devolve_o_id_do_evento(aberto: TestClient) -> None:
    """A Bahrd precisa correlacionar o que mandou com o que tratamos."""
    assert _post(aberto).json().get("evento_id")


def test_campo_obrigatorio_ausente_devolve_422(aberto: TestClient) -> None:
    """422 e não 500: o problema é o conteúdo, e eles precisam saber."""
    payload = {c: v for c, v in PAYLOAD.items() if c != "tipo_evento"}

    assert _post(aberto, payload).status_code == 422


def test_corpo_que_nao_e_json_devolve_422(aberto: TestClient) -> None:
    resposta = aberto.post(
        "/eventos/link",
        content=b"isto nao e json",
        headers={"Content-Type": "application/json"},
    )

    assert resposta.status_code == 422


# ─────────────────────── o que NÃO vira atendimento ───────────────────────


def test_evento_fora_do_catalogo_nao_vira_atendimento(aberto: TestClient) -> None:
    """Desconhecido é humano por omissão — a regra do pipeline, repetida aqui."""
    resposta = _post(aberto, {**PAYLOAD, "tipo_evento": "Coisa inventada ontem"})

    assert resposta.status_code == 200
    assert resposta.json()["atendido"] is False
    assert resposta.json()["motivo"] == "fora_do_catalogo"


def test_sem_telefone_nao_abre_ocorrencia(aberto: TestClient) -> None:
    """Ocorrência sem para quem escrever nasce órfã. Melhor registrar e parar."""
    resposta = _post(aberto, {**PAYLOAD, "contato_telefone": ""})

    assert resposta.json()["motivo"] == "sem_telefone"


def test_telefone_invalido_conta_como_sem_telefone(aberto: TestClient) -> None:
    """`123` vira `None` no tradutor — e `None` não vira mensagem para ninguém."""
    resposta = _post(aberto, {**PAYLOAD, "contato_telefone": "123"})

    assert resposta.json()["motivo"] == "sem_telefone"


# ─────────────────────────────── assinatura ───────────────────────────────


def test_sem_segredo_configurado_aceita(aberto: TestClient) -> None:
    """É o que permite testar com Postman antes de a TI definir a chave.

    O endpoint avisa no log — e o aviso é o que impede isso de chegar em
    produção sem ninguém notar.
    """
    assert _post(aberto).status_code == 200


def test_com_segredo_sem_cabecalho_recusa(trancado: TestClient) -> None:
    assert _post(trancado).status_code == 403


def test_com_segredo_e_assinatura_valida_aceita(trancado: TestClient) -> None:
    """200 **e** passou da porta do destino.

    Só o status não prova nada aqui: a rota devolve 200 tanto para o evento
    atendido quanto para o recusado por destino. Sem a segunda asserção, este
    teste continuaria verde no dia em que a lista de autorizados voltasse a
    barrar tudo.
    """
    resposta = _assinado(trancado)

    assert resposta.status_code == 200
    assert resposta.json().get("motivo") != "destino_nao_autorizado"


# ─────────────────── para quem a IA pode escrever ───────────────────
#
# ⚠️ **Corrigido em 03/09/2026.** A trava era `if segredo is None and not
# numero_autorizado(...)`: a lista de destinos só valia enquanto NÃO houvesse
# segredo, pelo raciocínio de que a assinatura já provava quem chamava. Só que
# o segredo em uso era `dev-hmac-nao-usar-em-producao`, versionado no
# `.env.example` desde d62f5b1 — qualquer pessoa com leitura do repositório
# assinava um POST válido e fazia o número oficial verificado da Bahrd mandar
# template de pânico para o celular que quisesse.
#
# O efeito perverso: preencher o segredo, que é a coisa certa a fazer,
# DESLIGAVA a única proteção que restava. A configuração preenchida era mais
# frouxa que a vazia.
#
# Agora quem decide é o ambiente. Estes quatro testes são a trava.


def test_destino_fora_da_lista_nao_recebe_mesmo_com_assinatura_valida(
    trancado: TestClient,
) -> None:
    """O teste que teria pego o buraco. Assinatura boa não é permissão de destino."""
    resposta = _assinado(trancado, {**PAYLOAD, "contato_telefone": "41988887777"})

    assert resposta.status_code == 200
    assert resposta.json()["atendido"] is False
    assert resposta.json()["motivo"] == "destino_nao_autorizado"


def test_lista_vazia_recusa_todo_mundo(trancado_sem_lista: TestClient) -> None:
    """Falha fechada: em teste, não escrever para ninguém é o erro barato."""
    assert _assinado(trancado_sem_lista).json()["motivo"] == "destino_nao_autorizado"


def test_a_grafia_do_numero_nao_derruba_o_autorizado(trancado: TestClient) -> None:
    """A lista traz `+5541999999999`; o payload manda sem `+55` e sem o nono.

    Reaproveita `variantes_do_numero`, e existe porque o mesmo erro já custou
    meia hora em 25/08/2026 — com a trava valendo sempre, ele voltaria a doer.
    """
    resposta = _assinado(trancado, {**PAYLOAD, "contato_telefone": "4199999999"})

    assert resposta.json().get("motivo") != "destino_nao_autorizado"


def test_em_producao_a_lista_nao_vale(monkeypatch) -> None:
    """⛔ A trava é de desenvolvimento, e some quando o cliente é real.

    Em produção a IA precisa escrever para quem o evento indicar. Deixar a
    lista valendo lá transformaria a proteção numa recusa de atendimento — o
    contrário do que ela existe para fazer.
    """
    monkeypatch.setenv("APP_ENV", "prd-poc")
    monkeypatch.setenv("BAHRD_WEBHOOK_HMAC_SECRET", SEGREDO)
    monkeypatch.setenv("TWILIO_NUMEROS_DE_TESTE", "")
    settings.cache_clear()
    try:
        cliente = TestClient(criar_app())
        resposta = _assinado(cliente, {**PAYLOAD, "contato_telefone": "41988887777"})

        assert resposta.json().get("motivo") != "destino_nao_autorizado"
    finally:
        settings.cache_clear()


def test_com_segredo_e_assinatura_errada_recusa(trancado: TestClient) -> None:
    resposta = trancado.post(
        "/eventos/link",
        content=json.dumps(PAYLOAD).encode(),
        headers={"Content-Type": "application/json", "X-Assinatura": "sha256=" + "0" * 64},
    )

    assert resposta.status_code == 403


def test_assinatura_confere_sobre_o_corpo_bruto() -> None:
    corpo = json.dumps(PAYLOAD).encode()
    mac = hmac.new(b"segredo", corpo, hashlib.sha256).hexdigest()

    assert assinatura_confere("segredo", corpo, mac)
    assert assinatura_confere("segredo", corpo, f"sha256={mac}")


def test_reserializar_o_json_invalida_a_assinatura() -> None:
    """O corpo tem de ser o que chegou — um byte a mais derruba o HMAC."""
    corpo = b'{"a":1}'
    mac = hmac.new(b"segredo", corpo, hashlib.sha256).hexdigest()
    reserializado = json.dumps(json.loads(corpo)).encode()

    assert reserializado != corpo
    assert not assinatura_confere("segredo", reserializado, mac)


@pytest.mark.parametrize("enviada", ["", "sha256=", "abc", "sha256=naohex"])
def test_assinatura_malformada_nao_passa(enviada: str) -> None:
    assert not assinatura_confere("segredo", json.dumps(PAYLOAD).encode(), enviada)


# ─────────────────────────── resiliência do canal ───────────────────────────


def test_erro_interno_nao_vira_5xx(aberto: TestClient, monkeypatch) -> None:
    """A regra mais importante desta rota.

    Se a IA, o LLM ou a rede falharem, a Bahrd não pode receber 5xx — senão ela
    marca o nosso endpoint como quebrado e para de entregar. Perder o canal é
    pior que perder um evento.
    """
    import central_ia.api.rotas.eventos as rota

    async def explode(*_a, **_k):
        raise RuntimeError("o LLM caiu")

    monkeypatch.setattr(rota, "_atender", explode)
    resposta = _post(aberto)

    assert resposta.status_code == 200
    assert resposta.json()["motivo"] == "erro_interno"


def test_a_rota_esta_registrada() -> None:
    """Guarda contra alguém remover o `include_router` sem perceber.

    Pelo `openapi()`, não por `app.routes`: nesta versão do FastAPI os routers
    incluídos ficam como `_IncludedRouter`, **sem atributo `path`** — varrer
    `routes` devolve vazio e o teste passaria a mentir.
    """
    assert "/eventos/link" in criar_app().openapi()["paths"]


def test_corpo_em_latin1_devolve_422_e_nao_500(aberto: TestClient) -> None:
    """Bug real, 24/08/2026.

    `json.loads` sobre bytes decodifica como UTF-8 **antes** de olhar a
    sintaxe. Payload em latin-1 — que muitos sistemas no Brasil ainda mandam —
    levanta `UnicodeDecodeError`, não `JSONDecodeError`. Sem capturar as duas,
    um "Veículo" com acento errado virava **500**, e 500 faz quem dispara
    marcar o endpoint como quebrado.
    """
    corpo = json.dumps(PAYLOAD, ensure_ascii=False).encode("latin-1")
    resposta = aberto.post(
        "/eventos/link",
        content=corpo,
        headers={"Content-Type": "application/json"},
    )

    assert resposta.status_code == 422
    assert resposta.status_code < 500


# ────────────────── trava de destino, fora de produção ──────────────────


def test_sem_assinatura_so_escreve_para_numero_autorizado(aberto, monkeypatch) -> None:
    """A rota é pública pelo túnel.

    Sem assinatura **e** sem esta trava, quem descobrisse a URL faria a IA
    mandar mensagem — pelo número oficial da Bahrd — para qualquer celular do
    Brasil.
    """
    monkeypatch.setenv("TWILIO_NUMEROS_DE_TESTE", "554199999999")
    settings.cache_clear()
    cliente = TestClient(criar_app())

    resposta = cliente.post(
        "/eventos/link", json={**PAYLOAD, "contato_telefone": "5511988887777"}
    )

    assert resposta.json()["motivo"] == "destino_nao_autorizado"
    settings.cache_clear()


def test_a_assinatura_nao_tira_a_trava_do_destino(trancado: TestClient) -> None:
    """⚠️ **Este teste dizia o contrário até 03/09/2026, e era ele o buraco.**

    Chamava-se `test_com_assinatura_a_trava_sai` e afirmava: *"quem assinou já
    provou que é a Bahrd, e em produção a IA precisa falar com o cliente de
    verdade, que nunca vai estar numa lista nossa"*.

    As duas metades são verdadeiras e a conclusão não segue delas. A segunda
    metade fala de **produção**, e é lá que ela vale, coberta por
    `test_em_producao_a_lista_nao_vale`. A primeira presume que a assinatura
    identifica a Bahrd, e enquanto o segredo é o `dev-hmac-nao-usar-em-producao`
    versionado no `.env.example`, ela identifica qualquer pessoa com leitura do
    repositório. Amarrar a trava à assinatura fazia a proteção sumir justamente
    quando alguém configurava o segredo, que é a coisa certa a fazer.

    Quem decide agora é o ambiente, não o cabeçalho.
    """
    corpo = json.dumps({**PAYLOAD, "contato_telefone": "5511988887777"}).encode()
    mac = hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
    resposta = trancado.post(
        "/eventos/link",
        content=corpo,
        headers={"Content-Type": "application/json", "X-Assinatura": f"sha256={mac}"},
    )

    assert resposta.json()["motivo"] == "destino_nao_autorizado"
