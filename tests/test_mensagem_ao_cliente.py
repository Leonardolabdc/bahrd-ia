"""Nada de andaime interno na tela de quem está na estrada.

**Aconteceu em 25/08/2026.** Um motorista mandou a palavra-chave de segurança
no meio do atendimento. Um restart tinha apagado a sessão da memória, a
mensagem caiu no ramo de "número não autorizado", e ele recebeu:

    Este número não está autorizado a abrir ocorrência nesta POC.
    Peça para incluírem ele em TWILIO_NUMEROS_DE_TESTE.

Nome de variável de ambiente no WhatsApp de um cliente. O motivo interno é
legítimo e precisa existir — mas o lugar dele é o log, que é onde quem pode
agir vai olhar. Quem está do outro lado precisa de um caminho, não de um
diagnóstico.

Este teste vale para a frase que sobra quando **não se sabe quem é** a pessoa.
O menu `AJUDA` é outra coisa: ele só vai para número já autorizado, é andaime
declarado da POC, e some quando a POC virar produção.
"""

from __future__ import annotations

import re

from central_ia.api.rotas import whatsapp

#: Nome de variável de ambiente e afins: MAIÚSCULAS com sublinhado. É a forma
#: que o vazamento tomou, e a que um olho distraído não reconhece como interna.
_PARECE_CONFIGURACAO = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")

#: Palavras que só fazem sentido para quem construiu o sistema.
_JARGAO = (
    "POC",
    "não autorizado",
    "nao autorizado",
    "webhook",
    "token",
    "sessão",
    "variável",
    "env",
)


def test_sem_atendimento_aberto_nao_expoe_configuracao() -> None:
    frase = whatsapp.SEM_ATENDIMENTO_ABERTO

    achado = _PARECE_CONFIGURACAO.findall(frase)
    assert not achado, f"nome de configuração na mensagem ao cliente: {achado}"

    for termo in _JARGAO:
        assert termo.lower() not in frase.lower(), f"jargão interno na mensagem: '{termo}'"


def test_sem_atendimento_aberto_da_um_caminho() -> None:
    """Recusar sem oferecer saída é pior que não responder.

    A pessoa escreveu porque precisa de alguma coisa. Se não dá para atender
    por aqui, ela tem de sair da mensagem sabendo para onde ir — e o 0800 da
    Central funciona sempre, inclusive quando a POC inteira estiver fora do ar.
    """
    frase = whatsapp.SEM_ATENDIMENTO_ABERTO

    assert "0800-080-8888" in frase
    assert "Bahrd" in frase, "a pessoa precisa saber quem está falando"
    # Curta: é WhatsApp, lido no celular, provavelmente na estrada.
    assert len(frase) < 220


def test_nenhuma_frase_do_modulo_carrega_nome_de_configuracao() -> None:
    """Vale para todas, não só para a que vazou.

    A verificação é sobre os **valores** das constantes de texto do módulo, não
    sobre o código-fonte: docstring e comentário mencionam
    `TWILIO_NUMEROS_DE_TESTE` de propósito, para explicar o incidente, e
    documentação não é entregue a ninguém. O que não pode existir é uma string
    pronta para envio com esse tipo de nome dentro.
    """
    frases = {
        nome: valor
        for nome, valor in vars(whatsapp).items()
        if nome.isupper() and isinstance(valor, str)
    }
    assert frases, "nenhuma constante de texto encontrada — o teste perdeu o alvo"

    for nome, frase in frases.items():
        achado = _PARECE_CONFIGURACAO.findall(frase)
        assert not achado, f"{nome} carrega nome de configuração: {achado}"
