# GitFlow-like branching and release

## Long-lived branches

- `main` contains released, receipt-bound versions.
- `develop` integrates the next release and remains deployable to the shared
  qualification environment.

## Short-lived branches

| Pattern | Starts from | Returns to | Purpose |
|---|---|---|---|
| `feature/<claim-or-receipt>` | `develop` | `develop` | Capability, specification, test, or receipt work |
| `release/<semver>` | `develop` | `main` and `develop` | Frozen release candidate and evidence assembly |
| `hotfix/<receipt-id>` | `main` | `main` and `develop` | Production correction with bounded evidence |
| `experiment/<question>` | `develop` | proposal or archived tag | Time-boxed exploration with an explicit learning record |

## Pull-request gates

Every pull request carries:

- stable claim and scenario IDs;
- success, failure twin, and recovery evidence;
- data-classification and privacy effect;
- migration and compatibility effect;
- operational signal and denominator;
- explicit assurance stage and limitations;
- independent engineering review.

Paths under `contracts/`, `sql/`, `infra/`, `security`, `migration`, `receipts/`,
and `acceptance` receive domain-specific review.

## Release sequence

1. Cut `release/<version>` from a passing `develop`.
2. Freeze contract and fixture digests.
3. Run configured-vendor, representative migration/restore, and
   production-shape security/observability tranches.
4. Assemble scientific, Quality, and Regulatory decision packets.
5. Resolve deviations through evidence, bounded conditions, or return-for-evidence.
6. Merge the accepted release to `main` and tag `v<version>`.
7. Merge the release result back to `develop`.
8. Publish the release manifest, source digest, evidence locators, and open receipts.

Git approval is an engineering act. Each organizational acceptance appears in
its own signed decision record.

## Branch protection target

Configure GitHub rulesets so that:

- `main` and `develop` receive pull requests and required status checks;
- `main` receives two fresh approvals, including a code owner;
- `develop` receives one fresh approval;
- release and hotfix merges preserve a linear, traceable history;
- contract, fixture, migration, security, and expected-result changes receive
  an independent reviewer;
- workflow permissions are read-only by default;
- reusable workflows are pinned by immutable commit SHA.

