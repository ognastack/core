"""Bundled templates for `ogna init` and `.ogna/` runtime files."""

CORE_COMPOSE_YAML = """services:
  kong-cp:
    image: ${OGNA_GATEWAY_IMAGE:-ghcr.io/ognastack/gateway:main}
    container_name: kong-cp
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    networks:
      - api
      - database
    environment:
      KONG_PLUGINS: bundled,cors,acme,ogna-guard
      KONG_HEADERS: "off"
      KONG_LUA_SSL_TRUSTED_CERTIFICATE: system
      KONG_NGINX_HTTP_LUA_SHARED_DICT: acme_storage 10m
      KONG_PROXY_ACCESS_LOG: /dev/stdout
      KONG_ADMIN_ACCESS_LOG: /dev/stdout
      KONG_PROXY_ERROR_LOG: /dev/stderr
      KONG_ADMIN_ERROR_LOG: /dev/stderr
      KONG_LOG_LEVEL: ${KONG_LOG_LEVEL:-notice}
      KONG_DATABASE: "off"
      KONG_DECLARATIVE_CONFIG: /kong/kong.yaml
      GOTRUE_JWT_SECRET: ${GOTRUE_JWT_SECRET:?GOTRUE_JWT_SECRET must be set}
      POSTGRES_DB: ${POSTGRES_DB}
      OGNA_GATEWAY_DB_PASSWORD: ${OGNA_GATEWAY_DB_PASSWORD}
      OGNA_EXTRA_ROUTES: ${OGNA_EXTRA_ROUTES:-}
      OGNA_CORS_ORIGINS: ${OGNA_CORS_ORIGINS:-}
      OGNA_AUTH_RATE_LIMIT_MINUTE: ${OGNA_AUTH_RATE_LIMIT_MINUTE:-10}
      OGNA_AUTH_RATE_LIMIT_HOUR: ${OGNA_AUTH_RATE_LIMIT_HOUR:-100}
      KONG_PROXY_LISTEN: 0.0.0.0:8000, 0.0.0.0:8443 ssl
    ports:
      - "${OGNA_HTTP_PORT:-80}:8000"
      - "${OGNA_HTTPS_PORT:-443}:8443"
      - "${OGNA_GATEWAY_PORT:-8000}:8000"
    healthcheck:
      test: ["CMD", "kong", "health"]
      interval: 10s
      timeout: 10s
      retries: 10
      start_period: 30s

  db-init:
    image: ${OGNA_MIGRATIONS_IMAGE:-ghcr.io/ognastack/migrations:main}
    container_name: db-init
    environment:
      DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}?sslmode=disable
    depends_on:
      postgres:
        condition: service_healthy
    command: init
    restart: on-failure
    networks:
      - database

  gotrue:
    image: supabase/auth:v2.178.0
    environment:
      GOTRUE_DISABLE_SIGNUP: ${GOTRUE_DISABLE_SIGNUP:-false}
      GOTRUE_MAILER_AUTOCONFIRM: ${GOTRUE_MAILER_AUTOCONFIRM:-true}
      GOTRUE_URI_ALLOW_LIST: ${GOTRUE_URI_ALLOW_LIST:-}
      GOTRUE_API_HOST: "0.0.0.0"
      GOTRUE_API_PORT: 9999
      GOTRUE_DB_DRIVER: "postgres"
      GOTRUE_JWT_AUD: "authenticated"
      GOTRUE_JWT_EXP: ${GOTRUE_JWT_EXP:-3600}
      GOTRUE_JWT_DEFAULT_GROUP_NAME: "authenticated"
      GOTRUE_JWT_SECRET: ${GOTRUE_JWT_SECRET}
      GOTRUE_SITE_URL: ${GOTRUE_SITE_URL:-http://localhost}
      DATABASE_URL: "postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}?search_path=auth"
    expose:
      - "9999"
    depends_on:
      postgres:
        condition: service_healthy
      db-init:
        condition: service_completed_successfully
    networks:
      - api
      - database
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9999/health"]
      interval: 5s
      timeout: 3s
      retries: 5

  postgres:
    image: postgres:18.1-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    expose:
      - "5432"
    networks:
      - database
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "pg_isready -U ${POSTGRES_USER:-ogna_user} -d ${POSTGRES_DB:-ogna_db}",
        ]
      interval: 5s
      timeout: 10s
      retries: 10
      start_period: 10s
    restart: unless-stopped

  migrations:
    image: ${OGNA_MIGRATIONS_IMAGE:-ghcr.io/ognastack/migrations:main}
    container_name: migrations
    environment:
      DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}?sslmode=disable
      DBMATE_MIGRATIONS_TABLE: migrations.schema_migrations
      OGNA_GATEWAY_DB_PASSWORD: ${OGNA_GATEWAY_DB_PASSWORD}
      DBMATE_MIGRATIONS_DIR: "/db/migrations"
      DBMATE_NO_DUMP_SCHEMA: "true"
    depends_on:
      postgres:
        condition: service_healthy
      gotrue:
        condition: service_healthy
    command: up
    restart: on-failure
    networks:
      - database


  storage:
    image: ghcr.io/ognastack/storage:latest
    environment:
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_ENDPOINT_URL: ${S3_ENDPOINT_URL}
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      DATABASE_URL: postgres
      DATABASE_PORT: 5432
      DATABASE_USERNAME: ${POSTGRES_USER}
      DATABASE_PASSWORD: ${POSTGRES_PASSWORD}
      DATABASE_NAME: ${POSTGRES_DB}
      STORAGE_TYPE: ${STORAGE_TYPE:-S3}
      GOTRUE_JWT_SECRET: ${GOTRUE_JWT_SECRET}
      GRAPHQL_HOST: "http://hasura:8080"
      GRAPHQL_ENDPOINT: "v1/graphql"
      GRAPHQL_SECRET: ${HASURA_GRAPHQL_ADMIN_SECRET}
    volumes:
      - temp_files:/tmp
    expose:
      - "8000"
    depends_on:
      postgres:
        condition: service_healthy
      hasura:
        condition: service_started
    networks:
      - storage
      - gql
      - api

  dashboard:
    image: ghcr.io/ognastack/ogna-fe-template:latest
    expose:
      - "3000"
    depends_on:
      kong-cp:
        condition: service_healthy
    networks:
      - api

  hasura:
    image: ${OGNA_HASURA_IMAGE:-ghcr.io/ognastack/hasura:main}
    container_name: hasura
    expose:
      - "8080"
    ports:
      - "127.0.0.1:${HASURA_CONSOLE_PORT:-8080}:8080"
    networks:
      - gql
      - database
    environment:
      HASURA_GRAPHQL_DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      HASURA_GRAPHQL_ADMIN_SECRET: ${HASURA_GRAPHQL_ADMIN_SECRET}
      HASURA_GRAPHQL_ENABLE_CONSOLE: ${HASURA_GRAPHQL_ENABLE_CONSOLE:-false}
      HASURA_GRAPHQL_UNAUTHORIZED_ROLE: anonymous
      HASURA_GRAPHQL_DEV_MODE: ${HASURA_GRAPHQL_DEV_MODE:-false}
      HASURA_GRAPHQL_METADATA_DIR: /tmp/hasura-metadata
      HASURA_GRAPHQL_JWT_SECRET: >
        {
          "type": "HS256",
          "key": "${GOTRUE_JWT_SECRET}",
          "claims_map": {
            "x-hasura-user-id": { "path": "$.sub" },
            "x-hasura-default-role": { "path": "$.role" },
            "x-hasura-allowed-roles": ["authenticated"]
          }
        }
    depends_on:
      postgres:
        condition: service_healthy
      migrations:
        condition: service_completed_successfully

volumes:
  postgres_data:
    driver: local
  temp_files:
    driver: local

networks:
  storage:
    driver: bridge
  database:
    driver: bridge
  gql:
    driver: bridge
  api:
    driver: bridge
"""

STORAGE_COMPOSE_YAML = """services:
  rustfs:
    image: rustfs/rustfs
    container_name: rustfs
    restart: unless-stopped
    environment:
      RUSTFS_ACCESS_KEY: ${S3_ACCESS_KEY:-rustfsadmin}
      RUSTFS_SECRET_KEY: ${S3_SECRET_KEY:-rustfsadmin}
    expose:
      - "9000"
    networks:
      - storage
"""

USER_COMPOSE_IMAGE_YAML = """# Your application services & overrides.
# - Swap your primary backend image anytime via `API_IMAGE` in .env or `ogna set-api <image>`
# - Add additional services (workers, microservices, queues, vector DBs) below or via `ogna add-service`
services:
  migrations:
    volumes:
      - ./migrations:/db/migrations:ro

  hasura:
    volumes:
      - ./hasura/tables:/user-hasura/tables:ro

  api:
    image: ${API_IMAGE:-ogna-py-appi:prod}
    container_name: api
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    depends_on:
      - postgres
      - kong-cp
    expose:
      - "8000"
    networks:
      - gql
      - api
    env_file:
      - .env
"""

USER_COMPOSE_BUILD_YAML = """# Your application services & overrides.
# - Swap to any pre-built image via `image: ${API_IMAGE}` or build locally from `./api`
# - Add additional services (workers, microservices, queues, vector DBs) below or via `ogna add-service`
services:
  migrations:
    volumes:
      - ./migrations:/db/migrations:ro

  hasura:
    volumes:
      - ./hasura/tables:/user-hasura/tables:ro

  api:
    image: ${API_IMAGE:-ogna-local-api:dev}
    build:
      context: ./api
    container_name: api
    restart: unless-stopped
    depends_on:
      - postgres
      - kong-cp
    expose:
      - "8000"
    networks:
      - gql
      - api
    env_file:
      - .env
"""

ENV_TEMPLATE = """POSTGRES_USER=ogna_user
POSTGRES_PASSWORD={postgres_password}
POSTGRES_DB={project_db}
POSTGRES_NON_ROOT_USER=ogna_user
POSTGRES_NON_ROOT_PASSWORD={postgres_password}
ENCRYPTION_KEY={encryption_key}
GOTRUE_JWT_SECRET={jwt_secret}
API_EXTERNAL_URL="localhost:8000"
API_IMAGE="{api_image}"
OGNA_EXTRA_ROUTES=""
STORAGE_TYPE="S3"
S3_SECRET_KEY={s3_secret}
S3_ENDPOINT_URL=http://rustfs:9000
S3_ACCESS_KEY=rustfsadmin
GOTRUE_JWT_EXP=3600
OGNA_GATEWAY_DB_PASSWORD={gateway_db_password}
HASURA_GRAPHQL_ADMIN_SECRET={hasura_secret}
"""

GITIGNORE_TEMPLATE = """# Environment & secrets
.env
.env.local
secrets/

# OGNA internal runtime compose files (regenerated by `ogna up`)
.ogna/

# Python / OS artifacts
__pycache__/
*.py[cod]
.venv/
venv/
.DS_Store
.idea/
logs/
"""

STARTER_API_DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

STARTER_API_REQUIREMENTS = """fastapi>=0.115.0
uvicorn[standard]>=0.32.0
"""

STARTER_API_MAIN = """from fastapi import FastAPI

app = FastAPI(title="OGNA App API", root_path="/api")


@app.get("/v1/health/")
async def health():
    return {"status": "healthy"}
"""

STARTER_MIGRATION_SQL = """-- migrate:up
-- Add your application tables here. Example:
-- CREATE TABLE IF NOT EXISTS public.items (
--     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--     name TEXT NOT NULL,
--     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
-- );

-- migrate:down
"""

STARTER_README = """# {project_name}

Built on the **OGNA Backend Stack**.

## Project Structure

```text
.
├── migrations/           # Your SQL database migrations (auto-applied on startup)
├── docker-compose.yaml   # Pluggable `api` container definition & migrations mount
└── .env                  # Environment variables, API_IMAGE, & generated secrets
```

## Swapping Your Backend API Container

Your backend can be written in **any language or framework** as long as its container listens on port `8000`.
Swap the backend image anytime:

```bash
# Switch the API Docker image in .env
ogna set-api my-org/my-go-backend:latest

# Or start directly with a specific image override
ogna up -d --api-image my-org/my-rust-backend:v2
```

## Quickstart

Start the full stack:

```bash
ogna up -d
```

View logs:

```bash
ogna logs -f
```

Create a new database migration:

```bash
ogna migration new create_users_profile
```

Stop the stack:

```bash
ogna down
```
"""
