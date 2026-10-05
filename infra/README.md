# Infrastructure reference

## Reader job

Use this directory to inspect a local service composition or an AWS evidence
and recovery baseline after the [repository's current state and branch
roles](../README.md#current-state-and-branch-roles) are clear. The root
[quickest proof](../README.md#quickest-proof-and-workbench) remains the shortest
route to source-owned behavior.

## Choose Compose or Terraform

| Need | Route | What it establishes |
| --- | --- | --- |
| Exercise the synthetic application without service infrastructure | Root [process-local workbench](../README.md#quickest-proof-and-workbench) | FastAPI and domain behavior in one Python process |
| Inspect the PostgreSQL, Flyway, object-storage, and telemetry service shape | [`docker-compose.yml`](docker-compose.yml) | A local composition and its pinned support images |
| Inspect the AWS encryption, storage, backup, configuration, and secret-access baseline | [`terraform/`](terraform) | Reviewable infrastructure declarations for an adopting environment |

## Prerequisites

The Compose route requires Docker with the Compose plugin, access to the pinned
container images, and synthetic local secret files at `infra/secrets/*.txt`.
The required PostgreSQL files cover bootstrap, application, outbox, recovery,
evidence, and migrator passwords plus a 32-byte tenant HMAC key encoded as 64
lowercase hexadecimal characters. Root and directory-level ignore rules keep
these local values outside version control and the migrator build context.

The Terraform route requires Terraform 1.8 or newer and provider-registry
access for initialization. Static initialization and validation inspect the
configuration. Planning or applying it additionally requires an approved AWS
account, region, identity, state design, environment inputs, and accountable
deployment decision.

## Compose path

[`docker-compose.yml`](docker-compose.yml) supplies a deployment-shaped local
environment: PostgreSQL, S3-compatible object storage, and an OpenTelemetry
collector with protected-attribute removal.

The PostgreSQL path first provisions and verifies cluster roles through a
separate privileged step. A one-shot, digest-pinned Flyway Community 13.8.1
container then applies versioned migrations, validates their checksums through
Flyway history, and exits. A following secret-bound step configures synthetic
local role passwords and the tenant-verification key. The application proof
waits for all three stages to complete successfully.

The exact 13.8.1 hosted receipt binds the selected source coordinate to its
configured PostgreSQL proof. That proof builds the repository migrator image
and exercises its shell, secret-reading entrypoint, Flyway CLI, JRE, JDBC
connection, and connection callback before the PostgreSQL migration matrix
runs.

The Flyway image receives its JDBC URL and `laboratory_migrator` user as
ordinary configuration. Its small entry adapter reads the migrator credential
from the mounted secret file and delegates directly to Flyway. The preceding
role-provisioning service owns the bootstrap credential. The role provisioner
stores a target-database startup setting that selects the no-login
`laboratory_owner` role through an explicit non-inheriting membership and
assigns the target `public` schema to that owner. The released connection
callback verifies the authenticated login, effective owner identity, and exact
catalog binding. Migration discovery, ordering, locking, transactions, history,
validation, status, and replay remain Flyway-owned.

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

## Terraform path

[`terraform/`](terraform) supplies an AWS evidence and recovery baseline with:

- customer-managed encryption and rotation;
- private, versioned object storage;
- archival lifecycle and explicit retention;
- a backup vault awaiting an environment-owned plan, selection, vault lock,
  and restore schedule;
- encrypted operational logs;
- Parameter Store entries for non-sensitive runtime configuration;
- Secrets Manager metadata with customer-managed encryption; and
- a value-free runtime catalog and exact-resource read policy.

An adopting organization completes this architectural baseline with its
network, identity federation, database topology, workload runtime, backup plan,
regional design, policy-as-code, and accountable approval before deployment.
Secret versions enter Secrets Manager through the protected deployment or
rotation workflow in the [AWS runtime configuration and secret rotation
runbook](../docs/runbooks/aws-runtime-configuration-and-secret-rotation.md).
Terraform manages secret identity, recovery posture, encryption, and
least-privilege retrieval policy while plaintext remains in the dedicated
secret lifecycle.

## Validation

Run the source-owned repository proof from the repository root:

```sh
python3 scripts/validate_repository.py
```

When the corresponding tools are available, inspect each infrastructure form
directly:

```sh
docker compose -f infra/docker-compose.yml config --quiet
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
```

The repository proof validates pinned image coordinates, Terraform source
contracts, migration artifacts, and related tests. Compose configuration
inspection establishes local interpolation and structural validity. Terraform
initialization and validation establish provider resolution and static module
validity. The manual [`ci.yml`](../.github/workflows/ci.yml) configured-evidence
route can exercise the database composition and retains its result in a named,
value-free receipt.

## Evidence boundary

The Compose and Terraform routes provide engineering evidence for their exact
source, tools, configuration, and environment. Production qualification comes
from a configured observation that binds those coordinates, representative
scenarios, artifacts, limitations, review, and accountable intended-use
acceptance.

## Return

Return to the [root orientation](../README.md) for current branch and release
state, the [migration guide](../docs/database-migrations.md) for database
evolution, or the [AWS runbook](../docs/runbooks/aws-runtime-configuration-and-secret-rotation.md)
for configuration and secret-rotation operations.

## Native workbench receiver

The [local entry runbook](../docs/runbooks/local-workbench-entry.v0.1.md) uses
this prepared database with the explicit PostgreSQL launcher and dependency
readiness probe. The current Compose file supplies supporting services; the
application image and complete container journey continue under Enterprise #43.
The native application and future container service share the same runtime
composition rather than separate implementations of tenant binding or replay.
