.PHONY: help env auth-info up up-external-s3 up-core build down clean restart logs ps status test test-cli install-cli

COMPOSE_BASE := docker compose -f docker-compose.yaml
COMPOSE_FULL := $(COMPOSE_BASE) -f docker-compose-api.yaml -f docker-compose-storage.yaml
COMPOSE_EXT_S3 := $(COMPOSE_BASE) -f docker-compose-api.yaml
COMPOSE_CORE_ONLY := $(COMPOSE_BASE) -f docker-compose-storage.yaml

help: ## Show available Make targets
	@echo "OGNA Core Stack — Makefile commands:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example (with generated secrets) if missing
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		gen() { openssl rand -hex "$$1" 2>/dev/null || python3 -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$$1"; }; \
		pg=$$(gen 24); \
		sed -i.bak \
			-e "s|^POSTGRES_PASSWORD=change_me.*|POSTGRES_PASSWORD=$$pg|" \
			-e "s|^POSTGRES_NON_ROOT_PASSWORD=change_me.*|POSTGRES_NON_ROOT_PASSWORD=$$pg|" \
			-e "s|^HASURA_GRAPHQL_ADMIN_SECRET=change_me.*|HASURA_GRAPHQL_ADMIN_SECRET=$$(gen 24)|" \
			-e "s|^OGNA_AUTH_ADMIN_PASSWORD=change_me.*|OGNA_AUTH_ADMIN_PASSWORD=$$(gen 14)Aa1!|" \
			-e "s|^ZITADEL_MASTERKEY=change_me.*|ZITADEL_MASTERKEY=$$(gen 16)|" \
			-e "s|^ZITADEL_DB_PASSWORD=change_me.*|ZITADEL_DB_PASSWORD=$$(gen 24)|" \
			-e "s|^ZITADEL_LOGIN_COOKIE_SECRET=change_me.*|ZITADEL_LOGIN_COOKIE_SECRET=$$(gen 24)|" \
			-e "s|^OGNA_INTERNAL_JWT_SECRET=change_me.*|OGNA_INTERNAL_JWT_SECRET=$$(gen 32)|" \
			.env && rm -f .env.bak; \
		echo "Created .env from .env.example with generated secrets"; \
		echo "Zitadel console: http://auth.localhost:8000/ui/console (login: $$(sed -n 's/^OGNA_AUTH_ADMIN_EMAIL=//p' .env), password in .env)"; \
	fi

auth-info: ## Show the OIDC issuer and client id for your frontends
	@docker run --rm --volumes-from zitadel-setup alpine cat /zitadel/bootstrap/web-client.json

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

clean: ## Stop all services and delete volumes (wipes DB data)
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
