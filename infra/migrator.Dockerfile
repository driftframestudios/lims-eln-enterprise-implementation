FROM flyway/flyway:13.4.0-alpine@sha256:66c0278f4398dd46b84d4108919a015b6ca03657a3d44ff2b349ad0602ace956

WORKDIR /flyway/project
COPY flyway.conf ./flyway.conf
COPY sql ./sql
COPY infra/run-flyway-with-secret.sh /usr/local/bin/run-flyway-with-secret

ENTRYPOINT ["/usr/local/bin/run-flyway-with-secret"]
CMD ["migrate"]
