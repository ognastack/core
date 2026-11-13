-- migrate:up
-- OGNA control plane: plans, accounts, projects (one VPS each), servers,
-- versioned deployments (desired state) and an event log.
-- Invariants that must hold under concurrent requests (plan quotas, deploy
-- version numbers) are enforced here, not only in the API.

CREATE SCHEMA IF NOT EXISTS platform;

CREATE OR REPLACE FUNCTION platform.touch_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Plans: sizes and limits. Edit rows to change server types or quotas
-- without a deploy (e.g. when a provider retires a server type).
-- ---------------------------------------------------------------------------
CREATE TABLE platform.plans (
    id                  TEXT PRIMARY KEY CHECK (id ~ '^[a-z0-9-]{1,32}$'),
    name                TEXT NOT NULL,
    server_type         TEXT NOT NULL,
    max_projects        INTEGER NOT NULL CHECK (max_projects >= 0),
    monthly_price_cents INTEGER NOT NULL DEFAULT 0 CHECK (monthly_price_cents >= 0),
    is_default          BOOLEAN NOT NULL DEFAULT FALSE,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX plans_single_default ON platform.plans (is_default) WHERE is_default;
CREATE TRIGGER plans_touch BEFORE UPDATE ON platform.plans
    FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at();

-- Hetzner shared vCPU line (Oct 2025): cx23 = 2 vCPU / 4 GB, cx33 = 4 / 8, cx43 = 8 / 16
INSERT INTO platform.plans (id, name, server_type, max_projects, monthly_price_cents, is_default, sort_order) VALUES
    ('hobby',    'Hobby',    'cx23', 1,  0,    TRUE,  10),
    ('pro',      'Pro',      'cx33', 3,  2000, FALSE, 20),
    ('business', 'Business', 'cx43', 10, 6000, FALSE, 30);

-- ---------------------------------------------------------------------------
-- Accounts: one per identity-provider user (GoTrue UUID or Zitadel id).
-- ---------------------------------------------------------------------------
CREATE TABLE platform.accounts (
    user_id    TEXT PRIMARY KEY CHECK (user_id ~ '^[A-Za-z0-9_.@-]{1,128}$'),
    plan_id    TEXT NOT NULL REFERENCES platform.plans (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER accounts_touch BEFORE UPDATE ON platform.accounts
    FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at();

-- ---------------------------------------------------------------------------
-- Projects: one customer stack on one VPS.
-- ---------------------------------------------------------------------------
CREATE TABLE platform.projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        TEXT NOT NULL REFERENCES platform.accounts (user_id),
    name            TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 63),
    slug            TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
    plan_id         TEXT NOT NULL REFERENCES platform.plans (id),
    server_type     TEXT NOT NULL,
    region          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'provisioning'
                    CHECK (status IN ('provisioning', 'running', 'failed', 'deleting', 'deleted')),
    status_detail   TEXT,
    current_version INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX projects_owner_active ON platform.projects (owner_id) WHERE status <> 'deleted';
CREATE INDEX projects_in_transition ON platform.projects (status) WHERE status IN ('provisioning', 'deleting');
CREATE TRIGGER projects_touch BEFORE UPDATE ON platform.projects
    FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at();

-- Plan quota, enforced atomically: the account row is locked so two
-- concurrent creates cannot both pass the check.
CREATE OR REPLACE FUNCTION platform.enforce_project_quota() RETURNS trigger AS $$
DECLARE
  max_allowed INTEGER;
  used        INTEGER;
BEGIN
  SELECT p.max_projects INTO max_allowed
    FROM platform.accounts a
    JOIN platform.plans p ON p.id = a.plan_id
   WHERE a.user_id = NEW.owner_id
     FOR UPDATE OF a;
  IF max_allowed IS NULL THEN
    RAISE EXCEPTION 'account_not_found' USING ERRCODE = 'foreign_key_violation';
  END IF;

  SELECT COUNT(*) INTO used
    FROM platform.projects
   WHERE owner_id = NEW.owner_id AND status <> 'deleted';
  IF used >= max_allowed THEN
    RAISE EXCEPTION 'quota_exceeded: plan allows % project(s)', max_allowed
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER projects_quota BEFORE INSERT ON platform.projects
    FOR EACH ROW EXECUTE FUNCTION platform.enforce_project_quota();

-- ---------------------------------------------------------------------------
-- Servers: the VPS behind a project, mirrored from the provider.
-- ---------------------------------------------------------------------------
CREATE TABLE platform.servers (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id            UUID NOT NULL UNIQUE REFERENCES platform.projects (id) ON DELETE CASCADE,
    owner_id              TEXT NOT NULL,
    provider              TEXT NOT NULL,
    provider_server_id    TEXT,
    name                  TEXT NOT NULL,
    server_type           TEXT NOT NULL,
    location              TEXT NOT NULL,
    ipv4                  TEXT,
    ipv6                  TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    -- SHA-256 of the one-time token in the VPS's cloud-init (for the future agent enrollment)
    enrollment_token_hash TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER servers_touch BEFORE UPDATE ON platform.servers
    FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at();

-- ---------------------------------------------------------------------------
-- Deployments: every change to a project's desired state is a new, immutable
-- version. Rollback = a new version copying an older one.
-- ---------------------------------------------------------------------------
CREATE TABLE platform.deployments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       UUID NOT NULL REFERENCES platform.projects (id) ON DELETE CASCADE,
    owner_id         TEXT NOT NULL,
    version          INTEGER NOT NULL,
    stack_version    TEXT NOT NULL,
    backend_image    TEXT NOT NULL,
    config           JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason           TEXT NOT NULL DEFAULT 'deploy' CHECK (reason IN ('deploy', 'rollback')),
    rolled_back_from INTEGER,
    created_by       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, version)
);

-- Assigns the next version number under a row lock on the project and makes
-- it the project's current version, so concurrent deploys get 1, 2, 3...
CREATE OR REPLACE FUNCTION platform.assign_deployment_version() RETURNS trigger AS $$
DECLARE
  current INTEGER;
BEGIN
  SELECT current_version INTO current
    FROM platform.projects
   WHERE id = NEW.project_id
     FOR UPDATE;
  IF current IS NULL THEN
    RAISE EXCEPTION 'project_not_found' USING ERRCODE = 'foreign_key_violation';
  END IF;
  NEW.version := current + 1;
  UPDATE platform.projects SET current_version = NEW.version WHERE id = NEW.project_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER deployments_version BEFORE INSERT ON platform.deployments
    FOR EACH ROW EXECUTE FUNCTION platform.assign_deployment_version();

-- ---------------------------------------------------------------------------
-- Events: human-readable history per project (shown in the dashboard).
-- ---------------------------------------------------------------------------
CREATE TABLE platform.events (
    id         BIGSERIAL PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES platform.projects (id) ON DELETE CASCADE,
    owner_id   TEXT NOT NULL,
    kind       TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX events_project_recent ON platform.events (project_id, created_at DESC);

-- migrate:down
DROP SCHEMA IF EXISTS platform CASCADE;
