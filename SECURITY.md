# Security

Use the repository owner’s private security-reporting channel for vulnerability
reports. Include the affected commit, scenario, material effect, and a safe
reproduction using synthetic data.

Repository tests use invented fixtures. Credentials stay in an approved secret
manager; workflows receive short-lived identity credentials. Logs and receipts
use allowlisted fields and replace protected values with `[REDACTED]`.

Adopting teams establish threat models, identity reviews, network policy,
dependency governance, privacy review, retention, incident response, and
configured-environment qualification.

