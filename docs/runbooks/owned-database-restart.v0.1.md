# Owned PostgreSQL restart and crash recovery

Use this explicitly activated proof to observe database-process recovery against
committed laboratory state. The harness creates three short-lived local clusters:
one for the laboratory journey, one for a controlled encounter failure, and one
for fresh re-entry. Each cluster has a new owner-only directory and Unix socket.
The command takes a PostgreSQL binary directory and expected major version; all
five selected binaries must report the same exact version.

## Prepare and run

Use the repository's Python 3.12 environment with the `postgres` and `test`
extras, and locally installed `postgres`, `initdb`, `pg_ctl`, `psql`, and
`pg_controldata` binaries. Clear any `PG*` environment overrides for this
invocation so libpq connects only through the harness's explicit local socket.
Run as an ordinary operating-system user who can create private temporary files
and start child processes.

```sh
uv sync --locked --extra postgres --extra test --no-editable
.venv/bin/python scripts/check_database_restart.py \
  --postgres-bin /path/to/postgresql/bin --expected-major 17
```

The same observation has an opt-in test entry:

```sh
LIMS_DATABASE_RESTART_CHECK=1 \
LIMS_RESTART_POSTGRES_BIN=/path/to/postgresql/bin \
LIMS_RESTART_EXPECTED_MAJOR=17 \
.venv/bin/python -m unittest tests.test_database_restart_proof -v
```

The standalone command returns a small JSON summary after successful cleanup.
It binds the source commit, working-tree state, current runtime and harness
bytes, exact engine and driver versions, migration source hashes, observation
time, durability settings, retained table counts and snapshot digest, and
observed scenarios. The pull request or receiving observation adds its performer
and independent reviewer. Keep that summary with the existing receiving work;
formal configured receipt admission retains its
[repository-native contract](../../.agents/skills/configured-environment-evidence-binding/SKILL.md).

## Observe the recovery boundary

The proof runs the repository role provisioner and each current versioned SQL
migration through `psql`, with one transaction per source file. It creates a
clearly labeled, authored history fixture with placeholder checksums so the
application can exercise its execution-provenance contract. The summary names
this fixture and binds the applied source files by SHA-256; the separate Flyway
CLI proof owns migration discovery, checksum validation and tool execution.
The helper is shared with the focused provenance test and operates only inside
the harness-owned disposable cluster. The proof then creates a
synthetic tenant and an invocation-generated HMAC verifier. The signed ordinary
`laboratory_app` role executes and reads the released Golden Specimen journey;
a privileged observer snapshots all public tables in one read-only repeatable
read transaction, including the worker-owned evidence tables. The verifier key
stays in process memory and the private database.

The complete snapshot sorts JSON rows in PostgreSQL and materializes them in
Python. Its work and memory grow with the returned tables; this deliberately
small synthetic fixture supplies recovery evidence. A representative workload
needs its own bounded retrieval, query-plan, and resource observation.

1. Seed the five-transition journey, custody, measurement, invocation, receipt,
   replay ledger, vendor projection, and pending outbox record.
2. Perform a fast database shutdown. Check the clean control-file state, start a
   new server, reconstruct the application adapter, and compare the full
   specimen and every public table. Exact Golden replay returns the same result
   with zero additional effects.
3. Hold a signed ordinary-role custody transfer open. Its transaction reads the
   changed position while an independent observer reads the original complete
   committed snapshot. Perform an immediate database shutdown with that
   transaction still open.
4. Check the interrupted control-file state, restart, and prove three distinct
   server lifetimes. The reconstructed adapter and full snapshot retain the
   committed journey; the pending position, custody event, and outbox record have rolled back.
   Golden replay again adds zero effects.
5. Retry the same custody transfer, commit exactly one event, aligned outbox
   record, and version change, preserve the earlier evidence, then replay it with zero
   additional effects.
6. Exercise a controlled exception after starting another owned cluster, check
   its cleanup, and start and clean up a fresh cluster for re-entry.

PostgreSQL documents [fast and immediate shutdown](https://www.postgresql.org/docs/17/server-shutdown.html)
as separate events: fast shutdown aborts open transactions and shuts down
cleanly; immediate shutdown requires WAL recovery at the next start. The
[`pg_ctl` interface](https://www.postgresql.org/docs/17/app-pg-ctl.html) supplies
bounded start and stop waits. The harness enables and observes `fsync`,
`synchronous_commit`, and `full_page_writes`; it also records checksum and WAL
settings. The [admitted native PostgreSQL 17.10 observation](../../receipts/owned-postgresql17-recovery-proof.json)
records all seven scenarios, 20 retained public tables, three server lifetimes,
and cleanup of three owned clusters at source
`83889fa87b740d824e82f5c9ffb0c515e6823148`. The engine was built from the bound
official source archive. Its observed `data_checksums=off` setting keeps
storage-corruption detection outside this recovery claim. The
[hosted PostgreSQL 17/Flyway receipt](../../receipts/hosted-postgresql-v007-proof.json)
records the separate containerized migration route. Earlier PostgreSQL 18.6
observations retain their named local scope.

## Resource ownership and failure recovery

The harness allocates fresh paths under the system's `/tmp` directory with mode
`0700`, disables TCP listeners, and rejects host authentication. Local trust is
confined to its private Unix socket and operating-system account. The current
account and explicitly selected binaries form the local operator trust boundary.
The harness accepts fresh cluster creation as its sole operational route;
retained clusters keep their existing owners.

Every process invocation has a finite timeout. Start and stop default to 30
seconds, with a five-second subprocess allowance. `--timeout-seconds` accepts
1 through 120 seconds. Driver connection, SQL statement, and lock waits also
have finite bounds. Before stopping a server, the harness checks the acquired
root and data-directory identities and the postmaster's data path and process
lifetime. A changed identity returns a private recovery route for operator
inspection. Cleanup keeps an existing proof error primary and reports secondary
cleanup failure separately.

Successful runs and ordinary Python failure paths stop the owned server before
removing its directory. If shutdown or ownership verification fails, the harness
retains the directory and prints its exact path locally. Inspect the owned
`postmaster.pid`, private logs and process identity there, then use the same
binary's `pg_ctl -D <owned-data-directory> -w -t 30 -m fast stop` after confirming
ownership. Remove that exact root after the process has stopped. Abrupt loss of
the harness process, such as `SIGKILL`, requires the same local operator recovery;
its owner-only temporary directory retains the recovery inputs. Keep those
paths and logs local; return the bounded result through the receiving PR.

This proof establishes local database process restart and crash recovery of its
synthetic state. Backup restore, point-in-time recovery, replication failover,
power-loss behavior, changed administrator durability settings, remote or cloud
environments, and production authorization each require their own observation
and accountable receiver.
