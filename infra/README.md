# Infrastructure reference

`docker-compose.yml` supplies a production-shape local environment: PostgreSQL,
S3-compatible object storage, and an OpenTelemetry collector with protected
attribute removal.

The PostgreSQL path uses a one-shot migrator after database health succeeds.
The migrator verifies the ordered SHA-256 manifest, applies pending migrations
under a transaction-level advisory lock, records immutable history, then binds
synthetic local role passwords and the tenant-verification key from mounted
secret files. The application proof waits for successful migration completion.

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
PostgreSQL files cover bootstrap, application, outbox, evidence, and migrator
passwords plus a 32-byte tenant HMAC key encoded as 64 lowercase hexadecimal
characters.

Secret versions enter Secrets Manager through the protected deployment or
rotation workflow described in
`../docs/runbooks/aws-runtime-configuration-and-secret-rotation.md`. Terraform
manages secret identity, recovery posture, encryption, and least-privilege
retrieval policy while plaintext remains in the dedicated secret lifecycle.
