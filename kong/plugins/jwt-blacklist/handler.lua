local redis = require "resty.redis"
local jwt_parser = require "kong.plugins.jwt.jwt_parser"

local JwtBlacklistHandler = {
  VERSION = "1.2.3",
  PRIORITY = 900,
}

-- Private helper to connect and authenticate to Redis
local function get_redis_conn(conf)
    local red = redis:new()
    red:set_timeout(conf.redis_timeout or 1000)

    local ok, err = red:connect(conf.redis_host, conf.redis_port)
    if not ok then
        return nil, "Connection failed: " .. (err or "unknown")
    end

    -- Read the secret file mounted via Docker Secrets
    local path = "/run/secrets/redis_password"
    local f = io.open(path, "r")
    if not f then
        return nil, "Secret file not found at " .. path
    end

    local pass = f:read("*all")
    f:close()

    if not pass or pass == "" then
        return nil, "Secret file is empty"
    end

    -- Strip whitespace/newlines from the password string
    pass = pass:gsub("%s+", "")

    -- Authenticate with Redis
    local res, auth_err = red:auth(pass)
    if not res then
        return nil, "Auth command failed: " .. (auth_err or "wrong password")
    end

    return red, nil
end

function JwtBlacklistHandler:access(conf)
  local path = kong.request.get_path()

  -- EXEMPTION: Never block the login or signup paths
  if path:find("/auth/token") or path:find("/auth/signup") then
    return
  end

  -- Extract Authorization Header
  local auth_header = kong.request.get_header("Authorization")
  if not auth_header then return end

  local _, _, token = string.find(auth_header, "Bearer%s+(.+)")
  if not token then return end

  -- Parse JWT and extract Signature (as the unique fingerprint)
  local jwt, err = jwt_parser:new(token)
  if err or not jwt.signature then
    kong.log.err("Failed to parse JWT signature")
    return
  end

  local fingerprint = jwt.signature
  local redis_key = "blocklist:token:" .. fingerprint

  -- LOGIC A: Handle Logout (The "Writer")
  if path == "/auth/logout" then
    local red, conn_err = get_redis_conn(conf)
    if red then
      local exp = (jwt.claims and jwt.claims.exp) or 0
      local ttl = exp - os.time()

      if ttl > 0 then
        -- Set the key in Redis with a TTL matching the token's remaining life
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
    end
    -- Continue to GoTrue so it can handle its internal session cleanup
    return
  end

  -- LOGIC B: Guard Check (The "Reader")
  -- This protects all backend upstreams (FastAPI, Go, Rust, etc.)
  local red, conn_err = get_redis_conn(conf)
  if not red then
    kong.log.err("Blacklist Guard Connection Error: ", conn_err)
    return -- Fail Open: Allow traffic if Redis is down
  end

  local res, get_err = red:get(redis_key)
  red:set_keepalive(10000, 100)

  if get_err then
    kong.log.err("Redis GET error: ", get_err)
    return
  end

  if type(res) == "string" then
    kong.log.notice("REJECTED: Blacklisted token signature detected")
    return kong.response.exit(401, { message = "Token has been revoked (logged out)" })
  end
end

return JwtBlacklistHandler
