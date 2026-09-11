"""Testes da camada de configuração.

`domain/` e `policy/` — onde vivem as regras que não podem falhar — serão
testáveis sem banco, sem rede e sem LLM (doc 02 §4). Estes aqui são a primeira
parcela disso: `Settings` não toca em nada externo, então roda em milissegundos.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from central_ia.config import Settings, _por_virgula


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("a,b", ["a", "b"]),
        ("a, b , c", ["a", "b", "c"]),
        ("", []),
        ("   ", []),
        ("so-um", ["so-um"]),
        # Formato JSON: já existe em `.env` por aí. Ignorá-lo quebrou o CORS do
        # painel — a lista virava lixo e o browser só dizia "Failed to fetch".
        ('["http://localhost:5173","http://127.0.0.1:5173"]',
         ["http://localhost:5173", "http://127.0.0.1:5173"]),
        ('[ "a" , "b" ]', ["a", "b"]),
        ("[]", []),
        # JSON quebrado não pode derrubar a aplicação: cai no modo vírgula.
        ('["a", "b"', ['["a"', '"b"']),
    ],
)
def test_lista_do_ambiente_aceita_virgula_e_json(entrada: str, esperado: list[str]) -> None:
    assert _por_virgula(entrada) == esperado


def _base(**extra: str) -> dict[str, str]:
    return {
        "ORACLE_PASSWORD": "senha-oracle",
        "MYSQL_PASSWORD": "senha-mysql",
        **extra,
    }


def test_valores_padrao_sao_de_desenvolvimento(monkeypatch: pytest.MonkeyPatch) -> None:
    for chave, valor in _base().items():
        monkeypatch.setenv(chave, valor)

    cfg = Settings()

    assert cfg.app_env == "dev"
    assert cfg.em_producao is False
    assert cfg.modo_voz == "voz_simulada"
    assert cfg.secret_provider == "env"
    assert cfg.kill_switch_ativo is False


def test_ambiente_invalido_falha_no_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falhar no boot é o comportamento certo: um `APP_ENV` errado em produção
    escolheria o caminho de segredos errado silenciosamente."""
    for chave, valor in _base(APP_ENV="producao").items():
        monkeypatch.setenv(chave, valor)

    with pytest.raises(ValidationError):
        Settings()


def test_redis_url_sem_credencial(monkeypatch: pytest.MonkeyPatch) -> None:
    for chave, valor in _base(REDIS_HOST="cache", REDIS_PORT="6380").items():
        monkeypatch.setenv(chave, valor)
    monkeypatch.delenv("REDIS_AUTH_TOKEN", raising=False)

    assert Settings().redis_url == "redis://cache:6380"


def test_redis_url_com_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Na OCI o Redis exige *auth token* — o mesmo código monta as duas URLs."""
    for chave, valor in _base(REDIS_AUTH_TOKEN="segredo").items():
        monkeypatch.setenv(chave, valor)

    assert Settings().redis_url == "redis://:segredo@redis:6379"


def test_mysql_url_usa_driver_assincrono(monkeypatch: pytest.MonkeyPatch) -> None:
    for chave, valor in _base().items():
        monkeypatch.setenv(chave, valor)

    cfg = Settings()
    assert cfg.mysql_url.startswith("mysql+aiomysql://")
    # O Alembic roda síncrono; daí a segunda URL.
    assert cfg.mysql_url_sincrono.startswith("mysql+pymysql://")


def test_segredo_nao_vaza_em_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um `print(settings())` num log de boot não pode vazar credencial."""
    for chave, valor in _base(ANTHROPIC_API_KEY="sk-ant-secreto").items():
        monkeypatch.setenv(chave, valor)

    texto = repr(Settings())
    assert "sk-ant-secreto" not in texto
    assert "senha-oracle" not in texto


def test_chave_vazia_conta_como_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` guarda a linha da chave vazia até alguém preenchê-la.

    Se `""` virasse `SecretStr("")`, o adaptador mandaria credencial vazia ao
    provedor e o 401 diria "chave inválida" em vez de "chave ausente" — que é
    o oposto do diagnóstico útil.
    """
    for chave, valor in _base(ELEVENLABS_API_KEY="", DEEPGRAM_API_KEY="   ").items():
        monkeypatch.setenv(chave, valor)

    cfg = Settings()
    assert cfg.elevenlabs_api_key is None
    assert cfg.deepgram_api_key is None


def test_espaco_ao_colar_a_chave_e_removido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Colar com espaço à frente é o erro mais comum ao editar `.env`.

    Sem a limpeza, o header HTTP sai malformado e a biblioteca reclama de
    "illegal header value" — mensagem que não diz nada sobre a causa.
    """
    for chave, valor in _base(
        ELEVENLABS_API_KEY=" sk_abc123 ", OPENROUTER_MODELO=" anthropic/claude-sonnet-5 "
    ).items():
        monkeypatch.setenv(chave, valor)

    cfg = Settings()
    assert cfg.elevenlabs_api_key is not None
    assert cfg.elevenlabs_api_key.get_secret_value() == "sk_abc123"
    assert cfg.openrouter_modelo == "anthropic/claude-sonnet-5"


def test_chave_preenchida_e_lida(monkeypatch: pytest.MonkeyPatch) -> None:
    for chave, valor in _base(DEEPGRAM_API_KEY="dg-abc123").items():
        monkeypatch.setenv(chave, valor)

    chave = Settings().deepgram_api_key
    assert chave is not None
    assert chave.get_secret_value() == "dg-abc123"


def test_exigir_aponta_o_que_falta(monkeypatch: pytest.MonkeyPatch) -> None:
    for chave, valor in _base().items():
        monkeypatch.setenv(chave, valor)
    monkeypatch.setenv("SIP_USERNAME", "")

    cfg = Settings()
    with pytest.raises(RuntimeError, match="sip_username"):
        cfg.exigir("sip_username")
