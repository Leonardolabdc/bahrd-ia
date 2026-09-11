# ============================================================================
# Imagem única do back-end — api-gateway, workers e runner de migração.
#
# Princípio 10 (README) e doc 02 §3.4: a imagem que roda no notebook é a que
# roda na OCI. Nenhum `if ambiente == "dev"` aqui dentro — o que muda entre
# ambientes é o comando e as variáveis de ambiente, nunca a imagem.
#
# Multi-stage: builder compila os wheels, runtime recebe só o resultado.
# Usuário não-root, HEALTHCHECK, SIGTERM tratado (uvicorn/arq como PID 1 via exec).
# ============================================================================

# ─────────────────────────── stage 1 · builder ───────────────────────────
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# gcc/libaio: dependências de build de oracledb e aiomysql.
# libaio é a única que precisa sobreviver no runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libaio1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ ./src/

# --prefix isola o resultado para um COPY limpo no runtime
RUN pip install --prefix=/install .

# ─────────────────────────── stage 2 · runtime ───────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/app \
    PATH=/usr/local/bin:$PATH

# libaio1: runtime do python-oracledb em modo thick (se vier a ser necessário)
# curl: usado pelo HEALTHCHECK
RUN apt-get update \
 && apt-get install -y --no-install-recommends libaio1 curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=app:app src/ ./src/
COPY --chown=app:app migrations/ ./migrations/
COPY --chown=app:app prompts/ ./prompts/
# Os modelos aprovados na Meta. Não é só ferramenta de publicação: a aplicação
# lê o corpo deles para saber o texto que o cliente recebeu e não repeti-lo na
# primeira resposta da IA (integrations/mensageria/modelos.py).
COPY --chown=app:app infra/templates-whatsapp/ ./infra/templates-whatsapp/
# alembic.ini é obrigatório em runtime: é ele que aponta para migrations/mysql.
# pyproject.toml carrega a configuração do pytest e do ruff.
COPY --chown=app:app alembic.ini pyproject.toml ./

USER app

EXPOSE 8000

# O endpoint /saude/vivo não toca banco — responde enquanto o processo está vivo.
# Prontidão (dependências) é /saude/pronto, consultado pelo orquestrador, não aqui.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/saude/vivo || exit 1

# Forma exec: o processo recebe SIGTERM diretamente (obrigatório para o
# Kubernetes não cortar conversa no meio — doc 02 §3.4).
CMD ["uvicorn", "central_ia.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--timeout-graceful-shutdown", "30"]
