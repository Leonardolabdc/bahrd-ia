# Equivalente ao dev.ps1, para quem estiver em Linux ou macOS.
# Os alvos são os mesmos — o time roda o mesmo compose nos dois sistemas.

.DEFAULT_GOAL := ajuda
.PHONY: ajuda setup up down reset build migrate logs ps shell test lint saude

ajuda:
	@echo "POC IA — Central de Monitoramento Bahrd · ambiente de desenvolvimento"
	@echo ""
	@echo "  make setup      cria o .env a partir do template"
	@echo "  make up         sobe a pilha"
	@echo "  make migrate    aplica as migrações"
	@echo "  make saude      consulta /saude/pronto"
	@echo "  make logs       acompanha api e worker"
	@echo "  make shell      bash dentro da imagem real"
	@echo "  make test       roda a suíte de testes"
	@echo "  make lint       roda o ruff"
	@echo "  make down       derruba (mantém os volumes)"
	@echo "  make reset      derruba E apaga os volumes"

setup:
	@test -f .env || (cp .env.example .env && echo ".env criado.")

up:
	docker compose up -d

down:
	docker compose down

reset:
	docker compose down -v

build:
	docker compose build

migrate:
	docker compose run --rm migrate

logs:
	docker compose logs -f api worker

ps:
	docker compose ps

shell:
	docker compose run --rm shell

test:
	docker compose run --rm --entrypoint sh shell -c "pip install --user -q pytest pytest-asyncio && python -m pytest -q"

lint:
	docker compose run --rm --entrypoint sh shell -c "pip install --user -q ruff && python -m ruff check --no-cache src migrations tests"

saude:
	curl -fsS http://localhost:8000/saude/pronto | python -m json.tool

# Publica no OCI Container Registry. NAMESPACE é obrigatório.
#   make publicar NAMESPACE=grxxxxxxxxx VERSAO=0.2.0
REGIAO ?= gru
REPO   ?= bahrd-ia
VERSAO ?= $(shell date +%Y.%m.%d-%H%M)

.PHONY: publicar
publicar:
	@test -n "$(NAMESPACE)" || (echo "defina NAMESPACE=<namespace do tenancy>"; exit 1)
	docker build -f docker/backend.Dockerfile --target runtime --platform linux/amd64 \
	  -t $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/backend:$(VERSAO) \
	  -t $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/backend:latest .
	docker build -f docker/web.Dockerfile --target runtime --platform linux/amd64 \
	  -t $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/web:$(VERSAO) \
	  -t $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/web:latest .
	docker push $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/backend:$(VERSAO)
	docker push $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/backend:latest
	docker push $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/web:$(VERSAO)
	docker push $(REGIAO).ocir.io/$(NAMESPACE)/$(REPO)/web:latest
	@echo "Aponte o deploy para as etiquetas COM VERSAO, nunca :latest."
