# Contributing

Every change should strengthen a traceable claim.

1. Start from `develop` using the branch family that matches the work:
   `feature/`, `fix/`, `chore/`, `experiment/`, `forecast/`, or `evidence/`.
2. Add or update a stable scenario, its failure twin, and its recovery behavior.
3. Keep fixtures synthetic and tenant-scoped.
4. Phrase comments and identifiers as desired-state attractors.
5. Preserve explicit privacy and safety boundaries, paired with the replacement
   behavior the system performs.
6. Run `python3 scripts/validate_repository.py`.
7. Open a pull request into `develop` with evidence and limitations.

Release candidates use `release/<version>` from `develop`, then return the
accepted result to both `main` and `develop`. Production corrections use
`hotfix/<receipt-id>` from `main` and return to both long-lived branches.
Details live in `docs/branching-and-release.md`.

Dependabot and Renovate maintenance pull requests follow the bot-bound branch
policy in the branching guide. Their updates retain the same tests, review,
release evidence, and merge-forward expectations as contributor changes.

A merge approval confirms engineering review. Scientific, Quality, Regulatory,
security, privacy, and production acceptance remain distinct, named decisions.
