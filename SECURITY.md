# Security

Use the repository owner’s private security-reporting channel for vulnerability
reports. Include the affected commit, scenario, material effect, and a safe
reproduction using synthetic data.

Repository tests use invented fixtures. Credentials stay in an approved secret
manager; workflows receive short-lived identity credentials. Logs and receipts
use allowlisted fields and replace protected values with `[REDACTED]`.

AWS runtime configuration uses Parameter Store for non-sensitive settings and
Secrets Manager for rotatable credentials. The reference Terraform places
secret metadata and encryption controls in state while an approved rotation
workflow supplies plaintext versions. Workloads receive AWS access through
platform identity and exact-resource IAM policy. Full resource ARNs are checked
against the expected partition, Region, and account before retrieval.

The runtime cache is process-local, bounded, and time-limited. Expiry returns
control to the provider and caller recovery policy. Structured resolution
errors, safe value representations, and the logging guard expose metadata while
replacing runtime values. See
`docs/runbooks/aws-runtime-configuration-and-secret-rotation.md`.

Adopting teams establish threat models, identity reviews, network policy,
dependency governance, privacy review, retention, incident response, and
configured-environment qualification.
