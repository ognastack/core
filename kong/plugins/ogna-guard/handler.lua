local jwt_parser = require "kong.plugins.jwt.jwt_parser"
local pgmoon = require "pgmoon"

-- OGNA security guard.
--   * strips internal headers that clients must never be able to spoof,
--   * verifies bearer tokens and rejects tokens whose GoTrue session has ended
--     (logout, "log out everywhere", deleted user, session timeout),
--   * forwards verified user claims to upstreams as X-Authenticated-User-* headers,
--   * adds baseline security response headers.
--
-- Revocation source of truth is GoTrue's own `auth.sessions` table: GoTrue deletes
-- the row on logout, so every access token carrying that `session_id` stops working.
-- Results are cached in Kong's shared cache so Postgres sees at most one lookup per
-- session every `session_cache_ttl` seconds.
local OgnaGuardHandler = {
  VERSION = "3.0.0",
  PRIORITY = 900,
}

local UUID_PATTERN = "^%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x$"

local function is_placeholder(value)
  return value == nil or value == "" or value:find("^%${") ~= nil
end

local function get_jwt_secret(conf)
  if conf and not is_placeholder(conf.jwt_secret) then
    return conf.jwt_secret
  end
  local env_secret = os.getenv("GOTRUE_JWT_SECRET")
  if env_secret and env_secret ~= "" then
    return env_secret
  end
  return nil
end

-- Returns true if the session is active, nil if it no longer exists, or nil + err on failure.
-- Returning nil (without err) lets kong.cache store it as a negative entry.
local function load_session(conf, session_id)
  local pg = pgmoon.new({
    host = conf.db_host,
    port = conf.db_port,
    database = conf.db_name,
    user = conf.db_user,
    password = conf.db_password,
  })
  pg:settimeout(conf.db_timeout)

  local ok, err = pg:connect()
  if not ok then
    return nil, "session store connect failed: " .. tostring(err)
  end

  local res, qerr = pg:query(
    "SELECT 1 FROM auth.sessions WHERE id = " .. pg:escape_literal(session_id) ..
    " AND (not_after IS NULL OR not_after > now()) LIMIT 1"
  )
  pg:keepalive(60000, 50)

  if not res then
    return nil, "session lookup failed: " .. tostring(qerr)
  end
  if type(res) == "table" and #res > 0 then
    return true
  end
  return nil
end

local function session_is_active(conf, session_id)
  local cache_key = "ogna-guard:session:" .. session_id
  local active, err = kong.cache:get(cache_key, {
    ttl = conf.session_cache_ttl,
    neg_ttl = conf.revoked_cache_ttl,
  }, load_session, conf, session_id)
  return active, err
end

function OgnaGuardHandler:access(conf)
  -- Strip sensitive internal headers to prevent client header spoofing
  kong.service.request.clear_header("X-Hasura-Admin-Secret")
  kong.service.request.clear_header("X-Authenticated-User-Id")
  kong.service.request.clear_header("X-Authenticated-User-Role")

  -- GoTrue validates its own sessions on /auth/*
  if kong.request.get_path():match("^/auth/") then
    return
  end

  local auth_header = kong.request.get_header("Authorization")
  if not auth_header then return end

  local _, _, token = string.find(auth_header, "^Bearer%s+(.+)$")
  if not token then return end

  local jwt, err = jwt_parser:new(token)
  if err or not jwt then
    return kong.response.exit(401, { message = "Invalid JWT format" })
  end

  local secret = get_jwt_secret(conf)
  if not secret then
    kong.log.err("GOTRUE_JWT_SECRET not configured")
    return kong.response.exit(503, { message = "Authentication verification unavailable" })
  end
  if not jwt:verify_signature(secret) then
    return kong.response.exit(401, { message = "Invalid token signature" })
  end

  local claims = jwt.claims or {}
  local exp = tonumber(claims.exp)
  if exp and exp <= ngx.time() then
    -- Protected routes are rejected by the jwt plugin; never forward stale identity
    return
  end

  -- Session check: tokens issued by GoTrue for a user always carry session_id.
  -- Tokens without one (e.g. service keys minted with the JWT secret) skip this check.
  local session_id = claims.session_id
  if session_id ~= nil then
    session_id = tostring(session_id)
    if not session_id:match(UUID_PATTERN) then
      return kong.response.exit(401, { message = "Invalid session" })
    end

    local active, serr = session_is_active(conf, session_id)
    if serr then
      kong.log.err("ogna-guard: ", serr)
      return kong.response.exit(503, { message = "Authentication verification unavailable" })
    end
    if not active then
      return kong.response.exit(401, { message = "Session has ended (logged out)" })
    end
  end

  if claims.sub then
    kong.service.request.set_header("X-Authenticated-User-Id", tostring(claims.sub))
  end
  if claims.role then
    kong.service.request.set_header("X-Authenticated-User-Role", tostring(claims.role))
  end
end

function OgnaGuardHandler:header_filter(conf)
  kong.response.set_header("X-Content-Type-Options", "nosniff")
  kong.response.set_header("X-Frame-Options", "DENY")
  kong.response.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
end

return OgnaGuardHandler
