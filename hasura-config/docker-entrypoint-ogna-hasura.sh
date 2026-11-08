#!/usr/bin/env sh
set -e

CORE_METADATA_DIR="/hasura-core-metadata"
USER_TABLES_DIR="${OGNA_USER_HASURA_TABLES_DIR:-/user-hasura/tables}"
MERGED_METADATA_DIR="/tmp/hasura-metadata"

rm -rf "$MERGED_METADATA_DIR"
mkdir -p "$MERGED_METADATA_DIR"
cp -R "$CORE_METADATA_DIR"/. "$MERGED_METADATA_DIR"/

if [ -d "$USER_TABLES_DIR" ]; then
  mkdir -p "$MERGED_METADATA_DIR/databases/user/tables"
  for table_file in "$USER_TABLES_DIR"/*.yaml "$USER_TABLES_DIR"/*.yml; do
    [ -f "$table_file" ] || continue
    fname="$(basename "$table_file")"
    cp "$table_file" "$MERGED_METADATA_DIR/databases/user/tables/$fname"
    echo "- \"!include user/tables/$fname\"" >> "$MERGED_METADATA_DIR/databases/tables.yaml"
    echo "[ogna-hasura] Merged user table metadata: $fname"
  done
fi

export HASURA_GRAPHQL_METADATA_DIR="$MERGED_METADATA_DIR"

exec /usr/bin/docker-entrypoint.sh "$@"
