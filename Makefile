.PHONY: help env up up-external-s3 up-core build down clean restart logs ps status test test-cli install-cli

COMPOSE_BASE := docker compose -f docker-compose.yaml
COMPOSE_FULL := $(COMPOSE_BASE) -f docker-compose-api.yaml -f docker-compose-storage.yaml
COMPOSE_EXT_S3 := $(COMPOSE_BASE) -f docker-compose-api.yaml
COMPOSE_CORE_ONLY := $(COMPOSE_BASE) -f docker-compose-storage.yaml

help: ## Show available Make targets
	@echo "OGNA Core Stack — Makefile commands:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
	fi

up: env ## Stand up the full stack (Core + API + local RustFS S3)
	$(COMPOSE_FULL) up -d --build

up-external-s3: env ## Stand up Core + API using external S3 (no local RustFS)
	$(COMPOSE_EXT_S3) up -d --build

up-core: env ## Stand up Core + local RustFS S3 without the API container
	$(COMPOSE_CORE_ONLY) up -d --build

build: env ## Build local core images (gateway, migrations, hasura)
	$(COMPOSE_FULL) build

down: ## Stop all running services
	$(COMPOSE_FULL) down --remove-orphans

clean: ## Stop all services and delete volumes (wipes DB & Redis data)
	$(COMPOSE_FULL) down -v --remove-orphans

restart: ## Restart all services
	$(COMPOSE_FULL) restart

logs: ## Follow container logs (override service with SERVICE=api)
	$(COMPOSE_FULL) logs -f $(SERVICE)

ps: ## List running services and status
	$(COMPOSE_FULL) ps

status: ps ## Alias for `make ps`

install-cli: ## Install the `ogna` CLI locally in editable mode
	pip install -e .

test-cli: ## Run `ogna` CLI unit tests
	PYTHONPATH=. python3 test/test_cli.py

test: ## Run full integration test suite against running stack
	PYTHONPATH=. python3 -m unittest discover -s test -p "test_*.py" -v
