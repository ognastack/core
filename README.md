# OGNA Backend Stack

OGNA is an **open-source Firebase alternative** built as a modular, Docker-first backend stack.
It provides the essential building blocks required to run a modern backend while allowing **full freedom over your application logic and technology choices**.

---

## Why OGNA? (Pluggable Backend Container)

Most Firebase alternatives tightly couple your backend logic to Postgres + REST/GraphQL, limiting how you build and scale your application.

OGNA is different by design:

- **Swap your backend container anytime** — Your backend is just a Docker image (`API_IMAGE`) exposing port `8000` internally.
- **Any language or framework** — Use Go, Rust, Python, Node.js, Java, C#, or anything that runs in a container.
- **Zero auth boilerplate in your backend** — Kong checks every token with the identity provider (so logged-out or revoked tokens stop working within seconds), forwards the verified user as `X-Authenticated-*` headers plus a short-lived signed token, and enforces rate limits before requests ever reach `/api/*`.

---

## What OGNA Provides

- **Database** — PostgreSQL 18.1
- **Authentication** — [Zitadel](https://zitadel.com) v4: OIDC/OAuth 2, SAML, MFA, passkeys, social logins, organizations (multi-tenancy), admin console and a full audit trail
- **Storage** — S3-compatible object storage (`ghcr.io/ognastack/storage:latest` + local RustFS or external S3)
- **API Gateway** — Kong (`ghcr.io/ognastack/gateway`) for routing, token checks (introspection), and rate limiting
- **GraphQL Engine** — Hasura (`ghcr.io/ognastack/hasura`) pre-configured with storage metadata, reading the gateway's internal token
- **Database Migrations** — Automated core + user SQL migrations (`ghcr.io/ognastack/migrations` powered by `dbmate`)
- **Pluggable Backend** — Bring your own backend Docker image (`API_IMAGE`)

---

## How It Works

OGNA separates **core infrastructure** from **your application container & migrations**:

1. **Swappable Backend Container (`api`)**:
   - Defined in `docker-compose.yaml` (or `docker-compose-api.yaml` in `core`) using `image: ${API_IMAGE:-ogna-py-appi:prod}`.
   - You can swap the backend container at any time via `ogna set-api <image>`, `ogna up --api-image <image>`, or by changing `API_IMAGE` in `.env`.
2. **Self-Contained Core Images (No Submodule Needed)**:
   - **Gateway (`ghcr.io/ognastack/gateway`)**: Packages Kong Gateway, the `ogna-guard` Lua plugin (strips spoofable internal headers, checks bearer tokens with Zitadel, forwards the verified user, adds security headers), and `kong.yaml`.
   - **Zitadel setup (`ghcr.io/ognastack/zitadel-setup`)**: One-shot job that creates the `OGNA` project, the gateway's introspection client and the `ogna-web` OIDC app in Zitadel. Safe to re-run.
   - **Migrations (`ghcr.io/ognastack/migrations`)**: Pre-initializes `auth` and `migrations` schemas (`db-init`), automatically runs OGNA's internal migrations, and then applies **your project's SQL migrations** from `./migrations`.
   - **Hasura (`ghcr.io/ognastack/hasura`)**: Packages Hasura GraphQL Engine with OGNA's storage permissions and metadata pre-loaded.

---

## 1. Creating a Project (Using the `ogna` CLI)

This is the recommended workflow when running a project on top of OGNA—no Git submodule or infrastructure config folders needed.

### Step 1: Install the `ogna` CLI

```bash
# Via pipx (recommended)
pipx install git+https://github.com/ognastack/core.git

# Or via pip from a local clone of this repo
pip install -e .
```

### Step 2: Initialize Your Project (`ogna init`)

Initialize a project pointing to your backend Docker image:

```bash
ogna init my-app --api-image my-org/my-backend:latest
cd my-app
```

*(Optional: pass `--scaffold-api` if you want `ogna init` to also generate a starter `./api` Dockerfile directory.)*

This creates a clean directory with cryptographically generated secrets in `.env`:

```text
my-app/
├── migrations/                 # Strictly your application's SQL migrations
│   └── 20260101000000_init.sql
├── hasura/
│   └── tables/                 # Your custom Hasura table/permission YAML files (auto-merged with core)
├── docker-compose.yaml         # Pluggable `api` service (`image: ${API_IMAGE}`) & mounts
├── .env                        # Auto-generated secrets + API_IMAGE (gitignored)
├── .env.example                # Safe template to commit to git
├── .gitignore                  # Ignores .env and .ogna/
└── README.md
```

### Step 3: Swap Your API Container Anytime

Your backend container only needs to listen on port **`8000`** (do not publish it publicly; Kong routes `/api/*` to `http://api:8000`).

You can swap your backend Docker image at any time:

```bash
# 1. Update API_IMAGE in .env
ogna set-api my-org/my-go-api:v2

# 2. Update API_IMAGE and immediately restart the running `api` container in-place
ogna set-api my-org/my-rust-api:latest --restart

# 3. Or specify the image directly when starting the stack
ogna up -d --api-image my-org/my-node-api:dev
```

### Step 4: Add Additional Services to the Stack

You can extend the stack with as many extra containers as you need—such as additional microservices, background workers, message queues, or vector databases.

#### Option A: Via the CLI (`ogna add-service`)

```bash
# 1. Add a token-protected microservice exposed through Kong at /payments
ogna add-service payments --image my-org/payments-api:latest --port 8000 --route /payments

# 2. Add a public microservice exposed through Kong at /webhooks (no token required)
ogna add-service webhooks --image my-org/webhooks-service:latest --port 8080 --route /webhooks --public

# 3. Add an internal/background service (e.g. worker or vector DB, not exposed on Kong)
ogna add-service worker --image my-org/celery-worker:latest
```

When `--route` is provided, `ogna` appends the service to `docker-compose.yaml` **and** updates `OGNA_EXTRA_ROUTES` in `.env` so Kong automatically routes traffic to it.

#### Option B: Manually in `docker-compose.yaml`

Your project's `docker-compose.yaml` is standard Docker Compose merged with OGNA Core. You can add any service directly and attach it to OGNA's internal networks (`api`, `database`, `gql`, `storage`):

```yaml
services:
  migrations:
    volumes:
      - ./migrations:/db/migrations:ro

  api:
    image: ${API_IMAGE:-ogna-py-appi:prod}
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
      - database
    env_file:
      - .env

  # Example: Add a Qdrant vector database or background worker
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    expose:
      - "6333"
    networks:
      - api
      - database
```

### Step 5: Add Database Migrations & Track Tables in Hasura

In OGNA, application services (`api`, `storage`, and custom microservices) do **not** connect directly to Postgres—all data access goes through **Hasura (`http://hasura:8080/v1/graphql`)**, which enforces row-level and column-level permissions per user (from the gateway's internal token).

#### 1. Create a SQL Migration (`ogna migration new`)

```bash
ogna migration new create_profiles_table
```

Edit `./migrations/<timestamp>_create_profiles_table.sql`:

```sql
-- migrate:up
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    username TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- migrate:down
DROP TABLE IF EXISTS public.profiles;
```

#### 2. Track the Table & Permissions in Hasura (`ogna track-table`)

Generate a Hasura table metadata file in `./hasura/tables/` (which OGNA automatically merges with core `storage` metadata on startup):

```bash
# Scope row-level select/insert/update/delete permissions to the logged-in user (X-Hasura-User-Id)
ogna track-table public.profiles --owner-column user_id

# Or allow all authenticated users to query/mutate specific columns
ogna track-table public.items --columns id,name,created_at
```

#### 3. Optional: Use the Visual Hasura Admin Console (`ogna console`)

For security, the Hasura Console is disabled by default. During local development, you can enable it on `http://127.0.0.1:8080/console` (bound strictly to localhost):

```bash
# Enable console, print the Admin Secret, and restart Hasura
ogna console --restart

# Disable console when finished
ogna console --disable --restart
```

### Step 6: Start, Inspect, and Stop the Stack

```bash
# Start all services in the background
ogna up -d

# Or start with an external S3 provider (skips local RustFS container)
ogna up -d --external-s3

# Check container status and gateway URLs
ogna status

# Stream logs (all services or just your `api` container)
ogna logs -f
ogna logs -f api

# Stop the stack
ogna down
```

---

## 2. Running the `core` Repository Directly

Use this workflow if you are developing `core` itself or running directly via `docker compose` without the CLI.

### Step 1: Clone `core` and Configure `.env`

```bash
git clone https://github.com/ognastack/core.git
cd core
make env   # copies .env.example to .env and generates every secret
```

`make env` replaces each `change_me` placeholder with a random value. If you copy `.env.example` by hand, generate them yourself (e.g. `openssl rand -hex 24`): the gateway refuses to start with a missing, short (<32 chars) or example `OGNA_INTERNAL_JWT_SECRET`, and Zitadel requires `ZITADEL_MASTERKEY` to be exactly 32 characters.

The Zitadel admin console is at `http://auth.localhost:8000/ui/console`; sign in with `OGNA_AUTH_ADMIN_EMAIL` and `OGNA_AUTH_ADMIN_PASSWORD` from `.env`.

Set `API_IMAGE` (and any other settings) in `.env`:

| Variable | Description | Default in `.env.example` |
|----------|-------------|---------------------------|
| `API_IMAGE` | **Your pluggable backend Docker image** | `ogna-py-appi:prod` |
| `POSTGRES_USER` | Database user | `ogna_user` |
| `POSTGRES_PASSWORD` | Database password | generated by `make env` |
| `POSTGRES_DB` | Database name | `ogna_db` |
| `HASURA_GRAPHQL_ADMIN_SECRET` | Hasura admin secret | generated by `make env` |
| `OGNA_AUTH_DOMAIN` | Zitadel's public hostname (`*.localhost` resolves locally in browsers) | `auth.localhost` |
| `OGNA_AUTH_EXTERNAL_PORT` / `_SECURE` / `OGNA_AUTH_PUBLIC_SCHEME` | Public port and scheme of the auth domain (keep them consistent: `443`/`true`/`https` in production) | `8000` / `false` / `http` |
| `OGNA_AUTH_ADMIN_EMAIL` / `_PASSWORD` | First Zitadel admin (console login) | `admin@example.com` / generated |
| `ZITADEL_MASTERKEY` | Encrypts Zitadel's secrets at rest. **Exactly 32 chars; never change or lose it** | generated by `make env` |
| `ZITADEL_DB_PASSWORD` | Password for Zitadel's own `zitadel` database user | generated by `make env` |
| `ZITADEL_LOGIN_COOKIE_SECRET` | Signs the login UI's session cookie | generated by `make env` |
| `OGNA_INTERNAL_JWT_SECRET` | Signs the short-lived tokens the gateway forwards to Hasura, Storage and your API | generated by `make env` |
| `OGNA_OIDC_REDIRECT_URIS` / `OGNA_OIDC_POST_LOGOUT_URIS` | Allowed redirects for the `ogna-web` OIDC app | localhost:3000 / :5173 |
| `OGNA_CORS_ORIGINS` | Allowed browser origins for OGNA services, comma-separated | localhost dev ports |
| `OGNA_AUTH_RATE_LIMIT_MINUTE` / `_HOUR` | Per-IP limit on Zitadel's token endpoint | `10` / `100` |
| `STORAGE_TYPE` | Storage backend type | `S3` |
| `S3_ENDPOINT_URL` | S3 endpoint URL | `http://rustfs:9000` |
| `S3_ACCESS_KEY` | S3 access key | `rustfsadmin` |
| `S3_SECRET_KEY` | S3 secret key | `rustfsadmin` |

### Step 2: Start the Core Stack (Makefile or Docker Compose)

You can stand up and manage the stack quickly using `make`:

```bash
make up               # Stand up full stack (Core + API + local RustFS S3)
make up-external-s3   # Stand up Core + API (external S3)
make up-core          # Stand up Core + local RustFS S3 (without API container)
make logs             # Follow container logs (or `make logs SERVICE=api`)
make ps               # Check running containers
make down             # Stop all containers
make clean            # Stop all containers and remove volumes
```

Or run `docker compose` directly:

#### Option A: Standard (Core + Pluggable API + Self-Hosted RustFS Storage)

```bash
docker compose \
  -f docker-compose.yaml \
  -f docker-compose-api.yaml \
  -f docker-compose-storage.yaml \
  up -d --build
```

To swap the API container on the fly without editing `docker-compose-api.yaml`:

```bash
API_IMAGE=my-custom-backend:latest docker compose \
  -f docker-compose.yaml \
  -f docker-compose-api.yaml \
  -f docker-compose-storage.yaml \
  up -d
```

#### Option B: External S3 (Omits Local RustFS Container)

```bash
docker compose \
  -f docker-compose.yaml \
  -f docker-compose-api.yaml \
  up -d --build
```

### Step 3: View Logs & Stop `core`

```bash
# Follow logs
docker compose logs -f

# Stop containers
docker compose -f docker-compose.yaml -f docker-compose-api.yaml -f docker-compose-storage.yaml down
```

### Step 4: Run Tests

```bash
# Run CLI unit tests (no running containers required)
PYTHONPATH=. python3 test/test_cli.py

# Run integration tests (requires stack running on http://localhost:8000).
# The suite creates a throwaway Zitadel machine user (using the setup job's admin
# token, read via `docker`) and requests many tokens quickly, so first raise the
# token rate limits in .env (OGNA_AUTH_RATE_LIMIT_MINUTE=1000,
# OGNA_AUTH_RATE_LIMIT_HOUR=10000) and restart the gateway.
python3 -m unittest discover -s test -p "test_*.py" -v
```

---

## Endpoints & Routing

All traffic enters through Kong on `http://localhost:8000` (and port `80`/`443`):

| Host / Route              | Target Service  | Description                                   | Token Required |
|---------------------------|-----------------|-----------------------------------------------|----------------|
| `OGNA_AUTH_DOMAIN` (all)  | `zitadel`       | OIDC endpoints, APIs, admin console (`/ui/console`) | No (Zitadel's own auth) |
| `OGNA_AUTH_DOMAIN` `/ui/v2/login` | `zitadel-login` | Hosted login pages                    | No             |
| `/`                       | `dashboard`     | Frontend dashboard                            | No             |
| `/api/*`                  | `api`           | Your pluggable backend (`:8000`)              | Yes            |
| `/storage/*`              | `storage`       | Object storage API                            | Yes            |
| `/graphql`                | `hasura`        | Hasura GraphQL endpoint                       | Yes            |

---

## Authentication (Zitadel)

### How a request is authenticated

1. Your frontend signs users in with **OIDC Authorization Code + PKCE** against Zitadel (issuer `http://auth.localhost:8000` in dev). Users see Zitadel's hosted login pages, which you can brand in the console. Any standard OIDC client works, e.g. `oidc-client-ts` for browsers or AppAuth for mobile. Get the client id with `make auth-info`.
2. The app calls OGNA with `Authorization: Bearer <access token>`. Access tokens are **opaque**: they mean nothing without asking Zitadel.
3. For `/api`, `/storage`, `/graphql` and extra routes, the gateway's `ogna-guard` plugin asks Zitadel whether the token is active ([token introspection](https://www.rfc-editor.org/rfc/rfc7662)). Inactive or missing → `401`. Zitadel unreachable → `503` (fails closed).
4. For an active token the gateway forwards:
   - `X-Authenticated-User-Id` (Zitadel user id), `X-Authenticated-User-Role` (`authenticated`), and when available `X-Authenticated-User-Roles` (project roles), `X-Authenticated-Org-Id`, `X-Authenticated-Client-Id`;
   - `Authorization: Bearer <internal token>`: an HS256 JWT signed with `OGNA_INTERNAL_JWT_SECRET` (`sub`, `role`, `aud=authenticated`, ≤ 5 min). Hasura and Storage verify this token, so they never talk to Zitadel. Your backend can trust the headers or verify the token.

### Logout and revocation

"Active" answers are cached for `OGNA_AUTH_ACTIVE_CACHE_TTL` seconds (default `5`) and "inactive" answers for 5 minutes. When a token is revoked, its user is deactivated or deleted, or (for user logins) the session ends, Zitadel reports it inactive, so it stops working at the gateway within about 5 seconds. Clients should log out through Zitadel's `end_session` endpoint and revoke their refresh token (`/oauth/v2/revoke`); OIDC client libraries do this for you.

### Machine-to-machine

Create a service user in the console (or via API), give it a client secret, and request tokens with the client-credentials grant and scope `openid urn:zitadel:iam:org:project:id:<OGNA project id>:aud`. The project id is shown in the console; the integration tests (`test/ogna_test_auth.py`) do exactly this.

### Migrating from GoTrue

This is a breaking change for existing deployments:

- **Users are not migrated automatically.** Zitadel has its own user store and ids. Import them with Zitadel's user import API, which supports existing password hashes such as bcrypt (verify with a few accounts first), and map old GoTrue ids to new Zitadel ids in your data.
- **`storage.bucket.owner` is now `TEXT`** (migration `003_storage_owner_text` drops the foreign key to `auth.users`). Existing owner values are GoTrue UUIDs and must be rewritten to Zitadel ids.
- **Frontends must switch** from GoTrue's `/auth/*` API (supabase-js) to an OIDC client. This includes the dashboard image.
- Remove `GOTRUE_*` and `ENCRYPTION_KEY` from `.env`, add the Zitadel variables (`make env` on a fresh checkout shows them all).
- Redis, the `jwt-blacklist` plugin and the `tokens` network are gone: `docker rm -f redis gotrue`, delete the `redis_data` volume, and remove `tokens` from your own services' `networks:`.

### Production checklist

- Secrets generated per deployment (`make env` / `ogna init`). Back up `ZITADEL_MASTERKEY`: losing it makes Zitadel's encrypted data unrecoverable.
- `OGNA_AUTH_DOMAIN` set to a real hostname (e.g. `auth.example.com`) with `OGNA_AUTH_EXTERNAL_PORT=443`, `OGNA_AUTH_EXTERNAL_SECURE=true`, `OGNA_AUTH_PUBLIC_SCHEME=https`, TLS terminated at Kong. These are baked into Zitadel's instance on first start; changing them later requires adding the new domain in Zitadel.
- `OGNA_OIDC_REDIRECT_URIS` / `OGNA_OIDC_POST_LOGOUT_URIS` limited to your real app URLs (`https://` disables Zitadel's dev mode for the app).
- SMTP configured in the console (Default settings → SMTP) so email verification and password reset work; consider requiring MFA and setting a lockout policy (`OGNA_AUTH_MAX_PASSWORD_ATTEMPTS`).
- `OGNA_CORS_ORIGINS` set to your frontend origins.
- If Kong runs behind another proxy or load balancer, set `KONG_TRUSTED_IPS` and `KONG_REAL_IP_HEADER` so rate limits apply to the real client IP.

---

## License

MIT License
