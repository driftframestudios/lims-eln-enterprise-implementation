# Infrastructure reference

`docker-compose.yml` supplies a production-shape local environment: PostgreSQL,
S3-compatible object storage, and an OpenTelemetry collector with protected
attribute removal.

`terraform/` supplies an AWS evidence and recovery baseline with:

- customer-managed encryption and rotation;
- private, versioned object storage;
- archival lifecycle and explicit retention;
- a backup vault;
- encrypted operational logs.
- Parameter Store entries for non-sensitive runtime configuration;
- Secrets Manager metadata with customer-managed encryption;
- a value-free runtime catalog and exact-resource read policy.

The Terraform is an architectural baseline. An adopting organization adds its
network, identity federation, database topology, workload runtime, backup plan,
regional design, policy-as-code, and accountable approval before deployment.

Local secret files live at `infra/secrets/*.txt`, remain outside version
control, and contain synthetic development credentials only.

Secret versions enter Secrets Manager through the protected deployment or
rotation workflow described in
`../docs/runbooks/aws-runtime-configuration-and-secret-rotation.md`. Terraform
manages secret identity, recovery posture, encryption, and least-privilege
retrieval policy while plaintext remains in the dedicated secret lifecycle.
