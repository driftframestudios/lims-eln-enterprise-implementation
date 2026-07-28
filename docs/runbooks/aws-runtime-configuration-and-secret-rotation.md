# AWS runtime configuration and secret rotation

## Purpose

This runbook establishes one inspectable path from an approved AWS resource to
the narrow application boundary that consumes its value. The pattern uses:

- Systems Manager Parameter Store `String` parameters for non-sensitive runtime
  configuration such as endpoints, timeouts, and feature thresholds;
- Secrets Manager for credentials, API keys, signing material, and other values
  with a rotation lifecycle;
- a customer-managed KMS key for Secrets Manager;
- full resource ARNs validated against the expected AWS partition, Region, and
  account before each provider call;
- one least-privilege read policy attached to the workload identity by the
  deployment platform.

The Terraform stack creates secret metadata and its KMS boundary. A protected
deployment or rotation workflow supplies secret versions through an approved
operator path. This keeps secret plaintext out of Terraform configuration,
plans, state, outputs, repository fixtures, and command history.

## Source map

| Logical setting | Classification | AWS source | Selector | Cache ceiling |
|---|---|---|---|---|
| `vendor.base_url` | Configuration | Parameter Store `String` | explicit version or label when a release pins it | 60 minutes |
| `vendor.timeout_seconds` | Configuration | Parameter Store `String` | current version for operational tuning | 60 minutes |
| `vendor.credentials` | Secret | Secrets Manager | `AWSCURRENT` in steady state; explicit version/stage for rehearsal | 15 minutes |

Parameter Store `SecureString` values return a classification error in the
reference resolver. Values with a credential lifecycle belong in Secrets
Manager, where staging labels, rotation, and secret-specific audit events form
a coherent operational surface.

## Application composition

Production composition injects SDK clients with the ordinary boto3 method
shapes:

```python
import boto3

from lims_eln_implementation.runtime_configuration import (
    RuntimeConfigurationResolver,
    RuntimeSettingCatalog,
)

catalog = RuntimeSettingCatalog.from_mapping(catalog_document)
resolver = RuntimeConfigurationResolver(
    scope=catalog.scope,
    parameter_store=boto3.client("ssm", region_name=catalog.scope.region),
    secrets_manager=boto3.client(
        "secretsmanager",
        region_name=catalog.scope.region,
    ),
)

endpoint = resolver.resolve(catalog.require("vendor.base_url")).reveal()
client_id = resolver.resolve_json_member(
    catalog.require("vendor.credentials"),
    member="client_id",
).reveal()
```

The workload receives AWS credentials through its platform identity, such as an
ECS task role, EKS workload identity, or Lambda execution role. The repository
and application configuration carry resource identities rather than AWS access
keys.

## Cache and refresh posture

The resolver maintains a bounded, process-local memory cache. Configuration
entries accept a TTL through 3,600 seconds; secret entries accept a TTL through
900 seconds. A rotation observer can call `force_refresh=True` or invalidate a
logical name after the `AWSCURRENT` stage moves.

An expired entry leaves the cache before retrieval. A provider failure then
surfaces a structured error and returns control to the caller’s retry,
degradation, or readiness policy. The resolver supplies no stale secret after
expiry. Process restart clears the cache. The reference offers no disk-backed
cache, serialization hook, or cache-content diagnostic endpoint.

Python cannot promise deterministic erasure of immutable strings from process
memory. Adopting teams pair the bounded cache with hardened workload isolation,
core-dump policy, memory inspection controls, short-lived credentials, and a
rotation interval appropriate to the threat model.

## Rotation rehearsal

1. Create a candidate secret version through the protected rotation workflow.
2. Apply the `AWSPENDING` stage and validate authentication in the configured
   qualification environment using an explicit stage selector.
3. Move `AWSCURRENT` to the qualified version according to the provider’s
   rotation transaction.
4. Invalidate `vendor.credentials` in each long-running process or wait for the
   bounded TTL.
5. Observe successful provider calls, secret-version metadata, error rate, and
   latency through allowlisted telemetry.
6. Exercise `AWSPREVIOUS` during the rollback rehearsal.
7. Capture an observed receipt binding the secret version identifier, workload
   release, environment, performer, reviewer, and artifact digests. The receipt
   excludes plaintext values.

## Failure routing

`ConfigurationResolutionError` exposes a stable resolution code, logical name,
source, one-way resource fingerprint, retryability decision, and sanitized
provider code. Provider exception messages leave the raised exception chain.
The logging filter also replaces registered values in messages, arguments,
structured extras, stack text, and exception rendering before a handler emits
the record.

| Resolution code | Operational route |
|---|---|
| `resource_scope` | Reconcile the catalog with the deployed account and Region. |
| `classification` | Move credential-shaped material to the Secrets Manager entry. |
| `access` | Reconcile workload policy, KMS conditions, key state, and stage ownership. |
| `missing` | Reconcile deployment order and the selected version or stage. |
| `throttled` | Apply bounded retry with jitter and inspect retrieval volume. |
| `payload` | Restore the agreed secret shape through the rotation workflow. |
| `provider` | Route the sanitized event and provider request identity to operations. |

## Logging boundary

`ResolvedSetting.__repr__`, `safe_fields()`, and
`ConfigurationResolutionError.safe_fields()` remain value-free.
`RuntimeValueRedactionFilter` can register values at composition time and
replace exact matches before records reach handlers. Composition registers each
derived member returned by `resolve_json_member()` as well as any complete
resolved value that reaches a consumer. Application events use
structured, allowlisted fields. The filter is a compensating guard for
accidental exact-value interpolation; review, static analysis, log access
controls, and secret-scanning gates remain active layers.

## Qualification evidence

The production security and observability receipt remains open until the
configured workload demonstrates:

- the expected role and exact-resource IAM policy;
- successful KMS decryption only through Secrets Manager in the intended Region;
- CloudTrail coverage for secret retrieval and administrative changes;
- secret rotation, refresh, rollback, and revoked-version behavior;
- application readiness behavior during access, throttling, and provider
  availability events;
- logs, traces, metrics, crash artifacts, and receipts free of plaintext secret
  values;
- accountable Security, Operations, Quality, and Regulatory review for the
  stated intended use.

## Primary AWS references

- [Parameter Store overview](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)
- [Parameter Store IAM access](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-access.html)
- [Secrets Manager `GetSecretValue`](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html)
- [Secrets Manager cache posture](https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets_cache-python.html)
- [Secrets Manager KMS encryption](https://docs.aws.amazon.com/secretsmanager/latest/userguide/security-encryption.html)
