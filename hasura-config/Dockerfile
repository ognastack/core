FROM hasura/graphql-engine:v2.40.0.cli-migrations-v3

COPY ./metadata /hasura-core-metadata
COPY ./metadata /hasura-metadata
COPY ./docker-entrypoint-ogna-hasura.sh /usr/local/bin/docker-entrypoint-ogna-hasura.sh

RUN chmod +x /usr/local/bin/docker-entrypoint-ogna-hasura.sh && \
    mkdir -p /user-hasura/tables

ENV HASURA_GRAPHQL_METADATA_DIR="/tmp/hasura-metadata"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-ogna-hasura.sh"]
CMD ["/bin/sh", "-c", "$HGE_BINARY serve"]
