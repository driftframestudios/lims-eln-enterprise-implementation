# Configured vendor evaluation

The repository supplies vendor-neutral contracts and synthetic examples. Once a
vendor sandbox exists, the hybrid team applies the same comparison surface to
each candidate.

## API and data behavior

- Create, update, and readback by stable external identity.
- Expected-revision conflict and exact request replay.
- Timeout before commit and timeout after commit.
- Pagination, throttling, retry hints, and rate limits.
- Tenant and project/container isolation.
- Exact decimal, unit, timestamp, controlled-vocabulary, and relationship
  round trips.
- Attachment byte and checksum parity.
- Complete export using a neutral reader.

## Operational behavior

- Published API and SDK versions and deprecation windows.
- Sandbox-to-production configuration portability.
- Workload identity, secret rotation, and service-account lifecycle.
- Audit export, telemetry integration, backup, restore, retention, and support.
- Measured latency, throughput, bulk limits, and recovery behavior at
  representative volume.

## Scientific and organizational evaluation

The evaluation package presents canonical examples, differences, and observed
behavior to laboratory, scientific, Quality, Regulatory, security, operations,
and executive participants through their established review systems. The
repository contains zero modeled approvers or simulated organizational
decisions.

## Comparison output

For each scenario, retain the candidate, version, environment, fixture identity,
request identity, input digest, response or exported data, latency, material
difference, and follow-up. The comparative-evidence repository can present
these results without importing vendor credentials or production records.
