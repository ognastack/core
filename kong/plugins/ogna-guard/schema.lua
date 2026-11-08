return {
  name = "ogna-guard",
  fields = {
    { config = {
        type = "record",
        fields = {
          { jwt_secret = { type = "string", encrypted = true } },
        },
    }, },
  },
}
