# Local workbench entry v0.1

## Outcome and source coordinate

Run the Golden Specimen through an explicitly selected state adapter. The
`develop` branch carries this entry candidate; the signed `v0.3.2` release
retains its earlier accepted source. Source acceptance, release, and publication
have separate receivers.

`workbench/runtime.py` owns local composition. `workbench/postgres.py` owns
durable transactions, replay, and recovery. Flyway owns schema evolution.
The [infrastructure guide](../../infra/README.md) owns prepared database roles,
migration order, and secret delivery.

## Prepare one isolated application environment

Use the repository's Python 3.12 selection and a compatible uv installation:

```sh
uv sync --locked --extra contracts --extra postgres --extra test --no-editable
.venv/bin/lims-eln-workbench --adapter process_local
```

Open `http://127.0.0.1:8000/workbench`. This adapter retains state for the
process lifetime. Its readiness response reports `process_local`.

`uv.lock` owns exact application and test resolutions; `pyproject.toml`
retains the declared dependency ranges and existing optional profiles.
The `contracts` extra pins the reviewed Program 0.4.0 commit. Its first
installation uses the receiving operator's configured Git access. Dependencies
and a managed Python may require an initial download. Reusing the synchronized
environment invokes its installed executable directly and performs no package
resolution. Use `uv sync --locked --offline ...` only when the required
artifacts are already present in the local cache.

The ordinary contributor route may omit `--no-editable` for live source edits.
Installed-artifact checks use `--no-editable`; rebuilding after runtime source
changes keeps the observed artifact explicit. The [package handoff
runbook](program-package-handoff.v0.1.md) owns exact Program identity and resource
conformance. A sibling checkout remains an explicit development choice.

## Select durable state

Prepare PostgreSQL 17 through the existing role provisioner, Flyway V001-V005,
and role-bootstrap sequence. The local profile needs the `SYN-TENANT-A`
tenant, the ordinary `laboratory_app` login, and a verifier entry whose key
identifier matches `LIMS_WORKBENCH_TENANT_KEY_ID`. The existing Compose
bootstrap uses `local-compose-v1`.

Supply local files under an access-controlled directory:

```sh
LIMS_WORKBENCH_DB_HOST=127.0.0.1 \
LIMS_WORKBENCH_DB_PORT=5432 \
LIMS_WORKBENCH_DB_PASSWORD_FILE=infra/secrets/postgres_app_password.txt \
LIMS_WORKBENCH_TENANT_KEY_FILE=infra/secrets/postgres_tenant_hmac_key.txt \
.venv/bin/lims-eln-workbench --adapter postgresql
```

Choose the port exposed by the prepared database. The launcher defaults to
database `laboratory`; `LIMS_WORKBENCH_DB_NAME` selects another prepared
database. A different verifier identifier uses `LIMS_WORKBENCH_TENANT_KEY_ID`.
The service always connects as `laboratory_app`. Each new transaction receives
a fresh 60-second assertion for the fixed local tenant and workload identity.
The local issuer owns key material; the service receives the signed assertion.

Secret inputs are bounded regular files. Mounted files work directly; managed
secret symlinks require a deployment-specific receiver. Restart the local
application after coordinated credential rotation so its process-owned
configuration reads the new values.

The default HTTP binding is loopback. The reference issuer, three fixed actor
identities, and `X-Tenant-ID` consistency check serve the local workbench
profile. A remotely shared service receives authenticated identity and
deployment controls through Enterprise #38.

## Observe the selected adapter

- `GET /health/live` observes a running HTTP process.
- `GET /health/ready` reports the selected adapter and uses `Cache-Control:
  no-store`.
- PostgreSQL readiness binds the signed tenant, checks the ordinary application
  database identity, and verifies access to V005 workbench and invocation
  relations in a read-only transaction. The relation probes use `LIMIT 0`.
- An unavailable dependency returns HTTP 503 with a value-free status. A later
  successful probe restores HTTP 200 using the same service instance.
- Readiness establishes those dependency and permission checks. The complete
  journey, scientific mapping, broader deployment controls, and accountable
  acceptance retain their own observations.

Connection setup has a five-second timeout. Local SQL statements have a
ten-second timeout and lock acquisition has a three-second timeout. These are
bounded reference-profile settings, rather than a measured service-level
commitment.

## Replay, recovery, and retained state

Preserve the exact run identity, event time, and input bytes when requesting a
replay. The durable operation ledger decides completed replay, changed-content
collision, and in-progress/recovery state. A new independent experiment uses
new run and specimen identities. Application restart retains PostgreSQL state.

The existing reference grant admits fresh operations for one hour after
service construction. Restart renews that local grant; completed replay retains
its existing operation identity. Wider grant lifecycle policy belongs to the
authenticated service receiver.

A startup configuration error names its setting while secret values remain
local. A database readiness failure invites inspection of the prepared role,
key identifier, tenant, migration head, and reachability. Preserve the database
and existing secret files during recovery. Database reset remains an explicitly
scoped operator operation.

The complete container application, retained-secret setup command, comparison
export, and first-run/restart/reset journey remain the next acceptance slice
under Enterprise #43. This entry provides their shared runtime composition.

## Secret ownership and audience-fitting evidence

The local issuer and application share one operator-controlled process. The
issuer's closure separates code responsibility; operating-system and container
isolation provide separate deployment boundaries when those are required.

| Material | Receiving owner | Lifetime and sharing |
| --- | --- | --- |
| Database password | Connection factory for `laboratory_app` | Read from a protected local file at process construction; refresh through coordinated rotation and restart. |
| Tenant signing key | Fixed-tenant local issuer | Retained within the local process; only short-lived signed assertions cross into the service. |
| Bootstrap authority | Finite database preparation job | Prepare roles and verifier state, then exit; ordinary work uses the application role. |
| Detailed diagnostics | Authorized local operator | Retain locally for recovery; share normalized result and coverage through the PR. |

For shared evidence, select the fields needed for the receiving decision.
Consider what timing, identifiers, paths, neighboring metadata, and retained
history reveal together. Keep exact private lineage with its source owner;
preserve reproducibility through reviewed source, dependency, input, and
artifact identities. Secret values stay out of command arguments, image build
inputs, and public diagnostics. Existing container bootstrap transport receives
its dedicated repair and canary observations under Enterprise #45.

This applies the Field Guide's Leakage Modeling, AI as Bounded Caller,
Acquire-Release Spine, and Publication Boundaries and Proportionate Review.
The [container secret-lifecycle Issue](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/45)
owns the corresponding build, process, rotation, and export acceptance.

## Focused evidence and handback

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_workbench_runtime.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_workbench_api.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_workbench_postgres_adapter.py' -v
```

The unit route uses connector and contract-availability doubles. The configured
route uses the installed Program package, actual PostgreSQL, and the existing
Golden Specimen integration cases. Record Python/platform, source, lock, image,
migration, input, and result identities with the receiving PR; each observation
retains its own coverage. Public returns carry normalized outcomes. Protected
diagnostics and credentials stay with their local owner.

Sources: [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
and [Compose dependency readiness](https://docs.docker.com/compose/how-tos/startup-order/).
