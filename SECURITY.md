# Security

Use the repository owner's private security-reporting channel for vulnerability
reports. Include the affected commit, material effect, and a safe reproduction
using synthetic data.

Repository fixtures contain invented laboratory values. Runtime credentials
belong in Secrets Manager, mounted secret files, or the selected deployment
platform. Workflows use short-lived platform identity. Logs use allowlisted
fields and replace protected values with `[REDACTED]`.

AWS runtime settings use Parameter Store for non-sensitive configuration and
Secrets Manager for rotatable credentials. Terraform creates exact-resource IAM
policy and value-free secret metadata. AWS Powertools Parameters supplies
retrieval and provider caching. Workloads receive AWS access through platform
identity.

PostgreSQL row policies use a transaction-local tenant coordinate after the
application authenticates and authorizes the request. The selected identity
provider and application policy remain the authorization source.

GitHub Rulesets, required checks, dependency updates, and platform secret
scanning provide repository controls. Adopting teams add their threat model,
network policy, privacy program, retention, incident response, and configured
vendor assessment.
