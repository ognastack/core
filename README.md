# OGNA Backend Stack

OGNA is an **open-source Firebase alternative** built as a modular, Docker-first backend stack.
It provides the essential building blocks required to run a modern backend while allowing **full freedom over your application logic and technology choices**.

---

## What OGNA Provides

- **Database** — PostgreSQL 18.1
- **Authentication** — GoTrue (email/password, OAuth, JWT)
- **Storage** — S3-compatible object storage
- **API Gateway** — Kong for routing, JWT validation, and rate limiting
- **Pluggable Backend** — Bring your own backend in any language as a Docker container

---

## Why OGNA?

Most Firebase alternatives tightly couple your backend logic to Postgres + REST (or GraphQL), limiting how you can build and scale your application.

OGNA is different by design:

- Your backend is **just another Docker service**
- You can use **any language or framework**
- You control your data model and business logic
- Authentication, security, and routing are handled for you

---

## Architecture

- All `/api/*` requests → **Your backend service** (JWT protected)
- `/auth/*` requests → **GoTrue** (public authentication endpoints)
- `/storage/*` requests → **S3-compatible storage** (JWT protected)
- **Kong** acts as the single entry point:
  - Routing
  - JWT validation
  - Rate limiting

---

## Services

| Service   | Description                                  | Port      |
|-----------|----------------------------------------------|-----------|
| Kong      | API Gateway, routing, JWT validation          | 8000/8001 |
| GoTrue    | Authentication & JWT issuance                 | 9999      |
| API       | Your backend service (pluggable)              | 8000      |
| Postgres  | Primary database                              | 5432      |
| Redis     | JWT invalidation cache                        | 6379      |

---

## Security

OGNA supports **JWT token invalidation** using Redis.

- On logout, the JWT is added to a Redis-backed blacklist
- Any future request using that token is rejected
- Users must re-authenticate to obtain a new token

---

## Pluggable Backend Service

OGNA allows you to integrate **any backend implementation**.

### How It Works

- Your backend runs as a Docker container
- It is defined in `docker-compose-api.yaml`
- Kong automatically routes `/api/*` traffic to it
- JWT validation and rate limiting are enforced by Kong

### Example

```yaml
api:
  image: ogna-py-app:dev
  container_name: api
  restart: unless-stopped
  depends_on:
    ogna-database:
      condition: service_healthy
    kong-cp:
      condition: service_healthy
  expose:
    - "8000"
  networks:
    - ogna
```

### Backend Requirements

- Must expose port **8000**, dont expose it publicaly
- No authentication logic required in the backend

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd <repo-folder>
```

### 2. Environment variables

Create a `.env` file containing:

- Database credentials
- GoTrue secrets
- JWT configuration

### 3. Database migrations

All SQL migrations should be placed in the `./migrations` directory.
They will be applied automatically using **Flyway** during startup.

---

## Running the Stack

Start all services:

```bash
docker compose -f docker-compose.yaml -f docker-compose-api.yaml up -d
```

View logs:

```bash
docker compose logs -f kong-cp
docker compose logs -f api
```

Stop services:

```bash
docker compose down
```

---

## Endpoints

| Route        | Service    | Description                     | JWT Required |
|--------------|------------|---------------------------------|--------------|
| `/auth/*`    | GoTrue     | Authentication endpoints        | No           |
| `/api/*`     | API        | Application backend             | Yes          |
| `/storage/*` | Storage    | Object storage                  | Yes          |

---

## Authentication API (GoTrue)

### Signup

**POST /signup**

```json
{
  "email": "email@example.com",
  "password": "secret"
}
```

### Login / Token

**POST /token**

```
grant_type=password&username=email@example.com&password=secret
```

### Logout

**POST /logout**

- Requires authentication
- Revokes refresh tokens
- Invalidates active JWTs

---

## Configuration

- Kong configuration: `config/kong.yaml`
- JWT validation:
  - Expiration enforced
  - `iss` and `aud` optional in development
- Rate limiting applied per service
- GoTrue configuration via environment variables
- Backend service swapped via Docker image

---

## Roadmap

- Realtime events (Postgres logical replication)
- Admin dashboard
- Multi-tenant support
- GraphQL gateway (optional)

---

## License

MIT License
