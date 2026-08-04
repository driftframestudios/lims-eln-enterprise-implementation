# Infrastructure reference

`docker-compose.yml` supplies PostgreSQL 17, S3-compatible object storage, and
an OpenTelemetry Collector for local integration work.

The PostgreSQL path:

1. provisions migration-compatible cluster roles;
2. runs the pinned Flyway Community container with its dedicated migrator
   secret;
3. configures local application and Debezium connector passwords; and
4. makes the application database check available through the `proof` profile.

V001–V004 reference historical recovery and evidence roles, so fresh installs
create those identities while applying immutable history. The timestamped
successor migration removes their runtime tables and privileges. The active
application uses `laboratory_app`. A configured Debezium deployment can use the
read-only outbox identity plus the logical-replication privileges required by
its PostgreSQL hosting platform.

`debezium/outbox-event-router.properties` contains only Outbox Event Router
column mapping and INSERT-only behavior. Connector database, Kafka, TLS, and
schema-history credentials arrive from the deployment secret provider.

`terraform/` creates:

- Parameter Store values for non-sensitive runtime configuration;
- Secrets Manager metadata for rotatable vendor credentials;
- a customer-managed KMS key and alias; and
- an IAM policy scoped to the exact generated resources.

Secret versions enter Secrets Manager through the deployment or rotation
workflow. Terraform state and outputs remain value-free for secret contents.

Local files under `infra/secrets/*.txt` are excluded from version control. The
Compose profile expects bootstrap, migrator, application, outbox connector,
object-store passwords. These files contain synthetic local values only.
