"""Serve o áudio que a IA gerou, para o Twilio ir buscar.

O Twilio não aceita o áudio no corpo da requisição: ele recebe uma **URL** e
busca o arquivo depois. Por isso a nota de voz precisa ficar acessível de fora
— e é por isso que este módulo existe.

**Esta rota é pública, e isso é uma decisão, não um esquecimento.** O Twilio
busca a mídia sem credencial nossa; exigir autenticação aqui quebraria o envio.
O que protege é o resto:

* o identificador é um UUID aleatório — não dá para enumerar;
* o áudio vive `VALIDADE` minutos e some;
* o conteúdo é a fala da IA, que a pessoa do outro lado já recebeu.

O que **não** pode passar por aqui é áudio do cliente ou qualquer coisa com
dado pessoal — só a saída do TTS. Em produção isso vira URL assinada de object
storage com expiração, e a rota deixa de existir.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, status

router = APIRouter(prefix="/midia", tags=["midia"])

#: Tempo de vida de cada áudio. O Twilio busca em segundos; minutos é folga
#: para reenvio, não para guardar.
VALIDADE = timedelta(minutes=15)

#: Teto de itens em memória. Sem isso, uma demonstração longa vira vazamento.
MAXIMO = 60


@dataclass(frozen=True)
class Audio:
    conteudo: bytes
    tipo: str
    criado_em: datetime


_ARQUIVOS: dict[str, Audio] = {}


def _expirar() -> None:
    agora = datetime.now(UTC)
    vencidos = [k for k, a in _ARQUIVOS.items() if agora - a.criado_em > VALIDADE]
    for chave in vencidos:
        del _ARQUIVOS[chave]

    # Se ainda passou do teto, descarta os mais antigos.
    if len(_ARQUIVOS) > MAXIMO:
        por_idade = sorted(_ARQUIVOS.items(), key=lambda item: item[1].criado_em)
        for chave, _ in por_idade[: len(_ARQUIVOS) - MAXIMO]:
            del _ARQUIVOS[chave]


def guardar(conteudo: bytes, tipo: str, extensao: str = "mp3") -> str:
    """Guarda o áudio e devolve o nome do arquivo a compor a URL."""
    nome = f"{uuid.uuid4().hex}.{extensao}"
    _ARQUIVOS[nome] = Audio(conteudo, tipo, datetime.now(UTC))
    # A limpeza vem DEPOIS de inserir. Antes, o teto era furado por um: cortava
    # para o limite e em seguida somava mais um.
    _expirar()
    return nome


def url_publica(base: str, nome: str) -> str:
    return f"{base.rstrip('/')}/midia/{nome}"


@router.get(
    "/{nome}",
    summary="Áudio gerado pela IA, para o Twilio buscar",
    response_class=Response,
)
async def obter(nome: str) -> Response:
    _expirar()
    arquivo = _ARQUIVOS.get(nome)
    if arquivo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Áudio não encontrado ou expirado.",
        )
    return Response(
        content=arquivo.conteudo,
        media_type=arquivo.tipo,
        headers={"Cache-Control": "private, max-age=900"},
    )
