"""O login do painel: dois perfis, usuários na configuração, sessão no Redis.

Fecha a lacuna 12 da auditoria. O que estes testes guardam é que o login é
**do servidor**: cada rota do painel confere a sessão, e a tela esconder um
botão do operador não é o que impede o operador de usar a função.

Sem Redis de verdade: o falso abaixo segue o padrão de `test_alertas.py`, com
o mínimo que o login usa, e guarda o TTL de cada chave para o teste conferir o
prazo da sessão.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from central_ia.api import seguranca, sessoes_do_painel
from central_ia.api.main import criar_app
from central_ia.api.rotas import (
    eventos,
    eventos_de_teste,
    midia,
    painel,
    saude,
    sessao,
    whatsapp,
)
from central_ia.api.rotas.eventos import ResultadoDoEvento
from central_ia.config import Settings, settings
from central_ia.persistence import redis_bus, sessoes_redis
from central_ia.senhas import (
    UsuariosDoPainelInvalidos,
    carregar_usuarios,
    gerar_hash,
    verificar_senha,
)

SENHA_ADMIN = "senha-da-ana-123"
SENHA_OPERADOR = "senha-do-beto-456"

#: Gerados uma vez: cada scrypt custa dezenas de milissegundos, e a suíte não
#: precisa pagar isso a cada teste.
HASH_ADMIN = gerar_hash(SENHA_ADMIN)
HASH_OPERADOR = gerar_hash(SENHA_OPERADOR)
USUARIOS = f"ana:admin:{HASH_ADMIN};beto:operador:{HASH_OPERADOR}"


# ─────────────────────────────── Redis falso ───────────────────────────────


class _PipelineFalso:
    def __init__(self, dono: _RedisFalso) -> None:
        self._dono = dono
        self._comandos: list[tuple] = []

    def incr(self, chave: str) -> _PipelineFalso:
        self._comandos.append(("incr", chave))
        return self

    def expire(self, chave: str, segundos: int, nx: bool = False) -> _PipelineFalso:
        self._comandos.append(("expire", chave, segundos, nx))
        return self

    async def execute(self) -> None:
        for comando in self._comandos:
            if comando[0] == "incr":
                await self._dono.incr(comando[1])
            else:
                _, chave, segundos, nx = comando
                if not (nx and chave in self._dono.ttls):
                    self._dono.ttls[chave] = segundos


class _RedisFalso:
    def __init__(self) -> None:
        self.dados: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fora_do_ar = False

    def _conferir(self) -> None:
        if self.fora_do_ar:
            raise RedisConnectionError("redis fora do ar (teste)")

    def pipeline(self) -> _PipelineFalso:
        self._conferir()
        return _PipelineFalso(self)

    async def get(self, chave: str) -> str | None:
        self._conferir()
        return self.dados.get(chave)

    async def set(self, chave: str, valor: str, *, ex: int | None = None, nx: bool = False):
        self._conferir()
        if nx and chave in self.dados:
            return False
        self.dados[chave] = valor
        if ex is not None:
            self.ttls[chave] = ex
        return True

    async def delete(self, *chaves: str) -> int:
        self._conferir()
        apagadas = 0
        for chave in chaves:
            apagadas += chave in self.dados
            self.dados.pop(chave, None)
            self.ttls.pop(chave, None)
        return apagadas

    async def incr(self, chave: str) -> int:
        self._conferir()
        self.dados[chave] = str(int(self.dados.get(chave, 0)) + 1)
        return int(self.dados[chave])

    async def ttl(self, chave: str) -> int:
        self._conferir()
        return self.ttls.get(chave, -1) if chave in self.dados else -2

    def chaves_do_painel(self) -> list[str]:
        return [c for c in self.dados if c.startswith("painel:")]


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _RedisFalso:
    falso = _RedisFalso()
    monkeypatch.setattr(redis_bus, "cliente", lambda _cfg: falso)
    return falso


def _cliente(monkeypatch: pytest.MonkeyPatch, **ambiente: str) -> TestClient:
    monkeypatch.delenv("PAINEL_TOKEN", raising=False)
    monkeypatch.delenv("PAINEL_USUARIOS", raising=False)
    for chave, valor in ambiente.items():
        monkeypatch.setenv(chave, valor)
    settings.cache_clear()
    return TestClient(criar_app())


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch, redis: _RedisFalso) -> TestClient:
    return _cliente(monkeypatch, PAINEL_USUARIOS=USUARIOS, PAINEL_TESTES_ATIVO="true")


def _entrar(c: TestClient, usuario: str, senha: str, **cabecalhos: str):
    return c.post("/painel/sessao", json={"usuario": usuario, "senha": senha}, headers=cabecalhos)


def _token(resposta) -> str:
    return resposta.cookies[seguranca.COOKIE_SESSAO]


# ───────────────────────────────── o hash ──────────────────────────────────


def test_senha_certa_confere_e_errada_nao() -> None:
    assert verificar_senha(SENHA_ADMIN, HASH_ADMIN) is True
    assert verificar_senha("senha-da-ana-124", HASH_ADMIN) is False
    assert verificar_senha("", HASH_ADMIN) is False


def test_mesmo_texto_gera_hash_diferente() -> None:
    """Sal aleatório por usuário: duas pessoas com a mesma senha não se denunciam."""
    assert gerar_hash(SENHA_ADMIN) != gerar_hash(SENHA_ADMIN)


def test_o_hash_nao_tem_caractere_que_quebre_a_variavel() -> None:
    """`:` e `;` separam a entrada; `$` o docker compose interpola no `env_file`.

    Medido, não suposto: `scrypt$16384$8$1$abc$xyz` chegava ao contêiner como
    `scrypt$$16384$$8$$1`, com sal e hash trocados por vazio.
    """
    for proibido in (":", ";", "$", " ", "\"", "'"):
        assert proibido not in HASH_ADMIN
    assert HASH_ADMIN.startswith("scrypt.16384.8.1.")


@pytest.mark.parametrize(
    "torto",
    [
        "",
        "texto qualquer",
        "bcrypt.16384.8.1.abc.def",
        "scrypt.16384.8.1",
        "scrypt.x.8.1.AAAAAAAAAAAAAAAAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "scrypt.1024.8.1.AAAAAAAAAAAAAAAAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "scrypt.16384.8.1.!!!.???",
        "scrypt.16384.8.1.AAAA.AAAA",
    ],
)
def test_hash_malformado_nao_confere_nem_explode(torto: str) -> None:
    assert verificar_senha(SENHA_ADMIN, torto) is False


def test_carrega_os_dois_perfis() -> None:
    usuarios = carregar_usuarios(f" Ana :admin:{HASH_ADMIN} ; beto:operador:{HASH_OPERADOR};")
    assert {n: u.perfil for n, u in usuarios.items()} == {"ana": "admin", "beto": "operador"}


@pytest.mark.parametrize(
    ("entrada", "trecho"),
    [
        (f"ana:{HASH_ADMIN}", "três campos"),
        (f"ana:chefe:{HASH_ADMIN}", "perfil"),
        ("ana:admin:scrypt$16384$8$1$abc$xyz", "scrypt.N.r.p.sal.hash"),
        (f"ana:admin:{HASH_ADMIN};ana:operador:{HASH_OPERADOR}", "duas vezes"),
        (f"ana maria:admin:{HASH_ADMIN}", "usuário"),
        (f"ana:admin:{HASH_ADMIN.replace('16384', '1024', 1)}", "potência de 2"),
    ],
)
def test_entrada_malformada_derruba_a_partida_com_mensagem_clara(
    entrada: str, trecho: str
) -> None:
    with pytest.raises(UsuariosDoPainelInvalidos) as erro:
        Settings(painel_usuarios=entrada)

    mensagem = str(erro.value)
    assert "PAINEL_USUARIOS" in mensagem
    assert trecho in mensagem
    # A mensagem vai para o log de boot: nunca repete o hash.
    assert HASH_ADMIN not in mensagem and HASH_OPERADOR not in mensagem


def test_o_hash_nao_aparece_no_dump_da_configuracao() -> None:
    cfg = Settings(painel_usuarios=USUARIOS)
    assert HASH_ADMIN not in repr(cfg.model_dump())
    assert HASH_ADMIN not in repr(cfg)


# ───────────────────────────────── entrar ──────────────────────────────────


def test_login_certo_devolve_cookie_httponly_e_strict(cliente: TestClient) -> None:
    resposta = _entrar(cliente, "ana", SENHA_ADMIN)

    assert resposta.status_code == 204
    cookie = resposta.headers["set-cookie"]
    assert cookie.startswith(f"{seguranca.COOKIE_SESSAO}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert f"Max-Age={12 * 3600}" in cookie
    # A API local é HTTP: cookie `Secure` lá não seria guardado.
    assert "Secure" not in cookie


def test_atras_do_caddy_o_cookie_sai_secure(cliente: TestClient) -> None:
    resposta = _entrar(cliente, "ana", SENHA_ADMIN, **{"X-Forwarded-Proto": "https"})

    assert resposta.status_code == 204
    assert "Secure" in resposta.headers["set-cookie"]


def test_o_nome_nao_diferencia_maiuscula(cliente: TestClient) -> None:
    assert _entrar(cliente, "  ANA ", SENHA_ADMIN).status_code == 204
    assert cliente.get("/painel/sessao").json()["usuario"] == "ana"


def test_sessao_atual_diz_quem_e_e_o_perfil(cliente: TestClient) -> None:
    _entrar(cliente, "beto", SENHA_OPERADOR)

    resposta = cliente.get("/painel/sessao")

    assert resposta.status_code == 200
    assert resposta.json() == {"usuario": "beto", "perfil": "operador", "login_ativo": True}


def test_senha_errada_e_usuario_inexistente_respondem_igual(cliente: TestClient) -> None:
    """A mesma frase e o mesmo código. Diferenciar entregaria quem existe."""
    errada = _entrar(cliente, "ana", "senha-errada-000")
    inexistente = _entrar(cliente, "carla", "senha-errada-000")

    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json() == {"detail": "Usuário ou senha inválidos."}
    assert "set-cookie" not in errada.headers
    assert "set-cookie" not in inexistente.headers


def test_usuario_inexistente_paga_o_mesmo_scrypt(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem isto, "não existe" responderia na hora e "senha errada" depois de um
    scrypt inteiro, e o relógio diria quem existe."""
    conferidos: list[str] = []
    original = sessao.verificar_senha

    def espiar(senha: str, hash_senha: str) -> bool:
        conferidos.append(hash_senha)
        return original(senha, hash_senha)

    monkeypatch.setattr(sessao, "verificar_senha", espiar)

    _entrar(cliente, "carla", "qualquer-coisa-1")

    assert len(conferidos) == 1
    assert conferidos[0].startswith("scrypt.16384.8.1.")
    assert conferidos[0] not in (HASH_ADMIN, HASH_OPERADOR)


def test_comparacao_do_hash_e_resistente_a_tempo() -> None:
    import inspect

    from central_ia import senhas

    assert "compare_digest" in inspect.getsource(senhas.verificar_senha)


# ────────────────────────── limite de tentativas ───────────────────────────


def test_cinco_falhas_bloqueiam_ate_a_senha_certa(cliente: TestClient) -> None:
    for _ in range(sessoes_do_painel.MAXIMO_DE_FALHAS):
        assert _entrar(cliente, "ana", "senha-errada-000").status_code == 401

    bloqueado = _entrar(cliente, "ana", SENHA_ADMIN)

    assert bloqueado.status_code == 429
    assert bloqueado.json()["detail"] == "Muitas tentativas. Tente de novo em alguns minutos."
    assert int(bloqueado.headers["Retry-After"]) > 0
    assert "set-cookie" not in bloqueado.headers


def test_o_bloqueio_e_por_ip_e_usuario(cliente: TestClient) -> None:
    de_um_ip = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(sessoes_do_painel.MAXIMO_DE_FALHAS):
        _entrar(cliente, "ana", "senha-errada-000", **de_um_ip)

    assert _entrar(cliente, "ana", SENHA_ADMIN, **de_um_ip).status_code == 429
    # Outro IP, mesmo usuário: passa.
    outro_ip = {"X-Forwarded-For": "198.51.100.2"}
    assert _entrar(cliente, "ana", SENHA_ADMIN, **outro_ip).status_code == 204
    # Mesmo IP, outro usuário: passa.
    assert _entrar(cliente, "beto", SENHA_OPERADOR, **de_um_ip).status_code == 204


def test_o_ip_e_o_que_o_caddy_escreveu_por_ultimo(cliente: TestClient) -> None:
    """O primeiro valor de `X-Forwarded-For` vem de quem chama e pode ser
    inventado a cada tentativa; o último é o do proxy mais próximo."""
    for i in range(sessoes_do_painel.MAXIMO_DE_FALHAS):
        inventado = {"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"}
        _entrar(cliente, "ana", "senha-errada-000", **inventado)

    trocando_o_inicio = {"X-Forwarded-For": "10.9.9.9, 203.0.113.7"}
    assert _entrar(cliente, "ana", SENHA_ADMIN, **trocando_o_inicio).status_code == 429


def test_sucesso_zera_o_contador(cliente: TestClient) -> None:
    for _ in range(sessoes_do_painel.MAXIMO_DE_FALHAS - 1):
        _entrar(cliente, "ana", "senha-errada-000")
    assert _entrar(cliente, "ana", SENHA_ADMIN).status_code == 204

    # O contador recomeçou: mais quatro erros ainda são 401, não 429.
    for _ in range(sessoes_do_painel.MAXIMO_DE_FALHAS - 1):
        assert _entrar(cliente, "ana", "senha-errada-000").status_code == 401
    assert _entrar(cliente, "ana", SENHA_ADMIN).status_code == 204


def test_o_contador_nasce_com_prazo(cliente: TestClient, redis: _RedisFalso) -> None:
    """Contador sem TTL bloquearia o login para sempre."""
    _entrar(cliente, "ana", "senha-errada-000")

    (chave,) = [c for c in redis.dados if c.startswith(sessoes_do_painel.PREFIXO_TENTATIVAS)]
    assert redis.ttls[chave] == sessoes_do_painel.JANELA_DE_FALHAS_S
    assert "ana" not in chave and "testclient" not in chave


# ─────────────────────────── sair e expirar ────────────────────────────────


def test_sair_invalida_a_sessao(cliente: TestClient, redis: _RedisFalso) -> None:
    token = _token(_entrar(cliente, "ana", SENHA_ADMIN))
    assert cliente.get("/painel/fila").status_code == 200

    saida = cliente.delete("/painel/sessao")

    assert saida.status_code == 204
    assert seguranca.COOKIE_SESSAO in saida.headers["set-cookie"]
    assert "Max-Age=0" in saida.headers["set-cookie"]
    assert redis.chaves_do_painel() == []
    # O mesmo token, apresentado de novo por quem o guardou, não vale mais.
    cliente.cookies.set(seguranca.COOKIE_SESSAO, token)
    assert cliente.get("/painel/fila").status_code == 401
    assert cliente.get("/painel/sessao").status_code == 401


def test_sair_sem_sessao_tambem_e_204(cliente: TestClient) -> None:
    assert cliente.delete("/painel/sessao").status_code == 204


def test_sessao_expirada_e_401(cliente: TestClient, redis: _RedisFalso) -> None:
    _entrar(cliente, "ana", SENHA_ADMIN)
    (chave,) = redis.chaves_do_painel()
    assert redis.ttls[chave] == 12 * 3600, "o prazo da sessão é o TTL do Redis"

    # O Redis apagando a chave no fim do TTL.
    del redis.dados[chave]

    resposta = cliente.get("/painel/fila")
    assert resposta.status_code == 401
    assert resposta.json()["detail"] == "Sessão ausente ou expirada. Entre de novo."


def test_prazo_da_sessao_vem_da_configuracao(
    monkeypatch: pytest.MonkeyPatch, redis: _RedisFalso
) -> None:
    c = _cliente(monkeypatch, PAINEL_USUARIOS=USUARIOS, PAINEL_SESSAO_HORAS="2")
    resposta = _entrar(c, "ana", SENHA_ADMIN)

    (chave,) = redis.chaves_do_painel()
    assert redis.ttls[chave] == 2 * 3600
    assert f"Max-Age={2 * 3600}" in resposta.headers["set-cookie"]


def test_token_inventado_e_401(cliente: TestClient) -> None:
    cliente.cookies.set(seguranca.COOKIE_SESSAO, "inventado-por-alguem")
    assert cliente.get("/painel/fila").status_code == 401


def test_sem_cookie_e_401(cliente: TestClient) -> None:
    assert cliente.get("/painel/fila").status_code == 401
    assert cliente.get("/painel/sessao").status_code == 401


def test_quem_saiu_da_configuracao_perde_a_sessao_na_hora(
    monkeypatch: pytest.MonkeyPatch, redis: _RedisFalso
) -> None:
    c = _cliente(monkeypatch, PAINEL_USUARIOS=USUARIOS)
    token = _token(_entrar(c, "beto", SENHA_OPERADOR))

    # A API reinicia com o beto fora da lista.
    c = _cliente(monkeypatch, PAINEL_USUARIOS=f"ana:admin:{HASH_ADMIN}")
    c.cookies.set(seguranca.COOKIE_SESSAO, token)

    assert c.get("/painel/fila").status_code == 401
    assert redis.chaves_do_painel() == [], "e a sessão órfã sai do Redis"


def test_o_token_cru_nunca_vai_para_o_redis(cliente: TestClient, redis: _RedisFalso) -> None:
    token = _token(_entrar(cliente, "ana", SENHA_ADMIN))

    for chave, valor in redis.dados.items():
        assert token not in chave
        assert token not in valor
    (chave,) = redis.chaves_do_painel()
    assert chave == "painel:sessao:" + hashlib.sha256(token.encode()).hexdigest()


def test_a_sessao_do_login_nao_se_confunde_com_conversa(
    cliente: TestClient, redis: _RedisFalso
) -> None:
    """`sessao:*` é das conversas de WhatsApp, e o boot varre esse prefixo."""
    _entrar(cliente, "ana", SENHA_ADMIN)

    for chave in redis.chaves_do_painel():
        assert not chave.startswith(sessoes_redis.PREFIXO)
        assert not chave.startswith(sessoes_redis.PREFIXO_JANELA)


def test_o_que_a_sessao_guarda(cliente: TestClient, redis: _RedisFalso) -> None:
    import json

    _entrar(cliente, "ana", SENHA_ADMIN)
    (chave,) = redis.chaves_do_painel()

    dados = json.loads(redis.dados[chave])
    assert set(dados) == {"usuario", "perfil", "criada_em"}
    assert dados["usuario"] == "ana" and dados["perfil"] == "admin"


# ─────────────────────────────── os perfis ─────────────────────────────────


@pytest.fixture
def sem_disparar(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    montados: list[dict] = []

    async def fingir(cfg, payload, origem="rastreador"):
        montados.append(payload)
        return ResultadoDoEvento(200, {"atendido": True, "evento_id": "ev-123"})

    monkeypatch.setattr(eventos_de_teste, "processar_evento_rastreador", fingir)
    return montados


PEDIDO_DE_TESTE = {"tipo": "PANICO", "telefone": "+5541999999999"}


def test_operador_ve_a_fila(cliente: TestClient) -> None:
    _entrar(cliente, "beto", SENHA_OPERADOR)

    for rota in ("/painel/fila", "/painel/estado", "/painel/encerrados", "/painel/metricas"):
        assert cliente.get(rota).status_code == 200, rota


def test_operador_nao_usa_o_que_e_de_admin(cliente: TestClient, sem_disparar) -> None:
    _entrar(cliente, "beto", SENHA_OPERADOR)

    recusas = [
        cliente.get("/painel/testes/catalogo"),
        cliente.post("/painel/testes/evento", json=PEDIDO_DE_TESTE),
        cliente.get("/painel/testes/modelo"),
        cliente.post("/painel/testes/modelo", json={"modelo": "google/gemini-2.5-flash"}),
        cliente.post("/painel/simular", json={}),
    ]

    assert [r.status_code for r in recusas] == [403] * len(recusas)
    assert recusas[0].json()["detail"] == "Esta função é só do perfil admin."
    assert sem_disparar == [], "nada saiu para celular nenhum"


def test_admin_usa_tudo(
    cliente: TestClient, sem_disparar, monkeypatch: pytest.MonkeyPatch
) -> None:
    _entrar(cliente, "ana", SENHA_ADMIN)

    assert cliente.get("/painel/fila").status_code == 200
    assert cliente.get("/painel/testes/catalogo").status_code == 200
    assert cliente.get("/painel/testes/modelo").status_code == 200
    assert cliente.post("/painel/testes/evento", json=PEDIDO_DE_TESTE).status_code == 200
    assert len(sem_disparar) == 1


def test_admin_pode_simular(cliente: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem rodar o pipeline de verdade: o que se confere aqui é a porta."""

    class _LLM:
        async def fechar(self) -> None:
            return None

    class _Resultado:
        ocorrencia_id = "OC-TESTE"
        estado = "ENCERRADA_PELA_IA"
        elegivel_ia = True
        desfecho = "teste"
        custo_usd = 0.0
        auditoria: list = []

    class _Pipeline:
        def __init__(self, *_args) -> None:
            pass

        async def processar(self, *_args) -> _Resultado:
            return _Resultado()

    monkeypatch.setattr(painel, "construir_cliente_llm", lambda _cfg: _LLM())
    monkeypatch.setattr(painel, "construir_fonte", lambda _cfg: None)
    monkeypatch.setattr(painel, "Pipeline", _Pipeline)
    monkeypatch.setattr(painel, "_SIMULADAS", [])

    _entrar(cliente, "ana", SENHA_ADMIN)

    assert cliente.post("/painel/simular", json={}).status_code == 200


def test_tela_de_testes_desligada_e_404_ate_para_o_operador(
    monkeypatch: pytest.MonkeyPatch, redis: _RedisFalso
) -> None:
    """404 antes do 403: 403 contaria que a rota existe, e desligada ela não existe."""
    c = _cliente(monkeypatch, PAINEL_USUARIOS=USUARIOS, PAINEL_TESTES_ATIVO="false")
    _entrar(c, "beto", SENHA_OPERADOR)

    assert c.get("/painel/testes/catalogo").status_code == 404
    assert c.post("/painel/testes/evento", json=PEDIDO_DE_TESTE).status_code == 404


def test_sem_sessao_a_tela_de_testes_ligada_pede_login(cliente: TestClient) -> None:
    assert cliente.get("/painel/testes/catalogo").status_code == 401
    assert cliente.post("/painel/simular", json={}).status_code == 401


# ─────────────────────── sem usuário configurado ───────────────────────────


@pytest.mark.parametrize("ambiente", ["hml", "prd-poc"])
def test_producao_sem_usuario_fecha_o_painel(
    monkeypatch: pytest.MonkeyPatch, redis: _RedisFalso, ambiente: str
) -> None:
    """⛔ Falha fechada. Painel aberto em produção por esquecer uma variável é
    exatamente o que o login existe para evitar."""
    c = _cliente(monkeypatch, APP_ENV=ambiente)

    for resposta in (
        c.get("/painel/fila"),
        c.get("/painel/sessao"),
        _entrar(c, "ana", SENHA_ADMIN),
        c.delete("/painel/sessao"),
    ):
        assert resposta.status_code == 503
        assert "PAINEL_USUARIOS" in resposta.json()["detail"]


def test_producao_com_usuario_exige_login(
    monkeypatch: pytest.MonkeyPatch, redis: _RedisFalso
) -> None:
    c = _cliente(monkeypatch, APP_ENV="prd-poc", PAINEL_USUARIOS=USUARIOS)

    assert c.get("/painel/fila").status_code == 401
    _entrar(c, "beto", SENHA_OPERADOR)
    assert c.get("/painel/fila").status_code == 200


def test_desenvolvimento_sem_usuario_continua_aberto(
    monkeypatch: pytest.MonkeyPatch, redis: _RedisFalso
) -> None:
    c = _cliente(monkeypatch, PAINEL_TESTES_ATIVO="true")

    assert c.get("/painel/fila").status_code == 200
    assert c.get("/painel/testes/catalogo").status_code == 200, "perfil tratado como admin"
    assert c.get("/painel/sessao").json() == {
        "usuario": None,
        "perfil": "admin",
        "login_ativo": False,
    }
    # Não há login para fazer: 409, com o motivo.
    resposta = _entrar(c, "ana", SENHA_ADMIN)
    assert resposta.status_code == 409
    assert "PAINEL_USUARIOS" in resposta.json()["detail"]
    assert redis.chaves_do_painel() == []


def test_o_boot_avisa_como_o_login_esta(monkeypatch: pytest.MonkeyPatch) -> None:
    registros: list[tuple[str, str]] = []

    class _Log:
        def info(self, evento: str, **_kw) -> None:
            registros.append(("info", evento))

        def warning(self, evento: str, **_kw) -> None:
            registros.append(("warning", evento))

        def error(self, evento: str, **_kw) -> None:
            registros.append(("error", evento))

    monkeypatch.setattr(seguranca, "log", _Log())

    for cfg in (
        Settings(app_env="prd-poc"),
        Settings(app_env="dev"),
        Settings(painel_usuarios=USUARIOS),
    ):
        monkeypatch.setattr(seguranca, "settings", lambda cfg=cfg: cfg)
        seguranca.avisar_sobre_o_login()

    assert registros == [
        ("error", "painel_sem_login"),
        ("warning", "painel_sem_login"),
        ("info", "painel_login_ativo"),
    ]


# ───────────────────────────── Redis fora ──────────────────────────────────


def test_redis_fora_fecha_em_vez_de_abrir(cliente: TestClient, redis: _RedisFalso) -> None:
    _entrar(cliente, "ana", SENHA_ADMIN)
    redis.fora_do_ar = True

    assert cliente.get("/painel/fila").status_code == 503
    assert _entrar(cliente, "ana", SENHA_ADMIN).status_code == 503


# ──────────────────────── onde as trancas estão ────────────────────────────


def _dependencias(router) -> list[str]:
    return [d.dependency.__name__ for d in router.dependencies if d.dependency]


def test_todo_o_painel_exige_sessao() -> None:
    """No router, e não em cada rota: rota nova nasce protegida."""
    for router in (painel.router, eventos_de_teste.router):
        nomes = _dependencias(router)
        assert nomes.index("exigir_token_do_painel") < nomes.index("exigir_sessao")


def test_tela_de_testes_inteira_e_de_admin() -> None:
    assert "exigir_admin" in _dependencias(eventos_de_teste.router)


def test_simular_e_de_admin() -> None:
    (rota,) = [r for r in painel.router.routes if r.path == "/painel/simular"]
    assert "exigir_admin" in [d.dependency.__name__ for d in rota.dependencies]


def test_a_rota_de_login_nao_exige_sessao_mas_exige_o_token() -> None:
    nomes = _dependencias(sessao.router)
    assert "exigir_token_do_painel" in nomes
    assert "exigir_sessao" not in nomes


@pytest.mark.parametrize("modulo", [saude, midia, whatsapp, eventos])
def test_rotas_sem_pessoa_continuam_sem_login(modulo) -> None:
    """Healthcheck, Twilio e rastreador não fazem login. Ver `api/seguranca.py`."""
    assert "exigir_sessao" not in _dependencias(modulo.router)


# ──────────────────────── o script que gera a entrada ──────────────────────


def _script():
    caminho = Path(__file__).resolve().parents[1] / "scripts" / "criar_usuario_painel.py"
    spec = importlib.util.spec_from_file_location("criar_usuario_painel", caminho)
    modulo = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(modulo)
    return modulo


def _digitando(monkeypatch: pytest.MonkeyPatch, modulo, *respostas: str) -> None:
    fila = list(respostas)
    monkeypatch.setattr(modulo.getpass, "getpass", lambda _prompt="": fila.pop(0))


def test_script_imprime_so_a_entrada(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    modulo = _script()
    _digitando(monkeypatch, modulo, SENHA_OPERADOR, SENHA_OPERADOR)

    assert modulo.main(["Beto", "operador"]) == 0

    saida = capsys.readouterr()
    linha = saida.out.strip()
    assert "\n" not in linha
    assert SENHA_OPERADOR not in saida.out and SENHA_OPERADOR not in saida.err
    usuario = carregar_usuarios(linha)["beto"]
    assert usuario.perfil == "operador"
    assert verificar_senha(SENHA_OPERADOR, usuario.hash_senha)


@pytest.mark.parametrize(
    ("respostas", "codigo"),
    [(("curta", "curta"), 1), ((SENHA_ADMIN, "outra-senha-qualquer"), 1)],
)
def test_script_recusa_senha_curta_ou_que_nao_confere(
    monkeypatch: pytest.MonkeyPatch, capsys, respostas: tuple[str, str], codigo: int
) -> None:
    modulo = _script()
    _digitando(monkeypatch, modulo, *respostas)

    assert modulo.main(["ana", "admin"]) == codigo
    assert capsys.readouterr().out == "", "nada para colar quando recusa"


def test_script_recusa_perfil_desconhecido(capsys) -> None:
    with pytest.raises(SystemExit):
        _script().main(["ana", "chefe"])
