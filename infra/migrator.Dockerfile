FROM flyway/flyway:13.8.1-alpine@sha256:ca3c8eddac25811f84c9767c56a0610ce23cd4e61f59bb05778a78db42347b39

WORKDIR /flyway/project
COPY flyway.conf ./flyway.conf
COPY sql ./sql
COPY infra/run-flyway-with-secret.sh /usr/local/bin/run-flyway-with-secret

ENTRYPOINT ["/usr/local/bin/run-flyway-with-secret"]
CMD ["migrate"]
