local jwt_parser = require "kong.plugins.jwt.jwt_parser"

-- OGNA security guard.
-- Token revocation is handled by short-lived GoTrue access tokens (GOTRUE_JWT_EXP)
-- plus refresh-token revocation on logout, so no external store is needed here.
-- This plugin only:
--   * strips internal headers that clients must never be able to spoof,
--   * forwards verified user claims to upstreams as X-Authenticated-User-* headers,
--   * adds baseline security response headers.
local OgnaGuardHandler = {
  VERSION = "2.0.0",
  PRIORITY = 900,
}

-- Retrieve the JWT secret from config or environment
local function get_jwt_secret(conf)
    if conf and conf.jwt_secret and conf.jwt_secret ~= "" and not conf.jwt_secret:find("^%${") then
        return conf.jwt_secret
    end
    local env_secret = os.getenv("GOTRUE_JWT_SECRET")
    if env_secret and env_secret ~= "" then
        return env_secret
    end
    return nil
end

function OgnaGuardHandler:access(conf)
  -- Strip sensitive internal headers to prevent client header spoofing
  kong.service.request.clear_header("X-Hasura-Admin-Secret")
  kong.service.request.clear_header("X-Authenticated-User-Id")
  kong.service.request.clear_header("X-Authenticated-User-Role")

  local path = kong.request.get_path()

  -- Login and signup never carry a meaningful bearer token
  if path:match("^/auth/token") or path:match("^/auth/signup") then
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

  -- Only forward claims from a token we have verified ourselves
  local secret = get_jwt_secret(conf)
  if not secret then
    kong.log.err("GOTRUE_JWT_SECRET not configured; not forwarding user claims")
    return
  end
  if not jwt:verify_signature(secret) then
    return kong.response.exit(401, { message = "Invalid token signature" })
  end

  local claims = jwt.claims or {}
  local exp = tonumber(claims.exp)
  if exp and exp <= ngx.time() then
    -- Expired: protected routes are rejected by the jwt plugin; never forward stale identity
    return
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
