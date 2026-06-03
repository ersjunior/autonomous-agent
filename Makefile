COMPOSE_BASE := infra/docker/docker-compose.yml
COMPOSE_DEV := docker compose --env-file .env -f $(COMPOSE_BASE) -f infra/docker/docker-compose.dev.yml
COMPOSE_PROD := docker compose --env-file .env -f $(COMPOSE_BASE) -f infra/docker/docker-compose.prod.yml
COMPOSE := $(COMPOSE_DEV)

.PHONY: up down logs migrate shell-backend test lint prod-up prod-down prod-logs opensource-up opensource-down opensource-logs opensource-migrate wait-ollama pull-models warm-ollama setup-opensource

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
	docker exec autonomous-agent-ollama ollama pull $${OLLAMA_MODEL:-llama3.1}
	docker exec autonomous-agent-ollama ollama pull nomic-embed-text

opensource-migrate:
	$(COMPOSE_OPENSOURCE) exec backend alembic upgrade head

wait-ollama:
	@echo "Aguardando o Ollama responder (sem limite de tempo fixo)..."
	@n=0; until docker exec autonomous-agent-ollama ollama list >/dev/null 2>&1; do \
		n=$$((n+1)); \
		if [ $$n -gt 60 ]; then echo "❌ Ollama não respondeu após 5 min (60 tentativas)."; exit 1; fi; \
		echo "  ... ainda iniciando (tentativa $$n/60), aguardando 5s"; \
		sleep 5; \
	done
	@echo "✅ Ollama pronto."

warm-ollama:
	@echo "Pré-carregando o modelo na memória (warm-up para evitar cold start)..."
	@docker exec autonomous-agent-ollama ollama run $${OLLAMA_MODEL:-llama3.1} "ok" >/dev/null 2>&1 || true
	@echo "✅ Modelo aquecido."

setup-opensource: opensource-up
	@$(MAKE) wait-ollama
	@echo "Baixando modelos do Ollama..."
	@$(MAKE) pull-models
	@$(MAKE) warm-ollama
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
