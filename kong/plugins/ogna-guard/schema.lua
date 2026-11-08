return {
  name = "ogna-guard",
  fields = {
    { config = {
        type = "record",
        fields = {
          -- true: reject requests without a valid token (401)
          -- false: forward identity when a valid token is present, otherwise pass through anonymously
          { require_auth = { type = "boolean", default = true } },
        },
    }, },
  },
}
