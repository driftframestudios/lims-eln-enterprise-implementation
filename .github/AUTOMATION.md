# Bounded hosted automation

## Pull-request proof

The repository allocates **100–300 GitHub-hosted runner minutes per month**.
`pull-request-proof` gives pull requests into `develop` and `main` one
review-visible repository check on Python 3.12. It uses one standard runner,
read-only repository permission, a ten-minute ceiling, and cancellation for a
superseded run. `python scripts/validate_repository.py` exercises the complete
repository-local contract and behavior suite without provisioning PostgreSQL.
Its dependency-free automation check parses the admitted YAML subset, derives
the effective controls, and requires them to agree with the release manifest.

Repository settings remain the authority for enabling Actions and selecting a
required check after its exact hosted name has been observed.

## Confirmed full proof

`implementation-proof` retains the two-version Python matrix, PostgreSQL 17
services, Flyway migration and upgrade paths, and the stable matrix-result
check. A named receiver can run it by setting `ENABLE_GITHUB_ACTIONS=true`,
selecting `confirm_run`, and dispatching the workflow when that broader evidence
is useful.

## Monthly dependency upkeep

`.github/dependabot.yml` checks GitHub Actions, Python, Docker, and Terraform
dependencies monthly. Version-update pull requests target `develop`; each
ecosystem holds at most two open updates, and minor and patch updates share one
reviewable group when available. Major updates retain an individual review
coordinate. GitHub reads this configuration from the default branch, so the
reviewed schedule begins after release promotion to `main` and sends its
version-update pull requests back to `develop`.

## Recovery

Local validation remains available through `python3 scripts/validate_repository.py`.
Setting `ENABLE_GITHUB_ACTIONS=false` rests the confirmed full proof. Repository
settings can pause all hosted execution. A reviewed source change can return
the dependency schedule to its manual filename while preserving the ecosystem
definitions and branch contract.
