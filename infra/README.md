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

The Terraform is an architectural baseline. An adopting organization adds its
network, identity federation, database topology, workload runtime, backup plan,
regional design, policy-as-code, and accountable approval before deployment.

Local secret files live at `infra/secrets/*.txt`, remain outside version
control, and contain synthetic development credentials only.

