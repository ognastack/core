FROM ghcr.io/amacneil/dbmate:main

COPY ./init/init.sql /db/core-init/000_init.sql
COPY ./post/ /db/core-migrations/
COPY ./entrypoint.sh /usr/local/bin/ogna-migrate.sh

RUN chmod +x /usr/local/bin/ogna-migrate.sh && \
    mkdir -p /db/migrations

ENTRYPOINT ["/usr/local/bin/ogna-migrate.sh"]
CMD ["up"]
