# Contributing

Changes should strengthen a material LIMS/ELN vendor-evaluation or data-integrity
capability.

1. Describe the domain or integration behavior being changed.
2. Reuse an established framework for migration, retry, event delivery,
   telemetry, configuration, secrets, and repository policy.
3. Add the smallest test that proves the observable behavior and its failure
   twin.
4. Keep fixtures synthetic and tenant-scoped.
5. Use affirmative comments that state the desired behavior and recovery path.
6. Run `make validate`, `make test`, and `make build`.
7. Open a pull request with material effect, compatibility, verification, and
   configured-environment gaps.

GitFlow-like branch names remain a collaboration convention. GitHub Rulesets
and required checks enforce protected-branch behavior at the hosting boundary.
The repository contains no second branch-policy implementation.
