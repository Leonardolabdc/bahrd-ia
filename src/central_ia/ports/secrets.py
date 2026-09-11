"""Porta de segredos — `.env` no Docker, OCI Vault na nuvem.

Contramedida à armadilha 2 do doc 02 §3.4: começar com `.env` é prático e vira
dívida quando alguém escreve ``open(".env")`` no código. Aqui o segredo entra
por uma interface; a origem é decidida na composição.
"""

from __future__ import annotations

import os
from typing import Protocol

from central_ia.config import Settings


class SecretProvider(Protocol):
    """Contrato único. `nome` é o identificador lógico, não o nome da variável."""

    async def get(self, nome: str) -> str: ...


class EnvSecretProvider:
    """Fase 1 — Docker local. O segredo já está no ambiente do processo."""

    async def get(self, nome: str) -> str:
        chave = nome.upper().replace("-", "_").replace("/", "_")
        try:
            return os.environ[chave]
        except KeyError as erro:
            raise KeyError(f"Segredo ausente no ambiente: {chave}") from erro


class OciVaultSecretProvider:
    """Fase 2 — OCI. A aplicação autentica por *instance/workload principal*,
    então não existe chave da OCI em variável de ambiente.

    Implementação entra no Sprint 4, junto com o provisionamento do Vault
    (doc 03 §7). A interface já está fechada para que nada mais precise mudar.
    """

    def __init__(self, vault_ocid: str, region: str) -> None:
        self._vault_ocid = vault_ocid
        self._region = region

    async def get(self, nome: str) -> str:  # pragma: no cover - Sprint 4
        raise NotImplementedError(
            "OciVaultSecretProvider entra no Sprint 4 (provisionamento do Vault)."
        )


def construir_secret_provider(cfg: Settings) -> SecretProvider:
    """Única linha que muda entre ambientes."""
    if cfg.secret_provider == "oci_vault":
        cfg.exigir("oci_vault_ocid")
        return OciVaultSecretProvider(cfg.oci_vault_ocid, cfg.oci_region)
    return EnvSecretProvider()
