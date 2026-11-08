#!/bin/sh
set -e

ACTION="${1:-up}"

if [ "$ACTION" = "init" ]; then
  echo "[ogna-migrations] Running database pre-initialization (auth & migrations schemas)..."
  dbmate \
    --migrations-dir "/db/core-init" \
    --migrations-table "public.ogna_init_migrations" \
    --no-dump-schema \
    up
  exit 0
fi

if [ "$ACTION" = "up" ]; then
  echo "[ogna-migrations] Applying OGNA core migrations..."
  dbmate \
    --migrations-dir "/db/core-migrations" \
    --migrations-table "migrations.core_schema_migrations" \
    --no-dump-schema \
    up

  if [ -d "/db/migrations" ] && [ -n "$(ls -A /db/migrations/*.sql 2>/dev/null)" ]; then
    echo "[ogna-migrations] Applying user application migrations from /db/migrations..."
    dbmate \
      --migrations-dir "/db/migrations" \
      --migrations-table "${DBMATE_MIGRATIONS_TABLE:-migrations.schema_migrations}" \
      --no-dump-schema \
      up
  else
    echo "[ogna-migrations] No user migrations found in /db/migrations, skipping."
  fi
  exit 0
fi

exec dbmate "$@"
