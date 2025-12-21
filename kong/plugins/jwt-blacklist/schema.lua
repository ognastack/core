local typedefs = require "kong.db.schema.typedefs"

return {
  name = "jwt-blacklist",
  fields = {
    { config = {
        type = "record",
        fields = {
          { redis_host = typedefs.host({ default = "127.0.0.1" }) },
          { redis_port = typedefs.port({ default = 6379 }) },
          { redis_password = { type = "string", encrypted = true } }, -- secure storage
          { redis_timeout = { type = "number", default = 1000 } },
        },
    }, },
  },
}