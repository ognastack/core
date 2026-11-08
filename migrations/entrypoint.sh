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
  # Render core migrations, injecting the gateway's read-only DB password
  GATEWAY_PASS="${OGNA_GATEWAY_DB_PASSWORD:-}"
  if ! printf '%s' "$GATEWAY_PASS" | grep -Eq '^[A-Za-z0-9_-]{16,}$'; then
    echo "[ogna-migrations] OGNA_GATEWAY_DB_PASSWORD must be set (16+ chars, letters/digits/_/- only)." >&2
    exit 1
  fi
  RENDERED_DIR="/tmp/core-migrations"
  rm -rf "$RENDERED_DIR" && mkdir -p "$RENDERED_DIR"
  for f in /db/core-migrations/*.sql; do
    sed "s|__OGNA_GATEWAY_DB_PASSWORD__|${GATEWAY_PASS}|g" "$f" > "$RENDERED_DIR/$(basename "$f")"
  done

  echo "[ogna-migrations] Applying OGNA core migrations..."
  dbmate \
    --migrations-dir "$RENDERED_DIR" \
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
