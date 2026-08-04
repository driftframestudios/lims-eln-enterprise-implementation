FROM flyway/flyway:13.0.0-alpine@sha256:f3c8433401abf859ef9022584c8e6111684363ec490f737e749e9a4705ea32d0

WORKDIR /flyway/project
COPY flyway.conf ./flyway.conf
COPY sql ./sql
COPY infra/run-flyway-with-secret.sh /usr/local/bin/run-flyway-with-secret

ENTRYPOINT ["/usr/local/bin/run-flyway-with-secret"]
CMD ["migrate"]
