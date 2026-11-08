local typedefs = require "kong.db.schema.typedefs"

return {
  name = "ogna-guard",
  fields = {
    { config = {
        type = "record",
        fields = {
          { jwt_secret = { type = "string", encrypted = true } },
          -- Read-only connection used to check auth.sessions
          { db_host = typedefs.host({ default = "postgres" }) },
          { db_port = typedefs.port({ default = 5432 }) },
          { db_name = { type = "string", required = true } },
          { db_user = { type = "string", default = "ogna_gateway" } },
          { db_password = { type = "string", required = true, encrypted = true } },
          { db_timeout = { type = "number", default = 2000 } },
          -- Seconds an "active" result is cached (max delay before a logout takes effect)
          { session_cache_ttl = { type = "number", default = 5 } },
          -- Seconds a "revoked" result is cached (revoked sessions never come back)
          { revoked_cache_ttl = { type = "number", default = 300 } },
        },
    }, },
  },
}
