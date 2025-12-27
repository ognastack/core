CREATE SCHEMA IF NOT EXISTS auth;
CREATE ROLE postgres LOGIN;

CREATE SCHEMA IF NOT EXISTS migrations;

CREATE TABLE migrations.schema_migrations (
  version VARCHAR(255) PRIMARY KEY
);
