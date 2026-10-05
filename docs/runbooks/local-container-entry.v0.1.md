# Local container entry v0.1

## Outcome and ownership

Run the existing PostgreSQL workbench factory in a confined application
container. Integration source lives on `develop`; signed releases and
human-held `main` promotion retain their own acceptance. Enterprise #43
owns comparison export and complete journey acceptance. This route owns
container preparation, retained credentials, role grants, and recovery.

The application and local issuer share one operator-controlled process.
Remote identity belongs to #38. A Docker engine, its socket, and a host
administrator can inspect container memory and mounted secrets. Grant that
authority to the local operator; the application receives two read-only
credential files and its ordinary database role.

## Prepare exact artifacts and retained state

Use Python 3.12, uv, Docker with Compose, and a local Program checkout containing
the exact commit declared in `pyproject.toml`. Host Git credentials stay with
their credential owner. Initial packages/images require network access;
retained images and synchronized artifacts supply repeat execution.

Commit reviewed Enterprise source before building. The preparer archives exact
Git commits, builds the two packages, exports hash-locked dependencies, and
copies declared image inputs. Publication of a new context is atomic; previous
contexts remain available. Protected `.lims-build-*.log` files retain failed
build diagnostics. Success removes its log; uv caches completed downloads.

From the Enterprise repository root:

~~~sh
STATE_ROOT="$HOME/.local/state/lims-workbench"
mkdir -p "$STATE_ROOT"
chmod 700 "$STATE_ROOT"
python3 scripts/prepare_local_secrets.py "$STATE_ROOT/secrets"
python3 scripts/prepare_container_context.py "$STATE_ROOT/context-001" \
  --program-source /path/to/reviewed-program-checkout
export LIMS_SECRET_DIR="$STATE_ROOT/secrets"
export LIMS_APPLICATION_CONTEXT="$STATE_ROOT/context-001/application"
export LIMS_MIGRATOR_CONTEXT="$STATE_ROOT/context-001/migrator"
export LIMS_RUNTIME_UID="$(id -u)"
export LIMS_RUNTIME_GID="$(id -g)"
test "$LIMS_RUNTIME_UID" -gt 0
docker compose -p lims-local -f infra/docker-compose.yml --profile workbench \
  up -d --build application
~~~

Use a non-root operator account. Local file-backed secrets retain host
ownership; the application UID/GID matches that owner. The standalone image
defaults to `10001:10001`. Managed secret providers need an explicit receiving
ownership policy. A VM runtime needs access to the selected context,
source-mounted setup scripts, and state directory.

Readiness is at `http://127.0.0.1:8000/health/ready`; the workbench is at
`/workbench`. Completed setup jobs may have exited successfully while readiness
is pending. Inspect job exit statuses and application health separately.
`/health/live` observes the process; readiness exercises its database identity
and relations. Optional profiles are `object-storage` and `telemetry`.

## Credential lifetime

| Boundary | Mechanism | Recovery |
| --- | --- | --- |
| Preparation | External 0700 directory; 0600 files; serialized, exclusive atomic publication | Retain existing files and complete missing entries. |
| Build | Exact archives; two wheels; hash-checked registry dependencies; allowlisted contexts | Reuse a matching context or prepare a new named context. |
| Role setup | Protected temporary password file and SQL standard input; normalized output | Finite bootstrap job with retained administrative credential. |
| Migration | Flyway standard-input configuration; input file unlinked before execution | Inspect migration status while retaining Flyway history. |
| Application | Two files read at construction; ordinary login; fixed-tenant issuer | Coordinate rotation and recreation. |
| Public return | Source/profile and named normalized outcomes | Receiving PR; detailed diagnostics remain local. |

Prepared values are 32 random bytes encoded as 64 lowercase hexadecimal digits.
The shell receiver also admits bounded ASCII letters, digits, period,
underscore, tilde, and hyphen for established fixtures. Native file admission
retains its broader printable-ASCII contract. Other encodings receive an
explicit adapter.

Temporary files use a restrictive job-owned directory and cleanup on success,
failure, SIGINT, and SIGTERM. Each client runs in an owned session/process group. Termination reaches the
launcher and its descendants; a one-second grace interval precedes forced
group termination and a completed wait. Setup containers use an init process
to reap orphaned descendants. Cleanup follows confirmed group exit. An
unconfirmed exit retains protected temporary files for operator recovery. Forced host/process termination may retain
protected temporary data; remove the named stopped job or temporary storage
after preserving recovery evidence. Interrupted publication can retain a
private `.pending-*` entry. Reconcile any same-inode pending link while keeping
completed credentials intact before repeating preparation.

Setup sessions suppress statement/error-statement logging before credential
SQL. This applies to the stock local database configuration. Audit extensions,
privileged instrumentation, and managed providers retain separate inspection
boundaries. The pinned PostgreSQL image owns initial cluster setup; that
upstream lifecycle remains distinct from repository-owned setup and the
running application.

## Restart, independent experiment, rotation, and reset

Restart retains volumes and credentials. Reuse the Compose project and exact
request bytes for replay. New run/specimen identities create an independent
workbench experiment. A separate project, secret directory, and loopback port
provide a separate database experiment.

Rotate application/outbox/recovery/evidence passwords through a staged
directory. Keep bootstrap, migrator, and `local-compose-v1` key files unchanged:

1. Stop the application and retain the current secret directory and database.
2. Prepare a separate 0700 candidate directory; copy retained files with 0600
   permissions. Replace only intended role passwords using secure local
   generation. Values stay out of shell arguments and output.
3. Select the candidate via `LIMS_SECRET_DIR` and run only
   `docker compose ... run --rm --no-deps database-role-bootstrap`.
   Password updates and verifier admission share one database transaction.
4. A confirmed transaction rollback retains database passwords. A lost commit
   acknowledgement has an uncertain outcome. For either unsuccessful setup
   result, select the previous directory and reapply its passwords through the
   same bootstrap job using the retained administrator credential. Require a
   successful reconciliation before recreating the application.
5. A confirmed successful transaction followed by application failure has an explicit
   rollback: select the previous directory, rerun bootstrap, recreate the
   application, and observe readiness.
6. Readiness plus retained-state replay admits the candidate directory.
   Retire previous files through the operator's retention policy.

Bootstrap-password rotation and signing-key rollover require separately
reviewed procedures with their database/issuer owners. Existing volumes retain
their initialized administrator password; a replaced file changes its mounted
input.

Reset is a distinct operator action naming one project and its volumes.
Ordinary stop preserves volumes. Comparison export belongs to #43: write a
protected temporary artifact, flush and validate it, then publish atomically.
Failed export retains the previous accepted artifact and its input identity.

## Focused observations and handback

~~~sh
.venv/bin/python -m unittest discover -s tests -p 'test_local_container_security.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_database_migrations.py' -v
~~~

Canary checks cover child arguments/environments, protected input, output,
termination cleanup, malformed files, partial setup, and context admission
through controlled clients. Configured evidence separately covers actual image
configuration/history, user/mounts/writable paths, database role, first run,
restart, exact replay, changed-content rejection, and independent experiments.

Use one receiving PR for source/lock/image identities, actual platform,
normalized outcomes, and coverage. Keep logs, private paths, payloads, and
credentials local. Renew only observations affected by a changed boundary.

Sources: [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
[Compose trust model](https://docs.docker.com/compose/trust-model/),
[PostgreSQL password files](https://www.postgresql.org/docs/17/libpq-pgpass.html),
[Flyway standard-input configuration](https://documentation.red-gate.com/fd/config-files-parameter-277578859.html).
Return to [native entry](local-workbench-entry.v0.1.md) or
[infrastructure orientation](../../infra/README.md).
