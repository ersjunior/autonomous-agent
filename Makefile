COMPOSE_FILE := infra/docker/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE)

.PHONY: up down logs migrate shell-backend test lint

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(COMPOSE) exec backend alembic upgrade head

shell-backend:
	$(COMPOSE) exec backend bash

test:
	$(COMPOSE) exec -T worker sh -c "pip install -q pytest && PYTHONPATH=/workspace:/workspace/backend pytest /workspace/backend /workspace/agents /workspace/worker -v" || [ $$? -eq 5 ]

lint:
	$(COMPOSE) exec -T worker sh -c "pip install -q ruff && ruff check /workspace/backend /workspace/agents /workspace/worker"
