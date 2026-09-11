"""A rota que a tela de eventos de teste chama.

O que estes testes guardam é o contrato com quem **não é programador**: alguém
da Central abre a tela, escolhe um dos três eventos e aperta enviar. Se algo
barrar, a resposta precisa dizer o quê e o que fazer, em português.

E guardam as travas, que aqui valem mais que em qualquer outra rota: esta é a
única em que o destino de uma mensagem é escolhido por uma pessoa, e não por um
evento de veículo.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from central_ia.api.main import criar_app
from central_ia.api.rotas import eventos_de_teste
from central_ia.api.rotas.eventos import ResultadoDoEvento
from central_ia.config import settings
from central_ia.domain import eventos

DESTINO = "+5541999999999"

#: Os nomes exatos das abas do painel, como `web/src/App.tsx` os escreve.
#:
#: Escrito aqui à mão de propósito: se a aba for renomeada no front e a
#: descrição do evento não acompanhar, o teste quebra e alguém conserta os dois.
#: É o tipo de divergência que passa despercebida por meses.
ABAS_DO_PAINEL = {"Atendimento por IA", "Atendimento humano", "Encerrados"}


def _cliente(monkeypatch, **extra: str) -> TestClient:
    monkeypatch.setenv("PAINEL_TESTES_ATIVO", "true")
    monkeypatch.delenv("PAINEL_TOKEN", raising=False)
    for chave, valor in extra.items():
        monkeypatch.setenv(chave, valor)
    settings.cache_clear()
    return TestClient(criar_app())


@pytest.fixture
def cliente(monkeypatch) -> TestClient:
    c = _cliente(monkeypatch)
    yield c
    settings.cache_clear()


@pytest.fixture
def sem_disparar(monkeypatch) -> list[dict]:
    """Captura o payload sem mandar WhatsApp nenhum.

    O que estes testes precisam ver é o que a rota **monta**, e montar é a parte
    que ela faz sozinha. Deixar o fluxo real rodar aqui testaria a Meta.
    """
    montados: list[dict] = []

    async def fingir(cfg, payload, origem="link"):
        montados.append(payload)
        return ResultadoDoEvento(200, {"atendido": True, "evento_id": "ev-123"})

    monkeypatch.setattr(eventos_de_teste, "processar_evento_link", fingir)
    return montados


# ─────────────────────────────── as travas ───────────────────────────────


def test_desligada_a_rota_nao_existe(monkeypatch) -> None:
    """⛔ 404 e não 403.

    403 confirma que a rota existe, e com `APP_ENV=dev` o `/openapi.json` está
    público: quem varre a API acharia o caminho e saberia o que procurar. 404
    não conta nada.
    """
    monkeypatch.setenv("PAINEL_TESTES_ATIVO", "false")
    monkeypatch.delenv("PAINEL_TOKEN", raising=False)
    settings.cache_clear()
    try:
        c = TestClient(criar_app())

        assert c.get("/painel/testes/catalogo").status_code == 404
        assert c.post("/painel/testes/evento", json={
            "tipo": "PANICO", "telefone": DESTINO
        }).status_code == 404
    finally:
        settings.cache_clear()


@pytest.mark.parametrize("ambiente", ["hml", "prd-poc"])
def test_em_producao_a_tela_nao_existe(monkeypatch, ambiente: str) -> None:
    """A variável ligada não vence o ambiente. Testado aqui, na porta, e não só
    no `Settings`: é aqui que a decisão vira ou não uma mensagem para alguém."""
    c = _cliente(monkeypatch, APP_ENV=ambiente)
    try:
        assert c.get("/painel/testes/catalogo").status_code == 404
    finally:
        settings.cache_clear()


@pytest.mark.parametrize(
    "torto",
    ["", "419999", "4199999888899", "abc", "+1 415 555 0100"],
)
def test_numero_torto_nao_passa(cliente: TestClient, sem_disparar, torto: str) -> None:
    """⚠️ Conferido **no servidor**, não só na tela.

    A validação do formulário é conveniência para quem digita. Quem chama a rota
    por fora não passa por ela, e sem esta conferência o número inválido só
    apareceria lá na frente como `sem_telefone`, sem dizer o que houve.
    """
    resposta = cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": torto}
    )

    assert resposta.status_code == 422
    assert sem_disparar == [], "recusou antes de chamar o fluxo"


@pytest.mark.parametrize(
    "grafia",
    ["41999998888", "+5541999998888", "(41) 99999-8888", "554199999888"],
)
def test_qualquer_grafia_de_celular_brasileiro_passa(
    cliente: TestClient, sem_disparar, grafia: str
) -> None:
    """⛔ A lista fechada de destinos saiu em 03/09/2026, por decisão da operação.

    A Central precisa testar com o celular de quem estiver na sala, e a lista
    obrigava a chamar o dev para cadastrar cada número novo. O que se perdeu:
    quem tem o token do painel pode fazer a IA escrever para qualquer celular do
    Brasil. A validação pega o dígito **faltando**, não o dígito **trocado**.
    """
    resposta = cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": grafia}
    )

    assert resposta.status_code == 200
    assert len(sem_disparar) == 1


def test_tipo_fora_dos_tres_nem_chega_na_rota(cliente: TestClient) -> None:
    """O `Literal` barra no Pydantic. A tela não é um "mande qualquer coisa"."""
    resposta = cliente.post(
        "/painel/testes/evento",
        json={"tipo": "ROUBO_ATIVO_MOVIMENTO", "telefone": DESTINO},
    )

    assert resposta.status_code == 422


def test_teto_diario_e_rigido(cliente: TestClient, sem_disparar, monkeypatch) -> None:
    """⚠️ Aqui o princípio do resto do sistema se inverte.

    O `SECURITY.md` diz "alerta, nunca teto", porque teto no caminho de
    atendimento vira cliente real sem resposta. Um teste bloqueado não custa
    nada a ninguém, então aqui é teto mesmo.
    """
    monkeypatch.setattr(eventos_de_teste, "TETO_POR_DIA", 2)
    monkeypatch.setattr(eventos_de_teste, "_disparos", [])
    corpo = {"tipo": "REMOCAO_BATERIA", "telefone": DESTINO}

    assert cliente.post("/painel/testes/evento", json=corpo).status_code == 200
    assert cliente.post("/painel/testes/evento", json=corpo).status_code == 200
    estourou = cliente.post("/painel/testes/evento", json=corpo)

    assert estourou.status_code == 429
    assert "meia-noite" in estourou.json()["detail"]


# ─────────────────────────── o payload montado ───────────────────────────


def test_o_rotulo_vem_do_catalogo_e_nao_de_uma_copia(
    cliente: TestClient, sem_disparar
) -> None:
    """⛔ O parser casa `tipo_evento` por igualdade exata contra o rótulo.

    Um acento a menos numa string copiada à mão devolveria `fora_do_catalogo`
    sem dizer por quê, e alguém passaria a tarde procurando no lugar errado.
    """
    cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    )

    assert sem_disparar[0]["tipo_evento"] == eventos.PANICO.rotulo
    assert sem_disparar[0]["tipo_evento"] == "Pânico"


def test_cada_disparo_tem_id_proprio(cliente: TestClient, sem_disparar) -> None:
    """⚠️ É isto que faz apertar o botão duas vezes seguidas funcionar.

    Sem `id`, o fluxo derivaria a chave de `sha256(veiculo|rotulo|momento)`, e
    como a placa e o tipo são os mesmos e o horário é sempre agora, dois cliques
    no mesmo segundo viriam como `duplicado` por 6 horas. Quem estivesse testando
    leria isso como defeito da IA, não como idempotência.
    """
    corpo = {"tipo": "REMOCAO_BATERIA", "telefone": DESTINO}
    cliente.post("/painel/testes/evento", json=corpo)
    cliente.post("/painel/testes/evento", json=corpo)

    assert sem_disparar[0]["id"] != sem_disparar[1]["id"]
    assert all(p["id"].startswith("teste-") for p in sem_disparar)


def test_o_horario_e_sempre_agora_e_nao_se_escolhe(
    cliente: TestClient, sem_disparar
) -> None:
    """⚠️ **O campo de data e hora saiu da tela em 03/09/2026.**

    Existia para reproduzir um evento com horário específico, e cobrava três
    formas de errar: formato fora do que o parser aceita, fuso trocado, e data no
    passado num evento que a tela apresenta como acontecendo agora. Ninguém
    tinha o caso de uso.

    A rota nem aceita mais o campo, e é isso que este teste crava: mandar
    `momento` não muda nada, em vez de mudar em silêncio.
    """
    cliente.post(
        "/painel/testes/evento",
        json={
            "tipo": "PANICO",
            "telefone": DESTINO,
            "momento": "2020-01-01 03:00:00",
        },
    )

    enviado = sem_disparar[0]["data_hora_evento"]
    assert not enviado.startswith("2020"), "o horário pedido foi ignorado"

    # Levanta se o formato divergir do que `parse_evento_webhook` espera.
    from datetime import datetime

    datetime.strptime(enviado, "%Y-%m-%d %H:%M:%S")


def test_campo_opcional_vazio_nao_entra_no_payload(
    cliente: TestClient, sem_disparar
) -> None:
    """Chave presente com valor vazio é diferente de chave ausente.

    `_OBRIGATORIOS` é checado por truthiness, e o resto do parser trata ausência
    e vazio de formas diferentes. Mandar `"contato_nome": ""` fingiria que a
    Central informou um nome em branco.
    """
    cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    )

    assert "contato_nome" not in sem_disparar[0]

    # ⚠️ `latitude` e `endereco` estavam nesta lista e saíram em 03/09/2026. São
    # as exceções deliberadas: ganharam padrão porque a Bahrd manda os dois em
    # evento real, e sem eles o teste exercitava a reserva de texto e escondia o
    # `Local:`. Ver `test_todo_disparo_leva_coordenada` e `test_o_local_mostra_o
    # _endereco`.
    assert "latitude" in sem_disparar[0]
    assert "endereco" in sem_disparar[0]


# ─────────────────────────────── o recibo ───────────────────────────────


def test_o_recibo_explica_a_recusa_em_portugues(cliente: TestClient, monkeypatch) -> None:
    """⚠️ É metade do valor da tela.

    Oito desfechos do fluxo só existiam no log, e do lado de fora "não aconteceu
    nada" era indistinguível de "o WhatsApp está lento". Quem testa sem saber
    por que falhou volta a perguntar ao dev, que é o que a tela evita.
    """
    async def duplicado(cfg, payload, origem="link"):
        return ResultadoDoEvento(200, {"atendido": False, "motivo": "duplicado"})

    monkeypatch.setattr(eventos_de_teste, "processar_evento_link", duplicado)
    corpo = cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    ).json()

    assert corpo["aceito"] is False
    assert corpo["motivo"] == "duplicado"
    assert "sem preencher a data" in corpo["resumo"]


def test_motivo_desconhecido_nao_vira_silencio(cliente: TestClient, monkeypatch) -> None:
    """⛔ Um motivo novo no fluxo não pode virar recibo em branco.

    O dicionário de traduções vai ficar velho: alguém acrescenta uma recusa em
    `processar_evento_link` e esquece daqui. O texto padrão diz que a falha é
    nossa em vez de deixar a Central achando que fez algo errado.
    """
    async def novidade(cfg, payload, origem="link"):
        return ResultadoDoEvento(200, {"atendido": False, "motivo": "motivo_novo"})

    monkeypatch.setattr(eventos_de_teste, "processar_evento_link", novidade)
    corpo = cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    ).json()

    assert "defeito nosso" in corpo["resumo"]


def test_o_recibo_devolve_o_payload_montado(cliente: TestClient, sem_disparar) -> None:
    """A Central aprende o formato sozinha e para de perguntar como se monta."""
    corpo = cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    ).json()

    assert corpo["payload"]["tipo_evento"] == "Pânico"
    assert corpo["payload"]["contato_telefone"] == DESTINO


def test_o_recibo_leva_a_ocorrencia(cliente: TestClient, monkeypatch) -> None:
    """Sem isto o recibo diz "deu certo" e deixa a pessoa procurar na fila."""
    class SessaoFalsa:
        ocorrencia_id = "OC-2026-09-03-AAAA-WA"

    async def atendeu(cfg, payload, origem="link"):
        return ResultadoDoEvento(
            200, {"atendido": True, "evento_id": "ev-1"}, sessao=SessaoFalsa()
        )

    monkeypatch.setattr(eventos_de_teste, "processar_evento_link", atendeu)
    corpo = cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    ).json()

    assert corpo["aceito"] is True
    assert corpo["ocorrencia_id"] == "OC-2026-09-03-AAAA-WA"


# ─────────────────────────────── o catálogo ───────────────────────────────


def test_catalogo_traz_os_tres_com_rotulo_do_dominio(cliente: TestClient) -> None:
    corpo = cliente.get("/painel/testes/catalogo").json()

    assert [e["codigo"] for e in corpo["eventos"]] == [
        "REMOCAO_BATERIA",
        "MOVIMENTO_SEM_IGNICAO",
        "PANICO",
    ]
    assert [e["rotulo"] for e in corpo["eventos"]] == [
        eventos.REMOCAO_BATERIA.rotulo,
        eventos.MOVIMENTO_SEM_IGNICAO.rotulo,
        eventos.PANICO.rotulo,
    ]


def test_catalogo_mostra_o_orcamento_do_dia(cliente: TestClient) -> None:
    """Quem testa vê quanto já usou, e para de perguntar se pode mandar mais."""
    corpo = cliente.get("/painel/testes/catalogo").json()

    assert corpo["teto_por_dia"] == eventos_de_teste.TETO_POR_DIA
    assert corpo["usados_hoje"] >= 0


# ─────────────── as abas vêm marcadas para a tela destacar ───────────────


def test_a_descricao_marca_as_abas_entre_aspas_angulares(cliente: TestClient) -> None:
    """⚠️ O `«»` é contrato com o front, não enfeite de texto.

    A tela pinta de outra cor o que estiver entre eles, para "Encerrados" no
    meio de um parágrafo não ser indistinguível de uma palavra qualquer — e é
    justamente essa a informação que a pessoa leva para procurar o teste depois.

    A marca nasce **aqui**, junto de quem sabe para onde o evento vai. Se o
    front procurasse os nomes por texto, o destaque sumiria calado no dia em que
    uma aba fosse renomeada.
    """
    eventos_ = cliente.get("/painel/testes/catalogo").json()["eventos"]

    for evento in eventos_:
        marcadas = re.findall(r"«([^»]+)»", evento["descricao"])
        assert marcadas, f"{evento['codigo']} não diz em qual aba olhar"
        assert all(m in ABAS_DO_PAINEL for m in marcadas), (
            f"{evento['codigo']} cita aba que não existe: {marcadas}"
        )


def test_todo_evento_diz_pelo_menos_uma_aba(cliente: TestClient) -> None:
    """Quem dispara e não sabe onde olhar conclui que o teste falhou."""
    eventos_ = cliente.get("/painel/testes/catalogo").json()["eventos"]

    assert len(eventos_) == 3
    assert all("«" in e["descricao"] for e in eventos_)


def test_o_recibo_leva_nome_e_placa(cliente: TestClient, sem_disparar) -> None:
    """O histórico da tela precisa distinguir um envio do outro.

    Numa bateria de teste o telefone é sempre o mesmo, então nome e placa são
    o par que diz qual disparo é qual. Estavam só dentro do `payload`, que fica
    escondido atrás do «Ver o JSON».
    """
    corpo = cliente.post(
        "/painel/testes/evento",
        json={
            "tipo": "PANICO",
            "telefone": DESTINO,
            "nome": "Arthur",
            "placa": "XYZ9K88",
        },
    ).json()

    assert corpo["nome"] == "Arthur"
    assert corpo["placa"] == "XYZ9K88"


def test_nome_em_branco_volta_vazio_e_nao_nulo(cliente: TestClient, sem_disparar) -> None:
    """⚠️ `""` e não `None`: a tela testa com `recibo.nome &&`.

    `null` funcionaria em JavaScript, mas o campo é declarado `str` no contrato
    e um `None` ali obrigaria o tipo TypeScript a virar `string | null` só por
    causa de um caso que a rota controla.
    """
    corpo = cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    ).json()

    assert corpo["nome"] == ""


# ─────────────────── o mapa, que faltava sem ninguém ver ───────────────────


def test_todo_disparo_leva_coordenada(cliente: TestClient, sem_disparar) -> None:
    """⛔ **O defeito que passou por cinco disparos sem sintoma visível.**

    A tela nunca mandava latitude e longitude. `localizacao_do_evento` devolvia
    `None`, o `evento_alerta_mapa` nem chegava a ser tentado, e o cliente recebia
    a notificação sem o cartão de mapa. Nada no log parecia errado: só um
    `com_mapa=false` que era exatamente o que o código mandava fazer.

    ⚠️ E o pior não era o mapa faltando, era a tela **exercitar o caminho
    errado**. Em produção a Bahrd manda coordenada sempre; quem vem vazio é o
    `Endereço` (doc 14 §5). Sem coordenada, o teste validava a reserva de texto
    e dava por bom um fluxo que não é o que roda.
    """
    cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    )

    assert "latitude" in sem_disparar[0], "sem isto o cliente não recebe o mapa"
    assert "longitude" in sem_disparar[0]


def test_a_coordenada_informada_vence_o_padrao(cliente: TestClient, sem_disparar) -> None:
    """O padrão é conveniência, não imposição: quem manda um ponto usa o dele."""
    cliente.post(
        "/painel/testes/evento",
        json={
            "tipo": "PANICO",
            "telefone": DESTINO,
            "latitude": -23.5,
            "longitude": -46.6,
        },
    )

    assert sem_disparar[0]["latitude"] == -23.5
    assert sem_disparar[0]["longitude"] == -46.6


def test_a_coordenada_padrao_monta_um_mapa_valido(cliente: TestClient, sem_disparar) -> None:
    """⚠️ Coordenada que o `localizacao_do_evento` recuse não serve de padrão.

    Ele devolve `None` para lat/lon ausentes, e `None` é justamente o sinal para
    não tentar o modelo com mapa. Um padrão inválido daria o mesmo resultado de
    não ter padrão nenhum, com a diferença de parecer resolvido.
    """
    from central_ia.api.rotas.eventos import localizacao_do_evento
    from central_ia.integrations.rastreamento.bahrd_webhook import parse_evento_webhook

    cliente.post(
        "/painel/testes/evento", json={"tipo": "PANICO", "telefone": DESTINO}
    )
    evento = parse_evento_webhook(sem_disparar[0])

    assert localizacao_do_evento(evento) is not None, "o cartão de mapa monta"


def test_o_local_mostra_o_endereco_e_nao_o_ponteiro(cliente: TestClient, sem_disparar) -> None:
    """⛔ **O `Local:` saía como "veja o mapa acima".**

    Com o cartão de mapa junto e sem `endereco`, `templates_do_evento` aponta
    para o cartão em vez de mostrar coordenada crua a um motorista. Faz sentido
    em produção e, no teste, escondia justamente o campo que se quer conferir:
    quem disparava não via como o endereço fica na mensagem.

    ⚠️ O padrão some sozinho quando o rastreador mandar o logradouro, porque a
    cascata usa `evento.endereco` primeiro.
    """
    from central_ia.api.rotas.eventos import templates_do_evento
    from central_ia.domain import eventos as dom
    from central_ia.integrations.rastreamento.bahrd_webhook import parse_evento_webhook

    # ⚠️ Não é o pânico: desde 10/09/2026 ele usa modelo próprio, que não tem
    # linha `Local:` nem cartão. Quem carrega o endereço é o alerta genérico.
    cliente.post(
        "/painel/testes/evento", json={"tipo": "REMOCAO_BATERIA", "telefone": DESTINO}
    )
    evento = parse_evento_webhook(sem_disparar[0])
    nome, parametros, mapa = templates_do_evento(dom.REMOCAO_BATERIA, evento)[0]

    assert mapa is not None, "o cartão de mapa vai junto"
    assert any("Curitiba" in p for p in parametros), "o Local mostra o endereço"
    assert mapa["address"] in parametros, "e é o mesmo texto do cartão"


def test_o_endereco_informado_vence_o_padrao(cliente: TestClient, sem_disparar) -> None:
    """O padrão é conveniência. Quem informa um logradouro usa o dele."""
    cliente.post(
        "/painel/testes/evento",
        json={
            "tipo": "PANICO",
            "telefone": DESTINO,
            "endereco": "Rodovia Régis Bittencourt, Juquitiba - SP",
        },
    )

    assert sem_disparar[0]["endereco"] == "Rodovia Régis Bittencourt, Juquitiba - SP"
