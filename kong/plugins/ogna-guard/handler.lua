local cjson = require "cjson.safe"
local http = require "resty.http"
local digest = require "resty.openssl.digest"
local hmac = require "resty.openssl.hmac"
local to_hex = require("resty.string").to_hex

-- OGNA gateway guard (Zitadel edition).
--
-- For every request to an OGNA service it:
--   1. strips headers clients must never be able to set (admin secret, identity headers),
--   2. checks the bearer token with Zitadel's introspection endpoint (RFC 7662),
--      caching "active" answers for a few seconds and "inactive" answers longer,
--   3. on success forwards the identity as X-Authenticated-User-* headers and replaces
--      Authorization with a short-lived internal HS256 JWT (sub, role, aud) that Hasura,
--      Storage and backends verify with OGNA_INTERNAL_JWT_SECRET, so they never need
--      to know about Zitadel,
--   4. rejects the request (401) when `require_auth` is set and there is no valid token.
--
-- Revocation (logout, deleted user, revoked PAT) takes effect within
-- `active_cache_ttl` seconds because Zitadel reports the token as inactive.
--
-- Shared settings (introspection credentials, internal secret) are read once per
-- worker from the JSON file rendered by the container entrypoint, so secrets never
-- live in kong.yaml.
local OgnaGuardHandler = {
  VERSION = "4.0.0",
  PRIORITY = 900,
}

local SETTINGS_PATH = os.getenv("OGNA_GUARD_SETTINGS") or "/tmp/ogna-guard.json"
local settings

local function load_settings()
  if settings then return settings end
  local f, err = io.open(SETTINGS_PATH, "r")
  if not f then
    return nil, "cannot open " .. SETTINGS_PATH .. ": " .. tostring(err)
  end
  local raw = f:read("*a")
  f:close()
  local decoded, derr = cjson.decode(raw)
  if not decoded then
    return nil, "invalid settings JSON: " .. tostring(derr)
  end
  settings = decoded
  return settings
end

local function b64url(data)
  return (ngx.encode_base64(data):gsub("%+", "-"):gsub("/", "_"):gsub("=", ""))
end

local function sign_internal_jwt(s, claims)
  local header = b64url(cjson.encode({ alg = "HS256", typ = "JWT" }))
  local payload = b64url(cjson.encode(claims))
  local signing_input = header .. "." .. payload
  local mac, err = hmac.new(s.internal_jwt_secret, "sha256")
  if not mac then return nil, err end
  local sig, serr = mac:final(signing_input)
  if not sig then return nil, serr end
  return signing_input .. "." .. b64url(sig)
end

local function token_key(token)
  local d = digest.new("sha256")
  local h = d:final(token)
  return "ogna-guard:token:" .. to_hex(h)
end

-- Returns claims table for an active token, nil for inactive, or nil + err on failure.
-- The optional third return value overrides the cache TTL.
local function introspect(s, token)
  local client = http.new()
  client:set_timeout(s.introspection_timeout_ms or 3000)
  local res, err = client:request_uri(s.introspection_url, {
    method = "POST",
    body = "token=" .. ngx.escape_uri(token),
    headers = {
      ["Content-Type"] = "application/x-www-form-urlencoded",
      ["Accept"] = "application/json",
      ["Authorization"] = "Basic " .. ngx.encode_base64(s.client_id .. ":" .. s.client_secret),
      -- Zitadel resolves the instance from the Host header
      ["Host"] = s.auth_host,
      ["X-Forwarded-Proto"] = s.auth_scheme,
    },
    keepalive_timeout = 60000,
    keepalive_pool = 32,
  })
  if not res then
    return nil, "introspection request failed: " .. tostring(err)
  end
  if res.status ~= 200 then
    return nil, "introspection returned HTTP " .. res.status
  end
  local body = cjson.decode(res.body)
  if type(body) ~= "table" then
    return nil, "introspection returned invalid JSON"
  end
  if body.active ~= true or not body.sub then
    return nil
  end

  local ttl = s.active_cache_ttl or 5
  local exp = tonumber(body.exp)
  if exp then
    local remaining = exp - ngx.time()
    if remaining <= 0 then return nil end
    if remaining < ttl then ttl = remaining end
  end
  return body, nil, ttl
end

local function check_token(s, token)
  return kong.cache:get(token_key(token), {
    ttl = s.active_cache_ttl or 5,
    neg_ttl = s.inactive_cache_ttl or 300,
  }, introspect, s, token)
end

local function project_roles(claims)
  local roles = claims["urn:zitadel:iam:org:project:roles"]
  if type(roles) ~= "table" then return nil end
  local names = {}
  for name in pairs(roles) do
    names[#names + 1] = name
  end
  table.sort(names)
  return names
end

local function reject(status, message)
  if status == 401 then
    kong.response.set_header("WWW-Authenticate", 'Bearer realm="ogna"')
  end
  return kong.response.exit(status, { message = message })
end

function OgnaGuardHandler:access(conf)
  -- Never let clients set internal headers
  kong.service.request.clear_header("X-Hasura-Admin-Secret")
  kong.service.request.clear_header("X-Authenticated-User-Id")
  kong.service.request.clear_header("X-Authenticated-User-Role")
  kong.service.request.clear_header("X-Authenticated-User-Roles")
  kong.service.request.clear_header("X-Authenticated-Org-Id")
  kong.service.request.clear_header("X-Authenticated-Client-Id")

  local auth_header = kong.request.get_header("Authorization")
  local token = auth_header and auth_header:match("^[Bb]earer%s+(%S+)%s*$")

  if not token then
    -- Anything that is not a bearer token never reaches upstreams
    kong.service.request.clear_header("Authorization")
    if conf.require_auth then
      return reject(401, "Missing bearer token")
    end
    return
  end

  local s, serr = load_settings()
  if not s then
    kong.log.err("ogna-guard: ", serr)
    return reject(503, "Authentication verification unavailable")
  end

  local claims, err = check_token(s, token)
  if err then
    kong.log.err("ogna-guard: ", err)
    return reject(503, "Authentication verification unavailable")
  end

  local now = ngx.time()
  if claims and tonumber(claims.exp) and tonumber(claims.exp) <= now then
    claims = nil
  end

  if not claims then
    kong.service.request.clear_header("Authorization")
    if conf.require_auth then
      return reject(401, "Invalid or expired token")
    end
    return
  end

  local internal_ttl = s.internal_jwt_ttl or 300
  local internal_exp = now + internal_ttl
  if tonumber(claims.exp) and tonumber(claims.exp) < internal_exp then
    internal_exp = tonumber(claims.exp)
  end

  local roles = project_roles(claims)
  local org_id = claims["urn:zitadel:iam:user:resourceowner:id"]

  local internal, jerr = sign_internal_jwt(s, {
    iss = "ogna-gateway",
    aud = "authenticated",
    sub = tostring(claims.sub),
    role = "authenticated",
    iat = now,
    exp = internal_exp,
    email = claims.email,
    org_id = org_id,
    roles = roles,
    client_id = claims.client_id,
  })
  if not internal then
    kong.log.err("ogna-guard: failed to sign internal token: ", jerr)
    return reject(503, "Authentication verification unavailable")
  end

  kong.service.request.set_header("Authorization", "Bearer " .. internal)
  kong.service.request.set_header("X-Authenticated-User-Id", tostring(claims.sub))
  kong.service.request.set_header("X-Authenticated-User-Role", "authenticated")
  if roles and #roles > 0 then
    kong.service.request.set_header("X-Authenticated-User-Roles", table.concat(roles, ","))
  end
  if org_id then
    kong.service.request.set_header("X-Authenticated-Org-Id", tostring(org_id))
  end
  if claims.client_id then
    kong.service.request.set_header("X-Authenticated-Client-Id", tostring(claims.client_id))
  end
end

function OgnaGuardHandler:header_filter(conf)
  kong.response.set_header("X-Content-Type-Options", "nosniff")
  kong.response.set_header("X-Frame-Options", "DENY")
  kong.response.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
end

return OgnaGuardHandler
