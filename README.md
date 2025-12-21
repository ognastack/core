# OGNA Backend Stack

This project is a **microservices backend architecture** using **Kong**, **GoTrue (Supabase Auth)**, **FastAPI** and **Postgres**, with JWT authentication and rate-limiting for secure and scalable APIs.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Services](#services)
- [Pluggable Backend Service](#pluggable-backend-service)
- [Setup](#setup)
- [Running the stack](#running-the-stack)
- [Endpoints](#endpoints)
- [Configuration](#configuration)
- [License](#license)

---

## Overview

This backend stack provides:

- Centralized **API gateway** using Kong
- Authentication and JWT issuance via **GoTrue**
- Business logic through **FastAPI**
- **Postgres** as the main database
- **Rate limiting** per service to protect APIs
- Declarative configuration for Kong and JWT consumers

---

## Architecture

```
Frontend
   |
   v
[Kong API Gateway]
   |
   v
FastAPI
  |
  v
 Postgres DB (shared)
      ^
      |
    GoTrue (Auth/JWT)
```

- All `/api` requests → FastAPI (JWT protected)
- `/auth` requests → GoTrue (signup/login, public)
- Kong handles routing, JWT validation, and rate limiting

---

## Services

| Service  | Description                            | Port      |
| -------- | -------------------------------------- | --------- |
| Kong     | API Gateway, routes and JWT validation | 8000/8001 |
| GoTrue   | Authentication & JWT management        | 9999      |
| FastAPI  | Application backend                    | 8000      |
| Postgres | Database storage                       | 5432      |

---

## Pluggable Backend Service

This stack is designed to allow **any backend service** to be integrated seamlessly.

### How it works

- The backend must run as a **Docker container**.
- You only need to **replace the Docker image** in the `docker-compose.yml`.
- Kong will route requests to `/api/*` automatically, and JWT validation will still apply.

### Example: Adding a Custom Backend

```yaml
api:
  image: ogna-py-appi:dev # Replace this with your backend image
  container_name: api
  restart: unless-stopped
  depends_on:
    ogna-database:
      condition: service_healthy
    kong-cp:
      condition: service_healthy
  expose:
    - "8000" # The port your backend listens on
  networks:
    - ogna
```

### Notes

- Your backend must **listen on a port** internally (exposed via Docker).
- Kong expects the backend to serve under `/api/*`.
- All JWT authentication, rate limiting, and routing are handled automatically by Kong.
- You can change the image tag to switch environments (e.g., `my-backend:latest` or `my-backend:v1.2.3`).

---

## Setup

1. Clone the repository:

```bash
git clone <repo-url>
cd <repo-folder>
```

2. Create `.env` file:

- `.env` → Database and GoTrue secrets

3. Ensure migrations are in `./migrations` folder for Flyway and Postgres initialization

---

## Running the Stack

Start all services with Docker Compose:

```bash
docker compose -f docker-compose.yaml -f docker-compose-api.yaml up -d
```

Check logs for Kong or FastAPI

```bash
docker-compose logs -f kong-cp
docker-compose logs -f api
```

Stop the stack:

```bash
docker-compose down
```

---

## Endpoints

| Route    | Service | Description                    | JWT Required |
| -------- | ------- | ------------------------------ | ------------ |
| `/auth`  | GoTrue  | Signup, login, user management | No           |
| `/api/*` | FastAPI | Application backend endpoints  | Yes          |

---

## Configuration

- **Kong** is configured declaratively in `config/kong.yaml`
- **JWT validation** checks token expiration; `iss` and `aud` verification can be skipped for dev
- **Rate limiting** is applied per service in Kong
- **GoTrue** uses `GOTRUE_SITE_URL` and `GOTRUE_JWT_AUD` for JWT claims
- Any backend service can be swapped by changing the Docker image under the `api` service

---

## License

This project is licensed under the MIT License.
