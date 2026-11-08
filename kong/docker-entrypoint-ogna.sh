#!/usr/bin/env sh
set -e

TEMPLATE_PATH="${KONG_DECLARATIVE_CONFIG_TEMPLATE:-/kong/kong.yaml}"
RENDERED_PATH="/tmp/kong.yaml"

if [ -f "$TEMPLATE_PATH" ]; then
  JWT_SECRET="${GOTRUE_JWT_SECRET:-vPDsBi2TafJuP4iqp40qx60AR34Qf6hQgC8GWBB7GoOKGqL9V6}"

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
