-- migrate:up
CREATE SCHEMA IF NOT EXISTS auth;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'postgres') THEN
    CREATE ROLE postgres LOGIN;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS migrations;

CREATE TABLE IF NOT EXISTS migrations.schema_migrations (
  version VARCHAR(255) PRIMARY KEY
);

-- migrate:down
