"""Camada operacional: conversa, mensagem, metrica_turno.

Retenção curta (90 dias) e expurgo automatizado — minimização de dado na
prática (doc 02 §5.2). O resumo e o desfecho vão para o Oracle, que tem
retenção longa e auditável.

Revision ID: 0001
Revises:
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversa (
          conversa_id       CHAR(36) PRIMARY KEY,
          ocorrencia_id     VARCHAR(40) NOT NULL,
          canal             ENUM('LIGACAO','AUDIO','TEXTO') NOT NULL,
          estado            VARCHAR(30) NOT NULL,
          autenticado       TINYINT(1) DEFAULT 0,
          ia_pausada        TINYINT(1) DEFAULT 0,
          turnos            SMALLINT DEFAULT 0,
          tokens_entrada    INT DEFAULT 0,
          tokens_saida      INT DEFAULT 0,
          tokens_cache_read INT DEFAULT 0,
          custo_usd         DECIMAL(10,6) DEFAULT 0,
          iniciada_em       DATETIME(3) NOT NULL,
          encerrada_em      DATETIME(3) NULL,
          INDEX ix_conversa_ocorrencia (ocorrencia_id),
          INDEX ix_conversa_estado (estado, iniciada_em)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
    )

    # A chave primária inclui `criada_em` porque o MySQL exige que toda coluna
    # de particionamento faça parte de cada chave única da tabela. O DDL do
    # doc 02 §5.2 traz `PRIMARY KEY (mensagem_id)` isolada, o que é rejeitado
    # com ERROR 1503 — corrigido aqui.
    op.execute(
        """
        CREATE TABLE mensagem (
          mensagem_id BIGINT NOT NULL AUTO_INCREMENT,
          conversa_id CHAR(36) NOT NULL,
          papel       ENUM('user','assistant','system','tool') NOT NULL,
          conteudo    JSON NOT NULL,
          audio_uri   VARCHAR(500) NULL,
          latencia_ms INT NULL,
          criada_em   DATETIME(3) NOT NULL,
          PRIMARY KEY (mensagem_id, criada_em),
          INDEX ix_msg_conversa (conversa_id, mensagem_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        PARTITION BY RANGE (TO_DAYS(criada_em)) (
          PARTITION p_inicial VALUES LESS THAN (TO_DAYS('2026-09-01')),
          PARTITION p_max     VALUES LESS THAN MAXVALUE
        )
        """
    )

    op.execute(
        """
        CREATE TABLE metrica_turno (
          metrica_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
          conversa_id  CHAR(36) NOT NULL,
          ms_stt       INT,
          ms_llm_ttft  INT,
          ms_llm_total INT,
          ms_tts_ttfa  INT,
          ms_voz_a_voz INT,
          barge_in     TINYINT(1) DEFAULT 0,
          criada_em    DATETIME(3) NOT NULL,
          INDEX ix_metrica_conversa (conversa_id),
          INDEX ix_metrica_criada (criada_em)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS metrica_turno")
    op.execute("DROP TABLE IF EXISTS mensagem")
    op.execute("DROP TABLE IF EXISTS conversa")
