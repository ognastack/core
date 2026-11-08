#!/usr/bin/env sh
set -e

TEMPLATE_PATH="${KONG_DECLARATIVE_CONFIG_TEMPLATE:-/kong/kong.yaml}"
RENDERED_PATH="/tmp/kong.yaml"

fail() {
  echo "[ogna-gateway] ERROR: $1" >&2
  exit 1
}

# Value that shipped in older .env.example files; it is public, so never accept it.
PUBLIC_EXAMPLE_SECRET="vPDsBi2TafJuP4iqp40qx60AR34Qf6hQgC8GWBB7GoOKGqL9V6"

if [ -f "$TEMPLATE_PATH" ]; then
  # --- JWT secret: required, long, not an example value, safe for templating ---
  JWT_SECRET="${GOTRUE_JWT_SECRET:-}"
  [ -n "$JWT_SECRET" ] || fail "GOTRUE_JWT_SECRET is not set. Generate one with: openssl rand -hex 32"
  [ "${#JWT_SECRET}" -ge 32 ] || fail "GOTRUE_JWT_SECRET must be at least 32 characters."
  case "$JWT_SECRET" in
    "$PUBLIC_EXAMPLE_SECRET"|*change_me*|*CHANGE_ME*)
      fail "GOTRUE_JWT_SECRET is still an example value. Generate one with: openssl rand -hex 32" ;;
    *'|'*|*'&'*|*'\'*)
      fail "GOTRUE_JWT_SECRET must not contain '|', '&' or '\\'." ;;
  esac

  # --- Gateway DB password (session checks) ---
  GATEWAY_DB_PASS="${OGNA_GATEWAY_DB_PASSWORD:-}"
  printf '%s' "$GATEWAY_DB_PASS" | grep -Eq '^[A-Za-z0-9_-]{16,}$' \
    || fail "OGNA_GATEWAY_DB_PASSWORD must be set (16+ chars, letters/digits/_/- only)."
  case "$GATEWAY_DB_PASS" in
    *change_me*) fail "OGNA_GATEWAY_DB_PASSWORD is still an example value." ;;
  esac

  # --- Strict rate limit for credential endpoints (/auth/token, /auth/signup, ...) ---
  AUTH_RPM="${OGNA_AUTH_RATE_LIMIT_MINUTE:-10}"
  AUTH_RPH="${OGNA_AUTH_RATE_LIMIT_HOUR:-100}"
  printf '%s' "$AUTH_RPM" | grep -Eq '^[1-9][0-9]*$' || fail "OGNA_AUTH_RATE_LIMIT_MINUTE must be a positive integer."
  printf '%s' "$AUTH_RPH" | grep -Eq '^[1-9][0-9]*$' || fail "OGNA_AUTH_RATE_LIMIT_HOUR must be a positive integer."
  [ "$AUTH_RPH" -ge "$AUTH_RPM" ] || fail "OGNA_AUTH_RATE_LIMIT_HOUR must be >= OGNA_AUTH_RATE_LIMIT_MINUTE."

  # --- CORS origins (comma-separated) ---
  DEFAULT_CORS="http://localhost,http://127.0.0.1,https://localhost,https://127.0.0.1,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"
  CORS_YAML=""
  OLD_IFS="$IFS"; IFS=','
  for origin in ${OGNA_CORS_ORIGINS:-$DEFAULT_CORS}; do
    origin="$(printf '%s' "$origin" | tr -d '[:space:]')"
    [ -z "$origin" ] && continue
    printf '%s' "$origin" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?$' \
      || fail "Invalid origin in OGNA_CORS_ORIGINS: '$origin' (expected scheme://host[:port])"
    CORS_YAML="${CORS_YAML:+$CORS_YAML, }\"$origin\""
  done
  IFS="$OLD_IFS"
  [ -n "$CORS_YAML" ] || fail "OGNA_CORS_ORIGINS is empty."

  EXTRA_SERVICES_FILE="/tmp/kong_extra_services.yaml"
  : > "$EXTRA_SERVICES_FILE"

  # Parse OGNA_EXTRA_ROUTES if provided
  # Format: name=http://host:port:/route_path[:jwt|public],name2=http://host2:port:/path2[:jwt|public]
  if [ -n "${OGNA_EXTRA_ROUTES:-}" ]; then
    OLD_IFS="$IFS"
    IFS=','
    for entry in $OGNA_EXTRA_ROUTES; do
      entry="$(echo "$entry" | tr -d '[:space:]')"
      [ -z "$entry" ] && continue

      svc_name="${entry%%=*}"
      rest="${entry#*=}"
      # Extract url (http://host:port) and remaining (:path[:auth])
      svc_url="$(echo "$rest" | cut -d':' -f1,2)"
      svc_path="$(echo "$rest" | cut -d':' -f3)"
      svc_auth="$(echo "$rest" | cut -d':' -f4)"
      [ -z "$svc_auth" ] && svc_auth="jwt"

      if [ -n "$svc_name" ] && [ -n "$svc_url" ] && [ -n "$svc_path" ]; then
        cat >> "$EXTRA_SERVICES_FILE" <<EOF
  - name: ${svc_name}-service
    url: ${svc_url}
    routes:
      - name: ${svc_name}-route
        paths:
          - ${svc_path}
EOF
        if [ "$svc_auth" != "public" ]; then
          cat >> "$EXTRA_SERVICES_FILE" <<EOF
    plugins:
      - name: jwt
        config:
          key_claim_name: aud
          claims_to_verify:
            - exp
      - name: rate-limiting
        config:
          second: 500
          minute: 1000
          policy: local
EOF
        fi
      fi
    done
    IFS="$OLD_IFS"
  fi

  # Render base template and inject extra services before `# GLOBAL PLUGINS`
  awk -v extra_file="$EXTRA_SERVICES_FILE" '
    /# GLOBAL PLUGINS/ {
      while ((getline line < extra_file) > 0) {
        print line
      }
      close(extra_file)
    }
    { print }
  ' "$TEMPLATE_PATH" | sed \
    -e "s|\${GOTRUE_JWT_SECRET}|${JWT_SECRET}|g" \
    -e "s|\${POSTGRES_DB}|${POSTGRES_DB:-ogna_db}|g" \
    -e "s|\${OGNA_GATEWAY_DB_PASSWORD}|${GATEWAY_DB_PASS}|g" \
    -e "s|\${OGNA_AUTH_RATE_LIMIT_MINUTE}|${AUTH_RPM}|g" \
    -e "s|\${OGNA_AUTH_RATE_LIMIT_HOUR}|${AUTH_RPH}|g" \
    -e "s|\${OGNA_CORS_ORIGINS}|[${CORS_YAML}]|g" \
    > "$RENDERED_PATH"

  export KONG_DECLARATIVE_CONFIG="$RENDERED_PATH"
fi

if [ -x /entrypoint.sh ]; then
  exec /entrypoint.sh "$@"
elif [ -x /docker-entrypoint.sh ]; then
  exec /docker-entrypoint.sh "$@"
else
  exec "$@"
fi
