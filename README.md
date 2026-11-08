# OGNA Backend Stack

OGNA is an **open-source Firebase alternative** built as a modular, Docker-first backend stack.
It provides the essential building blocks required to run a modern backend while allowing **full freedom over your application logic and technology choices**.

---

## Why OGNA? (Pluggable Backend Container)

Most Firebase alternatives tightly couple your backend logic to Postgres + REST/GraphQL, limiting how you build and scale your application.

OGNA is different by design:

- **Swap your backend container anytime** — Your backend is just a Docker image (`API_IMAGE`) exposing port `8000` internally.
- **Any language or framework** — Use Go, Rust, Python, Node.js, Java, C#, or anything that runs in a container.
- **Zero auth boilerplate in your backend** — Kong validates JWTs, rejects tokens from logged-out sessions, forwards the verified user as `X-Authenticated-User-Id` / `X-Authenticated-User-Role` headers, and enforces rate limits before requests ever reach `/api/*`.

---

## What OGNA Provides

- **Database** — PostgreSQL 18.1
- **Authentication** — GoTrue (`supabase/auth`: email/password, OAuth, JWT)
- **Storage** — S3-compatible object storage (`ghcr.io/ognastack/storage:latest` + local RustFS or external S3)
- **API Gateway** — Kong (`ghcr.io/ognastack/gateway`) for routing, JWT validation, and rate limiting
- **GraphQL Engine** — Hasura (`ghcr.io/ognastack/hasura`) pre-configured with storage metadata & JWT claims
- **Database Migrations** — Automated core + user SQL migrations (`ghcr.io/ognastack/migrations` powered by `dbmate`)
- **Pluggable Backend** — Bring your own backend Docker image (`API_IMAGE`)

---

## How It Works

OGNA separates **core infrastructure** from **your application container & migrations**:

1. **Swappable Backend Container (`api`)**:
   - Defined in `docker-compose.yaml` (or `docker-compose-api.yaml` in `core`) using `image: ${API_IMAGE:-ogna-py-appi:prod}`.
   - You can swap the backend container at any time via `ogna set-api <image>`, `ogna up --api-image <image>`, or by changing `API_IMAGE` in `.env`.
2. **Self-Contained Core Images (No Submodule Needed)**:
   - **Gateway (`ghcr.io/ognastack/gateway`)**: Packages Kong Gateway, the `ogna-guard` Lua plugin (strips spoofable internal headers, rejects tokens whose session has ended, forwards verified user claims, adds security headers), and `kong.yaml`, dynamically injecting `GOTRUE_JWT_SECRET` from `.env`.
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
# 1. Add a JWT-protected microservice exposed through Kong at /payments
ogna add-service payments --image my-org/payments-api:latest --port 8000 --route /payments

# 2. Add a public microservice exposed through Kong at /webhooks (no JWT required)
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

In OGNA, application services (`api`, `storage`, and custom microservices) do **not** connect directly to Postgres—all data access goes through **Hasura (`http://hasura:8080/v1/graphql`)**, which enforces row-level and column-level permissions per user JWT.

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

`make env` replaces each `change_me` placeholder with a random value. If you copy `.env.example` by hand, generate them yourself (e.g. `openssl rand -hex 24`): the gateway refuses to start with a missing, short (<32 chars) or example `GOTRUE_JWT_SECRET`.

Set `API_IMAGE` (and any other settings) in `.env`:

| Variable | Description | Default in `.env.example` |
|----------|-------------|---------------------------|
| `API_IMAGE` | **Your pluggable backend Docker image** | `ogna-py-appi:prod` |
| `POSTGRES_USER` | Database user | `ogna_user` |
| `POSTGRES_PASSWORD` | Database password | generated by `make env` |
| `POSTGRES_DB` | Database name | `ogna_db` |
| `GOTRUE_JWT_SECRET` | Shared JWT secret (GoTrue, Kong, Storage, Hasura), 32+ chars | generated by `make env` |
| `ENCRYPTION_KEY` | GoTrue encryption key | generated by `make env` |
| `GOTRUE_JWT_EXP` | Access token lifetime in seconds (see [Sessions & Logout](#sessions--logout)) | `3600` |
| `OGNA_GATEWAY_DB_PASSWORD` | Password for the gateway's read-only `ogna_gateway` login (session checks) | generated by `make env` |
| `HASURA_GRAPHQL_ADMIN_SECRET` | Hasura admin secret | generated by `make env` |
| `GOTRUE_SITE_URL` | Public URL of your app (email links, default redirect) | `http://localhost` |
| `GOTRUE_URI_ALLOW_LIST` | Extra allowed redirect URLs, comma-separated (wildcards allowed) | empty |
| `GOTRUE_MAILER_AUTOCONFIRM` | Skip email confirmation. **Set `false` in production** and configure `GOTRUE_SMTP_*` | `true` |
| `OGNA_CORS_ORIGINS` | Allowed browser origins, comma-separated | localhost dev ports |
| `OGNA_AUTH_RATE_LIMIT_MINUTE` / `_HOUR` | Per-IP limits on `/auth/token`, `/auth/signup`, `/auth/recover`, `/auth/otp`, `/auth/magiclink` | `10` / `100` |
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
# The suite signs up and logs in many users quickly, so first raise the auth
# rate limits in .env (OGNA_AUTH_RATE_LIMIT_MINUTE=1000, OGNA_AUTH_RATE_LIMIT_HOUR=10000)
# and restart the gateway.
python3 -m unittest discover -s test -p "test_*.py" -v
```

---

## Endpoints & Routing

All traffic enters through Kong on `http://localhost:8000` (and port `80`/`443`):

| Route        | Target Service | Description                     | JWT Required |
|--------------|----------------|---------------------------------|--------------|
| `/`          | `dashboard`    | Frontend dashboard              | No           |
| `/auth/*`    | `gotrue`       | Authentication endpoints        | No           |
| `/api/*`     | `api`          | Your pluggable backend (`:8000`)| Yes          |
| `/storage/*` | `storage`      | Object storage API              | Yes          |
| `/graphql`   | `hasura`       | Hasura GraphQL endpoint         | Role-based   |

---

## Sessions & Logout

OGNA uses GoTrue's own sessions as the source of truth for revocation. There is no token blocklist and no Redis.

- GoTrue access tokens (JWTs) last `GOTRUE_JWT_EXP` seconds (default `3600`). Every token carries a `session_id`.
- On every request with a bearer token (except `/auth/*`), the gateway's `ogna-guard` plugin verifies the signature and checks that the token's session still exists in `auth.sessions`. If it doesn't, the request gets `401`.
- `POST /auth/logout` deletes the session, so **every** access token from that session, including copies made before a refresh, stops working within `session_cache_ttl` seconds (default `5`). Refresh tokens are revoked at the same time. The same applies to "log out everywhere" (`?scope=global`), session timeouts and deleted users.
- Lookups use a read-only Postgres login (`ogna_gateway`, password `OGNA_GATEWAY_DB_PASSWORD`) that can only read `auth.sessions`. "Active" results are cached for 5 seconds and "revoked" results for 5 minutes, so Postgres sees at most one lookup per session every 5 seconds.
- If Postgres can't be reached, the gateway fails closed (`503`).
- Tokens without a `session_id` (for example, service keys you sign yourself with `GOTRUE_JWT_SECRET`) skip the session check.
- Clients should refresh access tokens before they expire. `@supabase/auth-js` (or `supabase-js`) pointed at `/auth` does this automatically.

### Upgrading from versions that used Redis

Earlier versions ran Redis and a `jwt-blacklist` Kong plugin. Both are gone:

1. Add `OGNA_GATEWAY_DB_PASSWORD` to `.env` (16+ characters, letters/digits/`_`/`-`), e.g. `openssl rand -hex 24`. The `migrations` service refuses to start without it.
2. Remove `REDIS_PASSWORD` from `.env`. Optionally set `GOTRUE_JWT_EXP` (default `3600`).
3. Pull the new `ghcr.io/ognastack/gateway:main` and `ghcr.io/ognastack/migrations:main` images and restart. Migration `003_gateway_session_reader` creates the `ogna_gateway` role.
4. Delete the old container and volume: `docker rm -f redis && docker volume rm <project>_redis_data`.
5. If your own services were attached to the `tokens` network, remove it from their `networks:` list.

### Production checklist

- Secrets: generated, unique per deployment, never the values from `.env.example`. The gateway enforces this for `GOTRUE_JWT_SECRET`.
- `GOTRUE_MAILER_AUTOCONFIRM=false` plus `GOTRUE_SMTP_HOST`, `_PORT`, `_USER`, `_PASS`, `_ADMIN_EMAIL`, so new accounts must prove they own their email.
- `GOTRUE_SITE_URL` set to your app's public URL, and `GOTRUE_URI_ALLOW_LIST` limited to your own domains, so login links can't redirect to other sites.
- `OGNA_CORS_ORIGINS` set to your real frontend origins.
- Keep the default auth rate limits (or lower). If Kong runs behind another proxy or load balancer, set `KONG_TRUSTED_IPS` and `KONG_REAL_IP_HEADER` so limits apply to the real client IP.

To rotate `OGNA_GATEWAY_DB_PASSWORD` later, run `ALTER ROLE ogna_gateway PASSWORD '...'` and update `.env` (the migration only sets it once).

---

## License

MIT License
