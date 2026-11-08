local typedefs = require "kong.db.schema.typedefs"

return {
  name = "jwt-blacklist",
  fields = {
    { config = {
        type = "record",
        fields = {
          { redis_host = typedefs.host({ default = "127.0.0.1" }) },
          { redis_port = typedefs.port({ default = 6379 }) },
          { redis_password = { type = "string", encrypted = true } },
          { redis_timeout = { type = "number", default = 1000 } },
          { jwt_secret = { type = "string", encrypted = true } },
          { max_ttl = { type = "number", default = 86400 } },
          { fail_open = { type = "boolean", default = false } },
        },
    }, },
  },
}
