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
      - auth
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
      OGNA_INTERNAL_JWT_SECRET: ${OGNA_INTERNAL_JWT_SECRET:?OGNA_INTERNAL_JWT_SECRET must be set}
      OGNA_AUTH_DOMAIN: ${OGNA_AUTH_DOMAIN:-auth.localhost}
      OGNA_AUTH_EXTERNAL_SECURE: ${OGNA_AUTH_EXTERNAL_SECURE:-false}
      OGNA_AUTH_ACTIVE_CACHE_TTL: ${OGNA_AUTH_ACTIVE_CACHE_TTL:-5}
      OGNA_AUTH_INACTIVE_CACHE_TTL: ${OGNA_AUTH_INACTIVE_CACHE_TTL:-300}
      OGNA_INTERNAL_JWT_TTL: ${OGNA_INTERNAL_JWT_TTL:-300}
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
    volumes:
      - zitadel_bootstrap:/zitadel/bootstrap:ro
    depends_on:
      zitadel-setup:
        condition: service_completed_successfully

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

  zitadel:
    image: ghcr.io/zitadel/zitadel:v4.16.0
    container_name: zitadel
    restart: unless-stopped
    user: "0"
    command: start-from-init --masterkeyFromEnv
    environment:
      ZITADEL_MASTERKEY: ${ZITADEL_MASTERKEY:?ZITADEL_MASTERKEY must be set (exactly 32 characters)}
      ZITADEL_PORT: 8080
      ZITADEL_EXTERNALDOMAIN: ${OGNA_AUTH_DOMAIN:-auth.localhost}
      ZITADEL_EXTERNALPORT: ${OGNA_AUTH_EXTERNAL_PORT:-8000}
      ZITADEL_EXTERNALSECURE: ${OGNA_AUTH_EXTERNAL_SECURE:-false}
      ZITADEL_TLS_ENABLED: "false"
      # Own database + unprivileged user, created on first start with the admin login
      ZITADEL_DATABASE_POSTGRES_HOST: postgres
      ZITADEL_DATABASE_POSTGRES_PORT: 5432
      ZITADEL_DATABASE_POSTGRES_DATABASE: zitadel
      ZITADEL_DATABASE_POSTGRES_USER_USERNAME: zitadel
      ZITADEL_DATABASE_POSTGRES_USER_PASSWORD: ${ZITADEL_DB_PASSWORD:?ZITADEL_DB_PASSWORD must be set}
      ZITADEL_DATABASE_POSTGRES_USER_SSL_MODE: disable
      ZITADEL_DATABASE_POSTGRES_ADMIN_USERNAME: ${POSTGRES_USER}
      ZITADEL_DATABASE_POSTGRES_ADMIN_PASSWORD: ${POSTGRES_PASSWORD}
      ZITADEL_DATABASE_POSTGRES_ADMIN_SSL_MODE: disable
      # First instance: organization, human admin (console login) and service accounts
      ZITADEL_FIRSTINSTANCE_INSTANCENAME: OGNA
      ZITADEL_FIRSTINSTANCE_ORG_NAME: ${OGNA_AUTH_ORG_NAME:-OGNA}
      ZITADEL_FIRSTINSTANCE_ORG_HUMAN_USERNAME: ${OGNA_AUTH_ADMIN_EMAIL:-admin@example.com}
      ZITADEL_FIRSTINSTANCE_ORG_HUMAN_EMAIL_ADDRESS: ${OGNA_AUTH_ADMIN_EMAIL:-admin@example.com}
      ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD: ${OGNA_AUTH_ADMIN_PASSWORD:?OGNA_AUTH_ADMIN_PASSWORD must be set}
      ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORDCHANGEREQUIRED: "false"
      ZITADEL_FIRSTINSTANCE_PATPATH: /zitadel/bootstrap/admin.pat
      ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINE_USERNAME: ogna-setup
      ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINE_NAME: OGNA setup (IAM_OWNER)
      ZITADEL_FIRSTINSTANCE_ORG_MACHINE_PAT_EXPIRATIONDATE: "2099-01-01T00:00:00Z"
      ZITADEL_FIRSTINSTANCE_LOGINCLIENTPATPATH: /zitadel/bootstrap/login-client.pat
      ZITADEL_FIRSTINSTANCE_ORG_LOGINCLIENT_MACHINE_USERNAME: login-client
      ZITADEL_FIRSTINSTANCE_ORG_LOGINCLIENT_MACHINE_NAME: Automatically Initialized IAM_LOGIN_CLIENT
      ZITADEL_FIRSTINSTANCE_ORG_LOGINCLIENT_PAT_EXPIRATIONDATE: "2099-01-01T00:00:00Z"
      # Instance defaults (applied when the instance is first created)
      ZITADEL_DEFAULTINSTANCE_LOGINPOLICY_ALLOWREGISTER: ${OGNA_AUTH_ALLOW_REGISTER:-true}
      ZITADEL_DEFAULTINSTANCE_LOCKOUTPOLICY_MAXPASSWORDATTEMPTS: ${OGNA_AUTH_MAX_PASSWORD_ATTEMPTS:-0}
      # Login V2 (separate Next.js container), served under /ui/v2/login on the auth domain
      ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_REQUIRED: "true"
      ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_BASEURI: ${OGNA_AUTH_PUBLIC_SCHEME:-http}://${OGNA_AUTH_DOMAIN:-auth.localhost}:${OGNA_AUTH_EXTERNAL_PORT:-8000}/ui/v2/login/
      ZITADEL_OIDC_DEFAULTLOGINURLV2: ${OGNA_AUTH_PUBLIC_SCHEME:-http}://${OGNA_AUTH_DOMAIN:-auth.localhost}:${OGNA_AUTH_EXTERNAL_PORT:-8000}/ui/v2/login/login?authRequest=
      ZITADEL_OIDC_DEFAULTLOGOUTURLV2: ${OGNA_AUTH_PUBLIC_SCHEME:-http}://${OGNA_AUTH_DOMAIN:-auth.localhost}:${OGNA_AUTH_EXTERNAL_PORT:-8000}/ui/v2/login/logout?post_logout_redirect=
      ZITADEL_SAML_DEFAULTLOGINURLV2: ${OGNA_AUTH_PUBLIC_SCHEME:-http}://${OGNA_AUTH_DOMAIN:-auth.localhost}:${OGNA_AUTH_EXTERNAL_PORT:-8000}/ui/v2/login/login?samlRequest=
    healthcheck:
      test: ["CMD", "/app/zitadel", "ready"]
      interval: 10s
      timeout: 30s
      retries: 12
      start_period: 30s
    volumes:
      - zitadel_bootstrap:/zitadel/bootstrap:rw
    networks:
      - auth
      - database
    depends_on:
      postgres:
        condition: service_healthy

  zitadel-login:
    image: ghcr.io/zitadel/zitadel-login:v4.16.0
    container_name: zitadel-login
    restart: unless-stopped
    user: "0"
    environment:
      ZITADEL_API_URL: http://zitadel:8080
      NEXT_PUBLIC_BASE_PATH: /ui/v2/login
      ZITADEL_SERVICE_USER_TOKEN_FILE: /zitadel/bootstrap/login-client.pat
      ZITADEL_SESSION_COOKIE_SECRET: ${ZITADEL_LOGIN_COOKIE_SECRET:?ZITADEL_LOGIN_COOKIE_SECRET must be set}
      CUSTOM_REQUEST_HEADERS: Host:${OGNA_AUTH_DOMAIN:-auth.localhost},X-Forwarded-Proto:${OGNA_AUTH_PUBLIC_SCHEME:-http}
    healthcheck:
      test: ["CMD", "/bin/sh", "-c", "node /app/healthcheck.mjs http://localhost:3000/ui/v2/login/healthy"]
      interval: 10s
      timeout: 30s
      retries: 12
      start_period: 20s
    volumes:
      - zitadel_bootstrap:/zitadel/bootstrap:ro
    networks:
      - auth
    depends_on:
      zitadel:
        condition: service_healthy

  zitadel-setup:
    image: ${OGNA_ZITADEL_SETUP_IMAGE:-ghcr.io/ognastack/zitadel-setup:main}
    container_name: zitadel-setup
    restart: on-failure
    environment:
      OGNA_AUTH_DOMAIN: ${OGNA_AUTH_DOMAIN:-auth.localhost}
      OGNA_AUTH_EXTERNAL_PORT: ${OGNA_AUTH_EXTERNAL_PORT:-8000}
      OGNA_AUTH_EXTERNAL_SECURE: ${OGNA_AUTH_EXTERNAL_SECURE:-false}
      OGNA_AUTH_PROJECT_NAME: ${OGNA_AUTH_PROJECT_NAME:-OGNA}
      OGNA_OIDC_REDIRECT_URIS: ${OGNA_OIDC_REDIRECT_URIS:-http://localhost:8000/auth/callback,http://localhost:3000/auth/callback,http://localhost:5173/auth/callback}
      OGNA_OIDC_POST_LOGOUT_URIS: ${OGNA_OIDC_POST_LOGOUT_URIS:-http://localhost:8000/,http://localhost:3000/,http://localhost:5173/}
    volumes:
      - zitadel_bootstrap:/zitadel/bootstrap:rw
      - zitadel_public:/zitadel/public:rw
    networks:
      - auth
    depends_on:
      zitadel:
        condition: service_healthy

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
      DBMATE_MIGRATIONS_DIR: "/db/migrations"
      DBMATE_NO_DUMP_SCHEMA: "true"
    depends_on:
      postgres:
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
      # Storage verifies the gateway's internal token (variable name kept for the storage image)
      GOTRUE_JWT_SECRET: ${OGNA_INTERNAL_JWT_SECRET}
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
    volumes:
      - zitadel_public:/zitadel/public:ro

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
          "key": "${OGNA_INTERNAL_JWT_SECRET}",
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
  zitadel_bootstrap:
    driver: local
  zitadel_public:
    driver: local
  postgres_data:
    driver: local
  temp_files:
    driver: local

networks:
  auth:
    driver: bridge
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
API_EXTERNAL_URL="localhost:8000"
API_IMAGE="{api_image}"
OGNA_EXTRA_ROUTES=""
STORAGE_TYPE="S3"
S3_SECRET_KEY={s3_secret}
S3_ENDPOINT_URL=http://rustfs:9000
S3_ACCESS_KEY=rustfsadmin
HASURA_GRAPHQL_ADMIN_SECRET={hasura_secret}

# --- Identity (Zitadel) ---
# Public hostname of the identity provider; *.localhost resolves to this machine in browsers.
OGNA_AUTH_DOMAIN=auth.localhost
OGNA_AUTH_EXTERNAL_PORT=8000
OGNA_AUTH_EXTERNAL_SECURE=false
OGNA_AUTH_PUBLIC_SCHEME=http
OGNA_AUTH_ADMIN_EMAIL=admin@example.com
OGNA_AUTH_ADMIN_PASSWORD={auth_admin_password}
# Exactly 32 characters; encrypts Zitadel's secrets at rest. Never change or lose it.
ZITADEL_MASTERKEY={zitadel_masterkey}
ZITADEL_DB_PASSWORD={zitadel_db_password}
ZITADEL_LOGIN_COOKIE_SECRET={zitadel_cookie_secret}
# Signs the short-lived tokens the gateway forwards to Hasura, Storage and your API.
OGNA_INTERNAL_JWT_SECRET={internal_jwt_secret}
# OIDC app "ogna-web" (created by zitadel-setup): where your frontends redirect after login/logout
OGNA_OIDC_REDIRECT_URIS=http://localhost:8000/auth/callback,http://localhost:3000/auth/callback,http://localhost:5173/auth/callback
OGNA_OIDC_POST_LOGOUT_URIS=http://localhost:8000/,http://localhost:3000/,http://localhost:5173/
# Per-IP limit on Zitadel's token endpoint. Raise for the integration test suite.
OGNA_AUTH_RATE_LIMIT_MINUTE=10
OGNA_AUTH_RATE_LIMIT_HOUR=100
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
