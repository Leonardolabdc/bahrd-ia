"""Nome de variável que o código não lê mais derruba a partida, em vez de sumir.

⛔ **Visto na conferência do `docker-compose.yml` em 09/09/2026.** O `config.py`
declarava cinco campos `whatsapp_*` — token, id do número, verify token, app
secret e versão da API — e **nenhum deles era lido por lugar nenhum**. O canal
sempre leu `meta_*`.

O modo de falha é o pior possível porque não tem sintoma: `extra="ignore"` faz
o Pydantic engolir a variável, a aplicação sobe inteira, `/saude/pronto`
responde, o healthcheck do container passa — e o WhatsApp fica mudo. Numa
central de monitoramento, é o alarme de um cliente não chegando a ninguém, sem
um erro em log nenhum para investigar.

⚠️ Apagar os campos **não** resolveria sozinho: com `extra="ignore"`, a
variável continuaria sendo ignorada em silêncio, só que sem nem aparecer no
código. Por isso a recusa é explícita.
"""

from __future__ import annotations

import pytest

from central_ia.config import Settings


class TestRecusaNomeAntigo:
    """Preencher o nome morto quebra na partida, com o nome novo na mensagem."""

    @pytest.mark.parametrize(
        ("morta", "viva"),
        [
            ("whatsapp_token", "META_ACCESS_TOKEN"),
            ("whatsapp_phone_number_id", "META_PHONE_NUMBER_ID"),
            ("whatsapp_verify_token", "META_VERIFY_TOKEN"),
            ("whatsapp_app_secret", "META_APP_SECRET"),
            ("whatsapp_api_version", "META_API_VERSION"),
        ],
    )
    def test_cada_nome_morto_derruba_e_aponta_o_novo(self, morta: str, viva: str) -> None:
        with pytest.raises(ValueError) as erro:
            Settings(**{morta: "valor-qualquer"})

        # A mensagem precisa carregar o destino. Um "variável inválida" seco
        # mandaria a pessoa procurar no código o que ela deveria escrever.
        assert viva in str(erro.value)

    def test_reclama_de_todas_de_uma_vez(self) -> None:
        """Quem copiou um `.env` antigo errou em bloco, e conserta em bloco.

        Falhar em uma por vez faria a pessoa subir, corrigir, subir de novo,
        cinco vezes.
        """
        with pytest.raises(ValueError) as erro:
            Settings(whatsapp_token="a", whatsapp_app_secret="b")

        assert "META_ACCESS_TOKEN" in str(erro.value)
        assert "META_APP_SECRET" in str(erro.value)


class TestNaoAtrapalhaQuemEstaCerto:
    """A trava não pode custar partida de quem configurou direito."""

    def test_vazia_nao_derruba(self) -> None:
        """⚠️ Sobra de `.env.example` copiado é comum e não é engano.

        Derrubar por causa de uma linha vazia trocaria um susto silencioso por
        um barulhento e inútil — e ensinaria a ignorar o erro.
        """
        assert Settings(whatsapp_token="", whatsapp_app_secret="   ").app_env == "dev"

    def test_o_campo_vivo_com_o_mesmo_prefixo_continua_funcionando(self) -> None:
        """⛔ `WHATSAPP_RESPONDER_EM_AUDIO` é viva e usa o mesmo prefixo.

        É por causa dela que a checagem lista nomes em vez de barrar o prefixo
        `WHATSAPP_` inteiro. Barrar o prefixo desligaria a resposta em áudio de
        quem a configurou — e essa é a variável que mais mexe na conta.
        """
        assert Settings(whatsapp_responder_em_audio=False).whatsapp_responder_em_audio is False
        assert Settings().whatsapp_responder_em_audio is True

    def test_o_nome_novo_e_lido_de_verdade(self) -> None:
        """Fecha o par: o que a mensagem de erro manda usar precisa funcionar."""
        cfg = Settings(meta_access_token="tok", meta_phone_number_id="123")
        assert cfg.meta_access_token is not None
        assert cfg.meta_access_token.get_secret_value() == "tok"
        assert cfg.meta_phone_number_id == "123"


def test_os_campos_mortos_nao_voltaram() -> None:
    """Impede a reintrodução silenciosa, que é como eles apareceram.

    Alguém lendo `META_ACCESS_TOKEN` e achando o nome pouco claro pode
    "consertar" declarando `whatsapp_token` de novo. Aqui o teste vermelho
    explica antes que o defeito volte.
    """
    for morto in (
        "whatsapp_token",
        "whatsapp_phone_number_id",
        "whatsapp_verify_token",
        "whatsapp_app_secret",
        "whatsapp_api_version",
    ):
        assert morto not in Settings.model_fields, (
            f"`{morto}` voltou ao Settings. O canal lê `meta_*`; um campo com "
            "este nome é lido por ninguém e some em silêncio."
        )
