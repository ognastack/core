FROM kong/kong-gateway:3.12.0.0

USER root

COPY ./plugins/ogna-guard /usr/local/share/lua/5.1/kong/plugins/ogna-guard
COPY ./kong.yaml /kong/kong.yaml
COPY ./docker-entrypoint-ogna.sh /usr/local/bin/docker-entrypoint-ogna.sh

RUN chmod +x /usr/local/bin/docker-entrypoint-ogna.sh && \
    chown -R kong:kong /kong /usr/local/share/lua/5.1/kong/plugins/ogna-guard

USER kong

ENV KONG_DATABASE="off" \
    KONG_DECLARATIVE_CONFIG="/kong/kong.yaml" \
    KONG_PLUGINS="bundled,cors,acme,ogna-guard" \
    KONG_LUA_SSL_TRUSTED_CERTIFICATE="system" \
    KONG_NGINX_HTTP_LUA_SHARED_DICT="acme_storage 10m"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-ogna.sh"]
CMD ["kong", "docker-start"]
