"""Os avisos de entrega da Meta, que antes eram descartados em silêncio.

Escrito depois de 24/08, quando dois templates idênticos saíram com `200` e só
um chegou. A resposta estava num destes webhooks — e nós jogávamos fora.
"""

from __future__ import annotations

from central_ia.integrations.mensageria.meta import extrair, extrair_status


def _envelope(statuses: list[dict]) -> dict:
    return {"entry": [{"changes": [{"value": {"statuses": statuses}}]}]}


def test_falha_traz_codigo_e_motivo() -> None:
    """O que interessa numa falha é o porquê, não o fato."""
    payload = _envelope(
        [
            {
                "id": "wamid.XYZ",
                "status": "failed",
                "recipient_id": "5541988888888",
                "errors": [
                    {
                        "code": 131026,
                        "title": "Message undeliverable",
                        "error_data": {"details": "Receiver is incapable of receiving"},
                    }
                ],
            }
        ]
    )

    (st,) = extrair_status(payload)

    assert st.falhou
    assert st.codigo == 131026
    assert st.titulo == "Message undeliverable"
    assert st.detalhe == "Receiver is incapable of receiving"
    assert st.destinatario == "5541988888888"
    assert st.mensagem_id == "wamid.XYZ"


def test_entrega_normal_nao_e_falha() -> None:
    payload = _envelope([{"id": "wamid.A", "status": "delivered", "recipient_id": "554199"}])

    (st,) = extrair_status(payload)

    assert not st.falhou
    assert st.situacao == "delivered"


def test_lote_devolve_todos() -> None:
    """A Meta agrupa vários avisos num POST só."""
    payload = _envelope(
        [
            {"id": "1", "status": "sent", "recipient_id": "a"},
            {"id": "2", "status": "delivered", "recipient_id": "a"},
            {"id": "3", "status": "read", "recipient_id": "a"},
        ]
    )

    assert [s.situacao for s in extrair_status(payload)] == ["sent", "delivered", "read"]


def test_payload_de_mensagem_nao_gera_status() -> None:
    """E o inverso: status não pode virar fala do cliente.

    Os dois lados do mesmo webhook. Confundir faria a IA responder ao eco.
    """
    fala = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "554199", "id": "m1", "type": "text",
                                 "text": {"body": "oi"}}
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert extrair_status(fala) == []
    assert len(extrair(fala)) == 1


def test_payload_vazio_nao_explode() -> None:
    assert extrair_status({}) == []
    assert extrair_status({"entry": [{"changes": [{"value": {}}]}]}) == []


def test_falha_sem_bloco_de_erro() -> None:
    """`failed` sem `errors` acontece; não pode derrubar o webhook."""
    payload = _envelope([{"id": "x", "status": "failed", "recipient_id": "554199"}])

    (st,) = extrair_status(payload)

    assert st.falhou
    assert st.codigo is None
