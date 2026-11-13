# OGNA platform (control plane)

The service where people sign in, pick a plan and create **projects**: an API (`api/`) and a web UI (`ui/`). Each project gets its own VPS running an OGNA stack. It is built **on OGNA itself**: this folder is an ordinary OGNA project, and `api/` is its pluggable backend.

```
┌──────────────── control plane (this folder, one OGNA stack) ───────────────┐
│ gateway → api (FastAPI) ──GraphQL──▶ Hasura ──▶ Postgres (platform schema) │
│              │                                                             │
│              └──▶ Hetzner Cloud API (create / find / delete servers)       │
└────────────────────────────────────────────────────────────────────────────┘
                     each project = one VPS (cloud-init: Docker, firewall,
                     enrollment token for the future agent)
```

**Status:** first version. It covers plans and quotas, the project and VPS lifecycle, and versioned deployments with rollback. The agent that will apply deployments on each VPS is not built yet. Deployments are recorded as **desired state** (`GET …/desired-state`) for the agent to fetch later.

## How it works

- **Identity comes from the gateway.** Kong verifies the user's token and forwards `X-Authenticated-User-Id`. The API has no auth code of its own and must only be reachable through the gateway (same contract as any OGNA backend). This works with GoTrue today and Zitadel later.
- **Writes go through the API, reads can use GraphQL.** The API talks to Hasura with the admin secret (OGNA services don't open Postgres directly). Users get read-only, owner-filtered GraphQL access to their projects, servers, deployments and events (`hasura/tables/`), e.g. for live status in a dashboard.
- **Rules are enforced in the database.** A trigger enforces plan quotas, locking the account row so concurrent creates can't exceed the limit. Another trigger assigns deployment version numbers, locking the project row so concurrent deploys get 1, 2, 3… This has been checked against Postgres 16, including two sessions racing on the quota.
- **Provisioning is a reconcile loop.** Every `OGNA_PLATFORM_RECONCILE_INTERVAL` seconds, and right after a create or delete, each project in `provisioning` or `deleting` moves one step towards its target:
  - provisioning: find the server **by label** (`ogna-project=<id>`) → create it if missing → mirror its status/IPs → `running` once the provider reports running. If the API crashes between "create" and "save the id", the next pass finds the server instead of creating a second one.
  - deleting: delete the server → wait until it's gone → `deleted` (frees the quota).
  - Retryable provider errors (rate limits, capacity) are retried on the next pass. Permanent ones (invalid input, bad token) or exceeding `OGNA_PLATFORM_PROVISION_TIMEOUT` mark the project `failed`. The user can then delete it.
- **Each VPS boots with cloud-init** (`app/cloudinit.py`): Docker, `ufw` (SSH, 80, 443 only), no password logins, automatic security updates, fail2ban, and `/etc/ogna/agent.env` (root-only) holding the control-plane URL, project id and a **one-time enrollment token**. Only its SHA-256 is stored, so the future agent can enroll without anyone handling secrets by hand.
- **Deployments are immutable versions.** Each one records `stack_version` (`main` or `1.4.2`), `backend_image` (tag or, preferably, `@sha256:` digest; tag-only deploys are flagged in the event log), and non-secret `config` (UPPER_SNAKE keys; platform-owned prefixes like `OGNA_`, `HASURA_`, `POSTGRES_` are rejected). A rollback creates a **new** version copying an old one, so history is never rewritten.

## Web UI

`ui/` is built from the [OGNA frontend template](https://github.com/ognastack/ogna-fe-template) (Next.js + shadcn/ui + `@ogna/js`) and replaces the stack's default dashboard, so it's served at `/` on the same origin as the API.

- **Sign up / log in:** the template's forms, backed by the stack's auth.
- **Projects** (`/protected/projects`): your projects with live status (polls every 5s while one is provisioning or deleting), plan usage, and a **New project** panel with name and region.
- **Project page** (`/protected/projects/<id>`): overview, server (type, location, IPs), **Deploy** (image, stack version, settings), **Deployments** with one-click rollback, **Events**, and the **Desired state** the agent will apply. **Delete** asks you to type the project slug.
- **Plan & usage** (`/protected/account`): current plan, usage, all plans, and, for platform admins, a form to change a user's plan.

For local development against a running stack: `cd ui && npm ci && NEXT_PUBLIC_OGNA_URL=http://localhost:8000 npm run dev`.

## API

All routes are under `/api/v1` and require a signed-in user.

| Method & path | Description |
|---|---|
| `GET /plans` | Active plans (size, project limit, price) |
| `GET /regions` | Regions users can pick (`OGNA_PLATFORM_REGIONS`, first is the default) |
| `GET /account` | Your plan and usage. The account is created on first call, on the default plan |
| `PUT /admin/accounts/{user_id}/plan` | Change a user's plan (only `OGNA_PLATFORM_ADMIN_USER_IDS`; refuses downgrades below current usage) |
| `POST /projects` `{name, region?}` | Create a project (`202`, provisioning starts immediately); `403 quota_exceeded` at the plan limit |
| `GET /projects` · `GET /projects/{id}` | Your projects with server status/IPs and current deployment |
| `POST /projects/{id}/sync` | Reconcile now and return fresh status |
| `DELETE /projects/{id}` | Delete the server, then the project (`202`) |
| `GET /projects/{id}/events` | History (created, server_created, running, deployed, rolled_back, failed, deleted) |
| `POST /projects/{id}/deployments` `{backend_image, stack_version?, config?}` | New desired-state version |
| `GET /projects/{id}/deployments` | Version history, newest first |
| `POST /projects/{id}/deployments/{version}/rollback` | New version copying `version` |
| `GET /projects/{id}/desired-state` | What the VPS should run (the future agent's input) |

Errors look like `{"error": {"code": "quota_exceeded", "message": "Your plan allows 1 project(s)"}, "message": "…", "error_code": "quota_exceeded"}`. The top-level fields are what `@ogna/js` returns as `error.msg` / `error.error_code`; validation errors are summarized as `"field: problem"`.

Plans live in `platform.plans`, seeded with Hetzner's current shared line: `hobby` → `cx23` (1 project), `pro` → `cx33` (3), `business` → `cx43` (10). Edit the rows to change sizes or limits without a deploy, e.g. if a server type is out of stock. Prices are informational; there is no billing yet.

## Run it

```bash
cd platform
ogna init . --name ogna-platform        # creates .ogna/ and .env; keeps the files here
cat .env.platform.example >> .env       # then edit: provider, token, admins…
ogna up --build -d                       # builds api/ and ui/
```

Then open http://localhost:8000, sign up, and create a project.

Start with `OGNA_PLATFORM_PROVIDER=fake`: servers are simulated, so you can click through the whole flow for free. Switch to `hetzner` with a project API token (Hetzner Console → Security → API tokens, read & write) when ready. **Real servers are billed** until the project is deleted.

## Tests

```bash
cd platform/api
pip install -r requirements-dev.txt
pytest
```

The tests cover the service against an in-memory repository and a fake provider: quotas (including concurrent creates), provisioning, retry and timeout, deletion, ownership, deploys, rollback, desired state and input validation. They also cover the Hetzner driver and the Hasura repository against recorded HTTP, cloud-init output, and the HTTP routes.

## Known limits / next steps

- **Single API replica.** Reconciles are serialized per project inside one process. Running several replicas needs a database lease (e.g. `SELECT … FOR UPDATE SKIP LOCKED` on a reconcile column).
- **No agent yet**, so a project reaching `running` means the VPS booted, not that the OGNA stack runs on it. Next: agent endpoints (`POST /agents/enroll` with the token from cloud-init, desired-state fetch, status reports).
- **Firewall:** `ufw` doesn't filter ports published by Docker. Keep the stack publishing only 80/443, or add a Hetzner Cloud Firewall via the API.
- **Failed projects keep their server** (if one was created) until the user deletes the project. Consider auto-cleanup.
- Secrets per deployment, custom domains/DNS, backups, billing.
