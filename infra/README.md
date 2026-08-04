# Infrastructure reference

`docker-compose.yml` supplies a production-shape local environment: PostgreSQL,
S3-compatible object storage, and an OpenTelemetry collector with protected
attribute removal.

The PostgreSQL path first provisions and verifies cluster roles through a
separate privileged step. A one-shot, digest-pinned Flyway Community 13.0.0
container then applies versioned migrations, validates their checksums through
Flyway history, and exits. A following secret-bound step configures synthetic
local role passwords and the tenant-verification key. The application proof
waits for all three stages to complete successfully.

The Flyway image receives its JDBC URL and user as ordinary configuration. Its
small entry adapter reads the bootstrap password from the mounted secret file
and delegates directly to Flyway. Migration discovery, ordering, locking,
transactions, history, validation, status, and replay remain Flyway-owned.

`terraform/` supplies an AWS evidence and recovery baseline with:

- customer-managed encryption and rotation;
- private, versioned object storage;
- archival lifecycle and explicit retention;
- a backup vault awaiting an environment-owned plan, selection, vault lock,
  and restore schedule;
- encrypted operational logs.
- Parameter Store entries for non-sensitive runtime configuration;
- Secrets Manager metadata with customer-managed encryption;
- a value-free runtime catalog and exact-resource read policy.

The Terraform is an architectural baseline rather than an active backup
implementation. An adopting organization adds its
network, identity federation, database topology, workload runtime, backup plan,
regional design, policy-as-code, and accountable approval before deployment.

Local secret files live at `infra/secrets/*.txt`, remain outside version
control, and contain synthetic development credentials only. The required
PostgreSQL files cover bootstrap, application, outbox, recovery, evidence, and
migrator passwords plus a 32-byte tenant HMAC key encoded as 64 lowercase
hexadecimal characters.

Secret versions enter Secrets Manager through the protected deployment or
rotation workflow described in
`../docs/runbooks/aws-runtime-configuration-and-secret-rotation.md`. Terraform
manages secret identity, recovery posture, encryption, and least-privilege
retrieval policy while plaintext remains in the dedicated secret lifecycle.
