#!/usr/bin/env sh
set -e

TEMPLATE_PATH="${KONG_DECLARATIVE_CONFIG_TEMPLATE:-/kong/kong.yaml}"
RENDERED_PATH="/tmp/kong.yaml"
GUARD_SETTINGS_PATH="${OGNA_GUARD_SETTINGS:-/tmp/ogna-guard.json}"
GATEWAY_CLIENT_ENV="${OGNA_GATEWAY_CLIENT_ENV:-/zitadel/bootstrap/gateway-client.env}"

fail() {
  echo "[ogna-gateway] ERROR: $1" >&2
  exit 1
}

is_int() { printf '%s' "$1" | grep -Eq '^[1-9][0-9]*$'; }

# Values that shipped in older .env.example files; they are public, so never accept them.
PUBLIC_EXAMPLE_SECRET="vPDsBi2TafJuP4iqp40qx60AR34Qf6hQgC8GWBB7GoOKGqL9V6"

if [ -f "$TEMPLATE_PATH" ]; then
  # --- Internal JWT secret: signs the short-lived tokens the gateway forwards upstream ---
  INTERNAL_SECRET="${OGNA_INTERNAL_JWT_SECRET:-}"
  [ -n "$INTERNAL_SECRET" ] || fail "OGNA_INTERNAL_JWT_SECRET is not set. Generate one with: openssl rand -hex 32"
  [ "${#INTERNAL_SECRET}" -ge 32 ] || fail "OGNA_INTERNAL_JWT_SECRET must be at least 32 characters."
  printf '%s' "$INTERNAL_SECRET" | grep -Eq '^[A-Za-z0-9_-]+$' \
    || fail "OGNA_INTERNAL_JWT_SECRET may only contain letters, digits, '_' and '-'."
  case "$INTERNAL_SECRET" in
    "$PUBLIC_EXAMPLE_SECRET"|*change_me*|*CHANGE_ME*)
      fail "OGNA_INTERNAL_JWT_SECRET is still an example value. Generate one with: openssl rand -hex 32" ;;
  esac

  # --- Auth domain (Zitadel's public hostname) ---
  AUTH_DOMAIN="${OGNA_AUTH_DOMAIN:-}"
  printf '%s' "$AUTH_DOMAIN" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$' \
    || fail "OGNA_AUTH_DOMAIN must be a hostname (e.g. auth.localhost or auth.example.com)."
  case "${OGNA_AUTH_EXTERNAL_SECURE:-false}" in
    true) AUTH_SCHEME="https" ;;
    false) AUTH_SCHEME="http" ;;
    *) fail "OGNA_AUTH_EXTERNAL_SECURE must be true or false." ;;
  esac

  # --- Introspection credentials written by the zitadel-setup job ---
  [ -r "$GATEWAY_CLIENT_ENV" ] || fail "$GATEWAY_CLIENT_ENV not found; did zitadel-setup run?"
  CLIENT_ID="$(sed -n 's/^OGNA_INTROSPECTION_CLIENT_ID=//p' "$GATEWAY_CLIENT_ENV")"
  CLIENT_SECRET="$(sed -n 's/^OGNA_INTROSPECTION_CLIENT_SECRET=//p' "$GATEWAY_CLIENT_ENV")"
  printf '%s' "$CLIENT_ID" | grep -Eq '^[A-Za-z0-9_.@-]+$' || fail "Invalid introspection client id in $GATEWAY_CLIENT_ENV"
  printf '%s' "$CLIENT_SECRET" | grep -Eq '^[A-Za-z0-9_.@-]+$' || fail "Invalid introspection client secret in $GATEWAY_CLIENT_ENV"

  # --- Token cache and internal token lifetimes (seconds) ---
  ACTIVE_TTL="${OGNA_AUTH_ACTIVE_CACHE_TTL:-5}"
  INACTIVE_TTL="${OGNA_AUTH_INACTIVE_CACHE_TTL:-300}"
  INTERNAL_TTL="${OGNA_INTERNAL_JWT_TTL:-300}"
  for v in "$ACTIVE_TTL" "$INACTIVE_TTL" "$INTERNAL_TTL"; do
    is_int "$v" || fail "Cache/token TTLs must be positive integers."
  done

  # --- Strict rate limit for Zitadel's token endpoint ---
  AUTH_RPM="${OGNA_AUTH_RATE_LIMIT_MINUTE:-10}"
  AUTH_RPH="${OGNA_AUTH_RATE_LIMIT_HOUR:-100}"
  is_int "$AUTH_RPM" || fail "OGNA_AUTH_RATE_LIMIT_MINUTE must be a positive integer."
  is_int "$AUTH_RPH" || fail "OGNA_AUTH_RATE_LIMIT_HOUR must be a positive integer."
  [ "$AUTH_RPH" -ge "$AUTH_RPM" ] || fail "OGNA_AUTH_RATE_LIMIT_HOUR must be >= OGNA_AUTH_RATE_LIMIT_MINUTE."

  # --- CORS origins for OGNA services (comma-separated) ---
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

  # --- Guard settings (read by the ogna-guard plugin; keeps secrets out of kong.yaml) ---
  umask 077
  cat > "$GUARD_SETTINGS_PATH" <<EOF
{
  "introspection_url": "http://zitadel:8080/oauth/v2/introspect",
  "auth_host": "${AUTH_DOMAIN}",
  "auth_scheme": "${AUTH_SCHEME}",
  "client_id": "${CLIENT_ID}",
  "client_secret": "${CLIENT_SECRET}",
  "internal_jwt_secret": "${INTERNAL_SECRET}",
  "internal_jwt_ttl": ${INTERNAL_TTL},
  "active_cache_ttl": ${ACTIVE_TTL},
  "inactive_cache_ttl": ${INACTIVE_TTL},
  "introspection_timeout_ms": 3000
}
EOF
  umask 022
  export OGNA_GUARD_SETTINGS="$GUARD_SETTINGS_PATH"

  EXTRA_SERVICES_FILE="/tmp/kong_extra_services.yaml"
  : > "$EXTRA_SERVICES_FILE"

  # Parse OGNA_EXTRA_ROUTES if provided
  # Format: name=http://host:port:/route_path[:jwt|public],name2=http://host2:port:/path2[:jwt|public]
  # ("jwt" keeps its historical name: it means "valid token required".)
  if [ -n "${OGNA_EXTRA_ROUTES:-}" ]; then
    OLD_IFS="$IFS"
    IFS=','
    for entry in $OGNA_EXTRA_ROUTES; do
      entry="$(echo "$entry" | tr -d '[:space:]')"
      [ -z "$entry" ] && continue

      svc_name="${entry%%=*}"
      rest="${entry#*=}"
      # rest = scheme://host:port:/path[:jwt|public]
      printf '%s' "$rest" | grep -Eq '^https?://[A-Za-z0-9.-]+:[0-9]+:/[A-Za-z0-9/_.-]*(:(jwt|public))?$' \
        || fail "Invalid OGNA_EXTRA_ROUTES entry '$entry' (expected name=http://host:port:/path[:jwt|public])"
      printf '%s' "$svc_name" | grep -Eq '^[A-Za-z0-9_-]+$' || fail "Invalid service name in OGNA_EXTRA_ROUTES: '$svc_name'"
      svc_url="$(printf '%s' "$rest" | sed -E 's|^(https?://[^:/]+:[0-9]+):.*|\1|')"
      svc_path="$(printf '%s' "$rest" | sed -E 's|^https?://[^:/]+:[0-9]+:(/[^:]*).*|\1|')"
      svc_auth="$(printf '%s' "$rest" | sed -nE 's|.*:(jwt\|public)$|\1|p')"
      [ -z "$svc_auth" ] && svc_auth="jwt"
      if [ "$svc_auth" = "public" ]; then require="false"; else require="true"; fi

      if [ -n "$svc_name" ] && [ -n "$svc_url" ] && [ -n "$svc_path" ]; then
        cat >> "$EXTRA_SERVICES_FILE" <<EOF
  - name: ${svc_name}-service
    url: ${svc_url}
    routes:
      - name: ${svc_name}-route
        paths:
          - ${svc_path}
    plugins:
      - name: ogna-guard
        config:
          require_auth: ${require}
      - name: cors
        config:
          origins: \${OGNA_CORS_ORIGINS}
          methods: [GET, POST, PUT, PATCH, DELETE, OPTIONS]
          headers: [Authorization, Content-Type]
          credentials: true
      - name: rate-limiting
        config:
          second: 500
          minute: 1000
          policy: local

EOF
      fi
    done
    IFS="$OLD_IFS"
  fi

  # Inject extra services before "# END SERVICES", then render placeholders
  awk -v extra_file="$EXTRA_SERVICES_FILE" '
    /# END SERVICES/ {
      while ((getline line < extra_file) > 0) {
        print line
      }
      close(extra_file)
    }
    { print }
  ' "$TEMPLATE_PATH" | sed \
    -e "s|\${OGNA_AUTH_DOMAIN}|${AUTH_DOMAIN}|g" \
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
