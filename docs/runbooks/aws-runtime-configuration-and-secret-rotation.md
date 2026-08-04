# AWS runtime configuration and secret rotation

## Selected services

- Systems Manager Parameter Store holds non-sensitive endpoints, timeouts, and
  operational settings.
- Secrets Manager holds credentials and other rotatable secret values.
- A customer-managed KMS key encrypts Secrets Manager values.
- Workload IAM grants reads to the exact named parameters and secrets.
- AWS Powertools Parameters supplies retrieval, provider caching, transforms,
  decryption integration, and provider error behavior.

Terraform creates parameter values, secret metadata, KMS resources, and the
exact-resource read policy. A deployment or rotation workflow creates secret
versions. This keeps plaintext outside Terraform plans, state, outputs,
repository fixtures, and command history.

## Application composition

```python
import json

from lims_eln_implementation.runtime_configuration import (
    AwsRuntimeSettings,
    RuntimeSettingCatalog,
)

catalog = RuntimeSettingCatalog.from_mapping(catalog_document)
settings = AwsRuntimeSettings()

endpoint = settings.resolve(catalog.require("vendor.base_url"))
credentials = json.loads(
    settings.resolve(catalog.require("vendor.credentials"))
)
```

The resource catalog contains names, classifications, versions or stages, and
cache TTLs. It contains zero resolved values. The deployment supplies ordinary
AWS workload credentials through an ECS task role, EKS workload identity,
Lambda execution role, or equivalent platform identity.

Powertools caches parameters for the requested `max_age`. Rotation can use
`force_fetch=True` through a deployment-specific composition when immediate
refresh is required. Long-running services can also restart after moving the
`AWSCURRENT` stage.

## Rotation

1. Create a candidate Secrets Manager version through the protected rotation
   workflow.
2. Assign `AWSPENDING` and exercise authentication in the selected vendor
   sandbox.
3. Move `AWSCURRENT` to the qualified version.
4. Refresh or restart long-running consumers within the selected rotation
   window.
5. Observe provider calls, authentication results, latency, and error rate using
   identifiers and version metadata.
6. Exercise `AWSPREVIOUS` during the rollback rehearsal.
7. Retain the resulting CloudTrail and deployment records in the organization's
   established operational systems.

## Logging

Application logs carry logical setting names and AWS request identifiers. They
carry zero resolved configuration or secret values. `EvidenceRedactor` provides
an additional allowlist at telemetry boundaries. Platform log controls, secret
scanning, core-dump policy, and access review remain active operational layers.

## Failure routing

| Provider condition | Response |
|---|---|
| Access denied | Reconcile workload IAM, KMS conditions, and resource ARN. |
| Resource missing | Reconcile deployment order, parameter version, or secret stage. |
| Throttling | Use Powertools/provider retry behavior and inspect retrieval volume. |
| Invalid payload | Restore the released secret or configuration shape. |
| Provider availability | Apply service readiness and degradation policy. |

## References

- [AWS Powertools Parameters](https://docs.aws.amazon.com/powertools/python/latest/utilities/parameters/)
- [Parameter Store](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)
- [Secrets Manager `GetSecretValue`](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html)
- [Secrets Manager rotation](https://docs.aws.amazon.com/secretsmanager/latest/userguide/rotating-secrets.html)
