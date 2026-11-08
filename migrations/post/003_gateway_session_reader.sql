-- migrate:up
-- Read-only login used by the Kong `ogna-guard` plugin to check whether a
-- token's GoTrue session still exists. It can read auth.sessions and nothing else.
-- The password is injected from OGNA_GATEWAY_DB_PASSWORD by the migrations entrypoint.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ogna_gateway') THEN
    CREATE ROLE ogna_gateway LOGIN PASSWORD '__OGNA_GATEWAY_DB_PASSWORD__';
  ELSE
    ALTER ROLE ogna_gateway LOGIN PASSWORD '__OGNA_GATEWAY_DB_PASSWORD__';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA auth TO ogna_gateway;
GRANT SELECT ON auth.sessions TO ogna_gateway;

-- migrate:down
REVOKE SELECT ON auth.sessions FROM ogna_gateway;
REVOKE USAGE ON SCHEMA auth FROM ogna_gateway;
DROP ROLE IF EXISTS ogna_gateway;
