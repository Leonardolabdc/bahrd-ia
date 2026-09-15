-- ===========================================================================
-- 001 · Schema base do sistema de registro (Oracle 23ai)
--
-- Executado como CENTRAL_IA, SEM privilégios de DBA. Nada de ALTER SYSTEM,
-- CREATE TABLESPACE, UTL_FILE ou pacote restrito — é a contramedida à
-- armadilha 1 do doc 02 §3.4: o que roda aqui tem de rodar igual no ADB-S.
--
-- Placeholders ${...} são substituídos pelo runner a partir do ambiente.
-- ===========================================================================

-- ===== Cadastro (na Fase 2 pode virar VIEW sobre a base legada) =====
CREATE TABLE cliente (
  cliente_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  razao_social      VARCHAR2(200) NOT NULL,
  documento         VARCHAR2(20)  NOT NULL,
  atende_com_ia     CHAR(1) DEFAULT 'S' CHECK (atende_com_ia IN ('S','N')),
  canal_preferido   VARCHAR2(20),
  janela_contato    VARCHAR2(40),
  criado_em         TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

CREATE TABLE veiculo (
  veiculo_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cliente_id      NUMBER NOT NULL REFERENCES cliente,
  placa           VARCHAR2(10) NOT NULL UNIQUE,
  modelo          VARCHAR2(100),
  valor_carga_ref NUMBER(14,2),
  rastreador_id   VARCHAR2(50)
);

CREATE TABLE contato (
  contato_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cliente_id        NUMBER NOT NULL REFERENCES cliente,
  veiculo_id        NUMBER REFERENCES veiculo,
  nome              VARCHAR2(150) NOT NULL,
  papel             VARCHAR2(30) NOT NULL,
  telefone_e164     VARCHAR2(20) NOT NULL,
  ordem_acionamento NUMBER DEFAULT 1,
  senha_hash        VARCHAR2(128),
  senha_coacao_hash VARCHAR2(128),
  CONSTRAINT ck_contato_papel CHECK (papel IN ('MOTORISTA','GESTOR','EMERGENCIA'))
);

CREATE INDEX ix_contato_cliente ON contato (cliente_id, ordem_acionamento);

-- ===== Ocorrência: o objeto central do fluxo =====
CREATE TABLE ocorrencia (
  ocorrencia_id          VARCHAR2(40) PRIMARY KEY,
  evento_externo_id      VARCHAR2(100) NOT NULL,
  tipo_evento            VARCHAR2(50)  NOT NULL,
  criticidade            VARCHAR2(10)  NOT NULL,
  cliente_id             NUMBER REFERENCES cliente,
  veiculo_id             NUMBER REFERENCES veiculo,
  estado                 VARCHAR2(30)  NOT NULL,
  elegivel_ia            CHAR(1),
  motivo_inelegibilidade VARCHAR2(200),
  playbook_codigo        VARCHAR2(40),
  canal_atual            VARCHAR2(20),
  politica_versao        VARCHAR2(20),
  prompt_versao          VARCHAR2(20),
  desfecho               VARCHAR2(50),
  desfecho_justificativa VARCHAR2(1000),
  aberta_em              TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
  primeiro_contato_em    TIMESTAMP WITH TIME ZONE,
  encerrada_em           TIMESTAMP WITH TIME ZONE,
  payload_evento         CLOB CHECK (payload_evento IS JSON),
  CONSTRAINT uq_evento_externo UNIQUE (evento_externo_id),
  CONSTRAINT ck_ocorrencia_criticidade
    CHECK (criticidade IN ('BAIXA','MEDIA','ALTA','CRITICA'))
);

CREATE INDEX ix_ocorrencia_estado ON ocorrencia (estado, aberta_em);

-- ===== Política de elegibilidade: editável por supervisão, versionada =====
-- A IA nunca decide a própria elegibilidade (princípio 1). Quem autoriza é
-- este motor determinístico.
CREATE TABLE politica_evento (
  politica_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  versao               VARCHAR2(20) NOT NULL,
  tipo_evento          VARCHAR2(50) NOT NULL,
  criticidade          VARCHAR2(10) NOT NULL,
  elegivel_ia          CHAR(1)      NOT NULL,
  canal_preferido      VARCHAR2(20),
  playbook_codigo      VARCHAR2(40),
  condicoes            CLOB CHECK (condicoes IS JSON),
  desfechos_permitidos CLOB CHECK (desfechos_permitidos IS JSON),
  vigente_de           TIMESTAMP WITH TIME ZONE NOT NULL,
  vigente_ate          TIMESTAMP WITH TIME ZONE,
  ativo                CHAR(1) DEFAULT 'S'
);

CREATE INDEX ix_politica_lookup
  ON politica_evento (tipo_evento, criticidade, ativo, vigente_de);

-- ===== Auditoria IMUTÁVEL (Blockchain Table do 23ai) =====
-- ${AUDITORIA_DIAS_IDLE}: 0 em dev (permite recriar o schema), 16 em hml e
-- prd-poc. A tabela não pode ser alterada depois — mudar exige recriar,
-- e é justamente por isso que o valor não é fixo no arquivo.
--
-- ⛔ **16 é teto do Autonomous Database, não escolha.** O valor era 31, e o
--    ADB recusa: `ORA-05807: Blockchain or immutable table cannot have idle
--    retention greater than 16 days`. O banco em contêiner aceita 31 sem
--    reclamar, então a diferença só aparece no primeiro deploy na nuvem —
--    exatamente a armadilha 1 do doc 02, e ela pegou.
--
-- `momento` é TIMESTAMP puro, não TIMESTAMP WITH TIME ZONE: o Oracle recusa
-- esse tipo em blockchain table (ORA-05730). O horário é gravado sempre em
-- **UTC** via SYS_EXTRACT_UTC — a trilha de auditoria não pode depender do
-- fuso da sessão que escreveu.
CREATE BLOCKCHAIN TABLE auditoria_decisao (
  auditoria_id    NUMBER GENERATED ALWAYS AS IDENTITY,
  ocorrencia_id   VARCHAR2(40)  NOT NULL,
  momento         TIMESTAMP DEFAULT SYS_EXTRACT_UTC(SYSTIMESTAMP) NOT NULL,
  ator            VARCHAR2(30)  NOT NULL,
  ator_id         VARCHAR2(100),
  acao            VARCHAR2(60)  NOT NULL,
  detalhe         CLOB CHECK (detalhe IS JSON),
  politica_versao VARCHAR2(20),
  prompt_versao   VARCHAR2(20),
  modelo          VARCHAR2(60)
)
NO DROP UNTIL ${AUDITORIA_DIAS_IDLE} DAYS IDLE
NO DELETE LOCKED
HASHING USING "SHA2_512" VERSION "v1";

CREATE INDEX ix_auditoria_ocorrencia ON auditoria_decisao (ocorrencia_id, momento);

-- ===== Base de conhecimento vetorial (POPs, manuais, histórico) =====
CREATE TABLE kb_documento (
  doc_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  titulo        VARCHAR2(300) NOT NULL,
  tipo          VARCHAR2(40)  NOT NULL,
  tipo_evento   VARCHAR2(50),
  vigente       CHAR(1) DEFAULT 'S',
  atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

CREATE TABLE kb_chunk (
  chunk_id  NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  doc_id    NUMBER NOT NULL REFERENCES kb_documento,
  ordem     NUMBER NOT NULL,
  texto     CLOB   NOT NULL,
  embedding VECTOR(1024, FLOAT32)
);

-- ===== Consentimentos LGPD =====
CREATE TABLE consentimento_lgpd (
  consentimento_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  contato_id       NUMBER NOT NULL REFERENCES contato,
  finalidade       VARCHAR2(60) NOT NULL,
  base_legal       VARCHAR2(60) NOT NULL,
  status           VARCHAR2(20) NOT NULL,
  registrado_em    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
  evidencia        CLOB CHECK (evidencia IS JSON),
  CONSTRAINT ck_consentimento_status CHECK (status IN ('CONCEDIDO','REVOGADO'))
);

CREATE INDEX ix_consentimento_contato ON consentimento_lgpd (contato_id, finalidade);
