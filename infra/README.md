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

The Flyway image receives its JDBC URL and `laboratory_migrator` user as
ordinary configuration. Its small entry adapter reads only the migrator
credential from the mounted secret file and delegates directly to Flyway. The
bootstrap credential remains on the preceding role-provisioning service. The
role provisioner stores a target-database startup setting that selects the
no-login `laboratory_owner` role through an explicit non-inheriting membership.
It assigns the target `public` schema to that owner so migration-controlled
grants have one attributable authority.
The released connection callback verifies the authenticated login, effective
owner identity, and exact catalog binding. Migration discovery, ordering,
locking, transactions, history, validation, status, and replay remain
Flyway-owned.

The provisioner also gives `laboratory_owner` SET-only, non-inheriting,
non-admin membership in the no-login `laboratory_outbox_authority`. This narrow
edge supports V004 ownership transfer for outbox tables and trusted routines.
V004 brackets the ownership statements with a transaction-scoped schema
creation grant and its revocation. Both roles retain `NOBYPASSRLS`; hosted
catalog checks confirm the role graph, resulting object ownership, and absent
schema-creation privilege before workload proofs begin.

Every Compose support image carries its version tag and immutable
multi-architecture digest. The root `.dockerignore` keeps VCS metadata, local
environment files, caches, local receipts, key material, Terraform state, and
`infra/secrets` outside the migrator build context.

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
control through explicit root and directory-level ignore rules, and contain
synthetic development credentials only. The required
PostgreSQL files cover bootstrap, application, outbox, recovery, evidence, and
migrator passwords plus a 32-byte tenant HMAC key encoded as 64 lowercase
hexadecimal characters.

Secret versions enter Secrets Manager through the protected deployment or
rotation workflow described in
`../docs/runbooks/aws-runtime-configuration-and-secret-rotation.md`. Terraform
manages secret identity, recovery posture, encryption, and least-privilege
retrieval policy while plaintext remains in the dedicated secret lifecycle.
