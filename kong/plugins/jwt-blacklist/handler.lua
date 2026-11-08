local redis = require "resty.redis"
local jwt_parser = require "kong.plugins.jwt.jwt_parser"

local JwtBlacklistHandler = {
  VERSION = "1.3.0",
  PRIORITY = 900,
}

-- Private helper to retrieve the Redis password from config, env, or Docker secret
local function get_redis_password(conf)
    if conf and conf.redis_password and conf.redis_password ~= "" and not conf.redis_password:find("^%${") then
        return conf.redis_password:gsub("%s+", ""), nil
    end

    local env_pass = os.getenv("REDIS_PASSWORD")
    if env_pass and env_pass ~= "" then
        return env_pass:gsub("%s+", ""), nil
    end

    -- Fallback: Read the secret file mounted via Docker Secrets
    local path = "/run/secrets/redis_password"
    local f = io.open(path, "r")
    if not f then
        return nil, "Redis password not found in plugin config, REDIS_PASSWORD env, or " .. path
    end

    local pass = f:read("*all")
    f:close()

    if not pass or pass == "" then
        return nil, "Secret file is empty"
    end

    return pass:gsub("%s+", ""), nil
end

-- Private helper to retrieve the JWT secret from config or environment
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

-- Private helper to connect and authenticate to Redis
local function get_redis_conn(conf)
    local red = redis:new()
    red:set_timeout(conf.redis_timeout or 1000)

    local ok, err = red:connect(conf.redis_host, conf.redis_port)
    if not ok then
        return nil, "Connection failed: " .. (err or "unknown")
    end

    local pass, pass_err = get_redis_password(conf)
    if not pass then
        return nil, pass_err
    end

    -- Authenticate with Redis
    local res, auth_err = red:auth(pass)
    if not res then
        return nil, "Auth command failed: " .. (auth_err or "wrong password")
    end

    return red, nil
end

function JwtBlacklistHandler:access(conf)
  -- Strip sensitive internal headers to prevent client header spoofing
  kong.service.request.clear_header("X-Hasura-Admin-Secret")
  kong.service.request.clear_header("X-Authenticated-User-Id")
  kong.service.request.clear_header("X-Authenticated-User-Role")

  local path = kong.request.get_path()

  -- EXEMPTION: Never block the login or signup paths (anchored to start of path)
  if path:match("^/auth/token") or path:match("^/auth/signup") then
    return
  end

  -- Extract Authorization Header
  local auth_header = kong.request.get_header("Authorization")
  if not auth_header then return end

  local _, _, token = string.find(auth_header, "^Bearer%s+(.+)$")
  if not token then return end

  -- Parse JWT and extract Signature (as the unique fingerprint)
  local jwt, err = jwt_parser:new(token)
  if err or not jwt or not jwt.signature then
    kong.log.err("Failed to parse JWT signature")
    return kong.response.exit(401, { message = "Invalid JWT format" })
  end

  -- Verify HMAC signature before trusting claims or writing to Redis
  local secret = get_jwt_secret(conf)
  if secret and not jwt:verify_signature(secret) then
    kong.log.notice("REJECTED: Invalid JWT signature")
    return kong.response.exit(401, { message = "Invalid token signature" })
  end

  local fingerprint = jwt.signature
  local redis_key = "blocklist:token:" .. fingerprint
  local max_ttl = (conf and conf.max_ttl) or 86400

  -- LOGIC A: Handle Logout (The "Writer")
  if path:match("^/auth/logout") then
    local red, conn_err = get_redis_conn(conf)
    if red then
      local exp = (jwt.claims and tonumber(jwt.claims.exp)) or 0
      local ttl = exp - os.time()
      if ttl > max_ttl then
        ttl = max_ttl
      end

      if ttl > 0 then
        -- Set the key in Redis with a bounded TTL matching the token's remaining life
        local ok, set_err = red:setex(redis_key, ttl, "revoked")
        if ok then
            kong.log.notice("Token blacklisted successfully: ", fingerprint:sub(1,8))
        else
            kong.log.err("Redis SETEX failed: ", set_err)
        end
      end
      red:set_keepalive(10000, 100)
    else
      kong.log.err("Blacklist Logout Error: ", conn_err)
      if not (conf and conf.fail_open) then
        return kong.response.exit(503, { message = "Token revocation service unavailable" })
      end
    end
    -- Continue to GoTrue so it can handle its internal session cleanup
    return
  end

  -- LOGIC B: Guard Check (The "Reader")
  -- This protects all backend upstreams (FastAPI, Go, Rust, Hasura, Storage, etc.)
  local red, conn_err = get_redis_conn(conf)
  if not red then
    kong.log.err("Blacklist Guard Connection Error: ", conn_err)
    if conf and conf.fail_open then
      return
    end
    return kong.response.exit(503, { message = "Authentication verification service unavailable" })
  end

  local res, get_err = red:get(redis_key)
  red:set_keepalive(10000, 100)

  if get_err then
    kong.log.err("Redis GET error: ", get_err)
    if conf and conf.fail_open then
      return
    end
    return kong.response.exit(503, { message = "Authentication verification error" })
  end

  if type(res) == "string" then
    kong.log.notice("REJECTED: Blacklisted token signature detected")
    return kong.response.exit(401, { message = "Token has been revoked (logged out)" })
  end

  -- Forward verified user claims to upstream services
  if jwt.claims then
    if jwt.claims.sub then
      kong.service.request.set_header("X-Authenticated-User-Id", tostring(jwt.claims.sub))
    end
    if jwt.claims.role then
      kong.service.request.set_header("X-Authenticated-User-Role", tostring(jwt.claims.role))
    end
  end
end

function JwtBlacklistHandler:header_filter(conf)
  kong.response.set_header("X-Content-Type-Options", "nosniff")
  kong.response.set_header("X-Frame-Options", "DENY")
  kong.response.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
end

return JwtBlacklistHandler
