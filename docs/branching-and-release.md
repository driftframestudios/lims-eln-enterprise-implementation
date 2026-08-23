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
| `experiment/<question>` | `develop` | `develop` when promoted, or archived tag | Time-boxed exploration with an explicit learning record |

## Local proof and optional maintenance branches

`python3 scripts/validate_repository.py` is the standing repository proof.
GitHub Actions rests disabled in repository settings at a **$0** budget. The
manual `implementation-proof` workflow becomes available only when a named
human enables Actions, sets `ENABLE_GITHUB_ACTIONS=true`, selects
`confirm_run`, and dispatches it. After the proof is read, set
`ENABLE_GITHUB_ACTIONS=false` and disable Actions in repository settings to
restore the resting state.

Dependency scheduling rests in `.github/dependabot.manual.yml`. A reviewed
rename to `.github/dependabot.yml` activates that schedule. When automation is
active, maintenance branches retain their bounded coordinate contract:

- Dependabot uses the complete
  `dependabot/github_actions/<dependency-update>` grammar and the
  `dependabot[bot]` pull-request identity.
- Renovate uses the complete `renovate/<dependency-update>` grammar and the
  `renovate[bot]` pull-request identity.
- Either flow targets `main` or `develop`; branch grammar, bot identity, and
  target must agree.

Each maintenance pull request continues through local validation, human review,
and the ordinary merge controls. The repository-local branch checker remains a
review aid. Its checker, tests, dependency-activation template, bounded-caller
sources, release manifests, and governance orientation surfaces retain explicit
ownership. Default-branch security updates are merged forward to `develop` so
both long-lived branches retain the correction.

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

- `main` and `develop` receive pull requests while hosted required-check sets
  remain empty in the $0 resting state;
- each pull request receives one approval, including code-owner review where a
  covered path changes;
- changes without an attributed author receive the configured extra approval;
- stale approvals are dismissed, the last push receives approval from another
  contributor, and review threads reach resolution;
- deletion and non-fast-forward protections preserve branch history;
- merge, squash, and rebase merge methods remain available;
- contract, fixture, migration, security, and expected-result changes receive
  an independent reviewer;
- any later manual workflow retains read-only permission, the repository-variable
  gate, dispatch confirmation, and a bounded timeout;
- any later reusable workflow is caller-owned and pinned by immutable commit SHA.

The current release-role manifest records this resting posture as an empty list
of hosted check contexts beside the retained human-review, code-owner,
deletion, non-fast-forward, and main-signature protections. A hosted context
becomes a separate future activation only after its name and funded execution
path are reviewed.
