"""A assinatura do webhook do Twilio.

É a única coisa que separa "mensagem de um cliente" de "mensagem de quem
descobriu a URL". Se ela falhar aberta, um estranho consegue fazer a IA
escrever no celular de uma pessoa real — por isso estes testes existem antes
de qualquer teste de conversa.

O vetor abaixo é o exemplo oficial da documentação do Twilio, com o token
`12345`. Usar o exemplo deles, e não um gerado por este mesmo código, é o que
prova que a implementação está certa: um teste que assina e confere com a
própria função passaria mesmo com o algoritmo errado.
"""

from __future__ import annotations

import pytest

from central_ia.integrations.mensageria import (
    assinatura_valida,
    numero_autorizado,
    url_do_webhook,
    variantes_do_numero,
)

TOKEN = "12345"
URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
PARAMETROS = {
    "CallSid": "CA1234567890ABCDE",
    "Caller": "+14158675309",
    "Digits": "1234",
    "From": "+14158675309",
    "To": "+18005551212",
}
ASSINATURA = "RSOYDt4T1cUTdK1PDd93/VVr8B8="


def test_assinatura_do_exemplo_oficial_e_aceita() -> None:
    assert assinatura_valida(TOKEN, URL, PARAMETROS, ASSINATURA)


def test_assinatura_errada_e_recusada() -> None:
    assert not assinatura_valida(TOKEN, URL, PARAMETROS, "naoEhAAssinaturaCerta=")


def test_parametro_alterado_invalida() -> None:
    """Trocar o remetente tem de derrubar a assinatura — é o ataque óbvio."""
    adulterado = PARAMETROS | {"From": "+15550000000"}
    assert not assinatura_valida(TOKEN, URL, adulterado, ASSINATURA)


def test_url_diferente_invalida() -> None:
    """Assinar sobre a URL errada é o erro nº 1 quando há túnel no meio."""
    assert not assinatura_valida(TOKEN, URL.replace("https", "http"), PARAMETROS, ASSINATURA)


def test_token_ausente_falha_fechado() -> None:
    """Sem token não se aceita nada. Falha aberta aqui seria porta destrancada."""
    assert not assinatura_valida("", URL, PARAMETROS, ASSINATURA)
    assert not assinatura_valida(TOKEN, URL, PARAMETROS, "")


@pytest.mark.parametrize(
    ("base", "esperada"),
    [
        ("https://algo.ngrok.app", "https://algo.ngrok.app/whatsapp/entrada"),
        ("https://algo.ngrok.app/", "https://algo.ngrok.app/whatsapp/entrada"),
    ],
)
def test_url_do_webhook_normaliza_barra_final(base: str, esperada: str) -> None:
    """Uma barra a mais entre o cadastrado e o reconstruído invalida a assinatura."""
    assert url_do_webhook(base) == esperada


# ───────────────────── o nono dígito dos celulares brasileiros ─────────────────


def test_celular_brasileiro_bate_com_e_sem_o_nono_digito() -> None:
    """O Twilio entrega ora com 9, ora sem — e é a mesma pessoa.

    Recusar o dono do celular por um dígito produz o pior sintoma possível:
    "este número não está autorizado" para quem está autorizado.
    """
    com_nove = "whatsapp:+5541999999999"
    sem_nove = "whatsapp:+554199999999"

    assert numero_autorizado(sem_nove, [com_nove])
    assert numero_autorizado(com_nove, [sem_nove])
    assert numero_autorizado(com_nove, [com_nove])


def test_numero_de_outra_pessoa_continua_recusado() -> None:
    """A tolerância é com a grafia, não com quem é."""
    assert not numero_autorizado("whatsapp:+5541988887777", ["whatsapp:+5541999999999"])
    assert not numero_autorizado("whatsapp:+5511999999999", ["whatsapp:+5541999999999"])
    assert not numero_autorizado("whatsapp:+5541999999999", [])


def test_fixo_e_estrangeiro_nao_ganham_variante() -> None:
    """A regra do nono dígito é de celular brasileiro. Não vale para o resto."""
    assert variantes_do_numero("whatsapp:+14155238886") == {"+14155238886"}
    # Fixo começa com 2..5 — não recebe o 9 na frente.
    assert variantes_do_numero("whatsapp:+554133221100") == {"+554133221100"}


def test_variantes_saem_em_forma_canonica() -> None:
    """Sempre `+55...`, sempre sem `whatsapp:` — venha o número como vier.

    Antes a função preservava o prefixo, e aí `whatsapp:+5541...` e `+5541...`
    geravam conjuntos que nunca se cruzavam. Só não quebrava porque a lista de
    autorizados trazia as duas formas escritas à mão.
    """
    canonico = {"+5541999999999", "+554199999999"}

    assert variantes_do_numero("whatsapp:+5541999999999") == canonico
    assert variantes_do_numero("+5541999999999") == canonico
    assert variantes_do_numero("+554199999999") == canonico
    # E a grafia da Meta: sem `+`, sem o nono dígito.
    assert variantes_do_numero("554199999999") == canonico
    assert variantes_do_numero("5541999999999") == canonico


def test_numero_da_meta_e_autorizado_como_qualquer_outro() -> None:
    """**Bug de 25/08/2026, no celular de um motorista.**

    O regex exigia o `+` inicial e a Meta não manda `+`. Toda mensagem vinda do
    WhatsApp caía fora da lista — e passava despercebido porque, quando a IA
    abre a conversa pelo evento, a sessão já existe e este teste nem roda.
    Bastou um restart apagar a sessão para um "Diamante" no meio do
    atendimento virar recusa, com nome de variável de ambiente na resposta.
    """
    lista = ["+5541999999999"]

    # As quatro grafias que chegam de verdade, de quatro interlocutores.
    assert numero_autorizado("+5541999999999", lista), "payload da Bahrd"
    assert numero_autorizado("whatsapp:+5541999999999", lista), "Twilio"
    assert numero_autorizado("554199999999", lista), "Meta — sem + e sem o nono"
    assert numero_autorizado("5541999999999", lista), "Meta — sem +, com o nono"

    # E continua recusando quem não é.
    assert not numero_autorizado("554188887777", lista)
