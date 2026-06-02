COMPOSE_BASE := infra/docker/docker-compose.yml
COMPOSE_DEV := docker compose --env-file .env -f $(COMPOSE_BASE) -f infra/docker/docker-compose.dev.yml
COMPOSE_PROD := docker compose --env-file .env -f $(COMPOSE_BASE) -f infra/docker/docker-compose.prod.yml
COMPOSE := $(COMPOSE_DEV)

.PHONY: up down logs migrate shell-backend test lint prod-up prod-down prod-logs opensource-up opensource-down opensource-logs opensource-migrate pull-models setup-opensource

up:
	$(COMPOSE) up -d --build

COMPOSE_OPENSOURCE := docker compose --env-file .env.local -f $(COMPOSE_BASE) --profile opensource

opensource-up:
	$(COMPOSE_OPENSOURCE) up -d --build

opensource-down:
	$(COMPOSE_OPENSOURCE) down

opensource-logs:
	$(COMPOSE_OPENSOURCE) logs -f

pull-models:
	docker exec autonomous-agent-ollama ollama pull ${OLLAMA_MODEL:-llama3.1}
	docker exec autonomous-agent-ollama ollama pull nomic-embed-text

opensource-migrate:
	$(COMPOSE_OPENSOURCE) exec backend alembic upgrade head

setup-opensource: opensource-up
	@echo "Aguardando serviços iniciarem (30s)..."
	@sleep 30
	@$(MAKE) pull-models
	@$(MAKE) opensource-migrate
	@echo "✅ Stack opensource pronta!"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(COMPOSE) exec backend alembic upgrade head

shell-backend:
	$(COMPOSE) exec backend bash

test:
	$(COMPOSE) exec -T worker sh -c "pip install -q pytest && PYTHONPATH=/workspace:/workspace/backend:/workspace/worker pytest /workspace/backend /workspace/agents /workspace/worker -v" || [ $$? -eq 5 ]

lint:
	$(COMPOSE) exec -T worker sh -c "pip install -q ruff && ruff check /workspace/backend /workspace/agents /workspace/worker"

prod-up:
	$(COMPOSE_PROD) up -d --build

prod-down:
	$(COMPOSE_PROD) down

prod-logs:
	$(COMPOSE_PROD) logs -f
