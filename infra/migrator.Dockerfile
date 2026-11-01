FROM flyway/flyway:13.11.1-alpine@sha256:ca71f3b89abb622198c0c462bb66bada4d0fecc64c4998f2c76a751cd969dcef

WORKDIR /flyway/project
COPY flyway.conf ./flyway.conf
COPY sql ./sql
COPY infra/run-flyway-with-secret.sh /usr/local/bin/run-flyway-with-secret

COPY infra/secret-files.sh /usr/local/lib/lims/secret-files.sh

ENTRYPOINT ["/usr/local/bin/run-flyway-with-secret"]
CMD ["migrate"]
