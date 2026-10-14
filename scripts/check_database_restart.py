#!/usr/bin/env python3
"""Exercise local database process recovery in an invocation-owned cluster."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lims_eln_implementation.security import (  # noqa: E402
    PostgresTenantBinding,
    SignedTenantContext,
    tenant_context_signing_message,
)
from lims_eln_implementation.workbench.postgres import PostgresWorkbenchService  # noqa: E402


class RestartProofError(RuntimeError):
    """A bounded assertion or owned-resource operation requires attention."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RestartProofError(message)


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class OwnedPostgres:
    """Own one fresh private directory and its PostgreSQL process lifetimes."""

    def __init__(self, binaries: Path, expected_major: int, timeout: int = 30):
        require(1 <= timeout <= 120, "process timeout requires 1 through 120 seconds")
        require(not any(name.startswith("PG") for name in os.environ),
                "run the owned-cluster proof with PostgreSQL environment overrides cleared")
        self.binaries = binaries.resolve(strict=True)
        self.timeout = timeout
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        self.environment["LC_ALL"] = "C"
        self.root: Path | None = None
        self._root_identity: tuple[int, int] | None = None
        self._data_identity: tuple[int, int] | None = None
        self._process_identity: tuple[int, str, int] | None = None
        self._start_after: int | None = None
        versions = {}
        for name in ("postgres", "initdb", "pg_ctl", "psql", "pg_controldata"):
            result = self._command(name, "--version")
            match = re.search(r"\(PostgreSQL\) (\d+(?:\.\d+)*)", result.stdout)
            require(match is not None, "each explicit PostgreSQL binary requires a version")
            versions[name] = match.group(1)
        require(len(set(versions.values())) == 1, "PostgreSQL binaries require one exact version")
        self.version = versions["postgres"]
        require(int(self.version.split(".")[0]) == expected_major,
                "PostgreSQL major differs from the explicitly selected major")

    def _command(self, name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [str(self.binaries / name), *arguments], env=self.environment,
                capture_output=True, text=True, timeout=self.timeout + 5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RestartProofError(f"owned PostgreSQL {name} invocation failed") from error
        if result.returncode:
            if self.root is not None:
                with (self.root / "commands.log").open("a", encoding="utf-8") as output:
                    output.write(result.stdout + result.stderr)
            raise RestartProofError(f"owned PostgreSQL {name} returned failure")
        return result

    @property
    def data(self) -> Path:
        require(self.root is not None, "cluster requires its owned root")
        return self.root / "data"

    @property
    def socket(self) -> Path:
        require(self.root is not None, "cluster requires its owned root")
        return self.root / "socket"

    @staticmethod
    def _directory_identity(path: Path) -> tuple[int, int]:
        observed = path.lstat()
        require(stat.S_ISDIR(observed.st_mode) and observed.st_uid == os.getuid(),
                "cluster path requires an owned regular directory")
        require(stat.S_IMODE(observed.st_mode) == 0o700,
                "cluster directory requires owner-only access")
        return observed.st_dev, observed.st_ino

    def _check_paths(self) -> None:
        require(self.root is not None and self._root_identity is not None,
                "cluster cleanup requires an acquired root")
        require(self._directory_identity(self.root) == self._root_identity,
                "cluster root identity changed; retain it for private recovery")
        if self._data_identity is not None:
            require(self._directory_identity(self.data) == self._data_identity,
                    "cluster data identity changed; retain it for private recovery")

    def _read_process_identity(self) -> tuple[int, str, int]:
        self._check_paths()
        lines = (self.data / "postmaster.pid").read_text(encoding="utf-8").splitlines()
        require(len(lines) >= 3, "owned postmaster requires complete process identity")
        identity = (int(lines[0]), lines[1], int(lines[2]))
        require(identity[0] > 0 and identity[1] == str(self.data),
                "postmaster requires the invocation-owned data directory")
        require(self._start_after is not None and identity[2] >= self._start_after,
                "postmaster requires the invocation-owned process lifetime")
        return identity

    def __enter__(self) -> OwnedPostgres:
        self.root = Path(tempfile.mkdtemp(prefix="lims-restart-", dir="/tmp")).resolve()
        self._root_identity = self._directory_identity(self.root)
        try:
            self.socket.mkdir(mode=0o700)
            self._command("initdb", "-D", str(self.data), "--no-locale", "--encoding=UTF8",
                          "--auth-local=trust", "--auth-host=reject", "--username=proof_owner")
            self._data_identity = self._directory_identity(self.data)
            self.start()
            return self
        except BaseException as error:
            self._cleanup_preserving(error)
            raise

    def start(self) -> tuple[int, str, int]:
        self._check_paths()
        require(self._process_identity is None and not (self.data / "postmaster.pid").exists(),
                "cluster start requires a stopped owned process")
        self._start_after = int(time.time())
        self._command(
            "pg_ctl", "-D", str(self.data), "-l", str(self.root / "server.log"),
            "-p", str(self.binaries / "postgres"), "-w", "-t", str(self.timeout),
            "-o", f"-c listen_addresses='' -k {self.socket} -p 5432 "
                  "-c fsync=on -c synchronous_commit=on -c full_page_writes=on "
                  "-c log_statement=none -c log_min_error_statement=panic "
                  "-c log_parameter_max_length_on_error=0", "start",
        )
        self._process_identity = self._read_process_identity()
        return self._process_identity

    def stop(self, mode: str = "fast") -> None:
        require(mode in {"fast", "immediate"}, "shutdown requires an explicit supported mode")
        self._check_paths()
        if not (self.data / "postmaster.pid").exists():
            require(self._process_identity is None,
                    "owned process identity disappeared; retain its recovery evidence")
            return
        observed = self._read_process_identity()
        require(self._process_identity is None or observed == self._process_identity,
                "postmaster lifetime changed; retain it for private recovery")
        self._command("pg_ctl", "-D", str(self.data), "-w", "-t", str(self.timeout),
                      "-m", mode, "stop")
        require(not (self.data / "postmaster.pid").exists(), "stopped postmaster retains its pid file")
        self._process_identity = None

    def control_state(self) -> str:
        self._check_paths()
        output = self._command("pg_controldata", "-D", str(self.data)).stdout
        match = re.search(r"^Database cluster state:\s*(.+)$", output, re.MULTILINE)
        require(match is not None, "cluster control data requires a shutdown state")
        return match.group(1).strip()

    def connect(self, user: str):
        import psycopg
        # libpq environment defaults can route connections; the CLI owns a clean PG namespace.
        require(not any(name.startswith("PG") for name in os.environ),
                "run the owned-cluster proof with PostgreSQL environment overrides cleared")
        return psycopg.connect(
            host=str(self.socket), port=5432, dbname="postgres", user=user,
            connect_timeout=self.timeout, options="-c statement_timeout=15000 -c lock_timeout=5000",
        )

    def install(self) -> list[dict[str, str]]:
        sources = [ROOT / "database/provision_cluster_roles.sql", *sorted((ROOT / "sql").glob("V*.sql"))]
        for index, path in enumerate(sources):
            self._command("psql", "--no-psqlrc", "-h", str(self.socket), "-p", "5432",
                          "-U", "proof_owner" if index == 0 else "laboratory_migrator",
                          "-d", "postgres", "--set", "ON_ERROR_STOP=1", "--single-transaction",
                          "-f", str(path))
        return [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p.read_bytes()).hexdigest()}
                for p in sources]

    def close(self) -> None:
        self._check_paths()
        if self._data_identity is not None:
            self.stop()
        self._check_paths()
        shutil.rmtree(self.root)
        self.root = None

    def _cleanup_preserving(self, primary: BaseException | None) -> None:
        try:
            self.close()
        except BaseException as cleanup_error:
            recovery = f"owned cluster retained for private recovery: {self.root}"
            if primary is not None:
                primary.add_note(recovery)
                primary.add_note(f"cleanup requires attention: {type(cleanup_error).__name__}")
            else:
                raise RestartProofError(recovery) from cleanup_error

    def __exit__(self, kind, error, traceback) -> None:
        self._cleanup_preserving(error)


TENANT = "SYN-RESTART-TENANT"
SPECIMEN = "SYN-RESTART-SPECIMEN"
RUN = "SYN-RESTART-RUN"
CALLER = "SYN-RESTART-SERVICE"
OCCURRED = datetime(2026, 10, 14, 12, tzinfo=UTC)


class LaboratoryProof:
    def __init__(self, cluster: OwnedPostgres):
        self.cluster = cluster
        self.key = secrets.token_bytes(32)
        with cluster.connect("proof_owner") as connection:
            connection.execute("insert into public.tenant (tenant_id,display_name) values (%s,%s)",
                               (TENANT, "Synthetic restart tenant"))
            connection.execute(
                "insert into laboratory_security.tenant_context_key "
                "(key_id,secret_material,valid_from_utc,valid_until_utc) "
                "values (%s,%s,clock_timestamp()-interval '1 hour',clock_timestamp()+interval '1 day')",
                ("restart-proof", self.key),
            )

    def context(self, tenant_id: str) -> SignedTenantContext:
        issued = int(time.time())
        fields = dict(tenant_id=tenant_id, subject_id=CALLER, key_id="restart-proof",
                      issued_at_epoch=issued, expires_at_epoch=issued + 300,
                      nonce="SYN-RESTART-" + secrets.token_hex(16))
        return SignedTenantContext(**fields, signature_hex=hmac.new(
            self.key, tenant_context_signing_message(**fields), sha256).hexdigest())

    def service(self) -> PostgresWorkbenchService:
        service = PostgresWorkbenchService(lambda: self.cluster.connect("laboratory_app"),
                                          tenant_context_provider=self.context,
                                          tenant_id=TENANT, caller_id=CALLER)
        service.check_ready()
        return service

    def run(self, service: PostgresWorkbenchService) -> dict:
        return service.run_golden_specimen(
            run_id=RUN, tenant_id=TENANT, specimen_id=SPECIMEN,
            actor_id="SYN-ACTOR-01", scientist_id="SYN-SCIENTIST-01", quality_actor_id="SYN-QUALITY-01",
            occurred_at=OCCURRED,
            raw_instrument_json=b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}',
            vendor_payload={"status": "under_review"},
        )

    def snapshot(self) -> dict[str, list]:
        # A privileged read observes every public evidence table, including worker-owned ledgers.
        # Application effects and reads above retain the signed ordinary-role boundary.
        from psycopg import sql
        with self.cluster.connect("proof_owner") as connection:
            connection.execute("set transaction isolation level repeatable read, read only")
            names = connection.execute(
                "select tablename from pg_catalog.pg_tables where schemaname='public' order by tablename"
            ).fetchall()
            return {
                name: [row[0] for row in connection.execute(sql.SQL(
                    "select to_jsonb(t) from public.{} as t order by to_jsonb(t)::text"
                ).format(sql.Identifier(name))).fetchall()]
                for (name,) in names
            }

    def transfer(self, connection) -> None:
        with connection.cursor() as cursor:
            PostgresTenantBinding(self.context(TENANT)).bind(cursor, expected_tenant_id=TENANT)
            cursor.execute("select custody_version from public.record_custody_transfer(%s,%s,%s,1,%s,%s)",
                           (SPECIMEN, "SYN-LAB-A/ARCHIVE", "SYN-ACTOR-01",
                            RUN + ":archive", OCCURRED + timedelta(minutes=1)))
            require(cursor.fetchone() == (2,), "custody transfer requires resulting version two")
            cursor.execute("select custody_version,location_code from public.custody_position "
                           "where tenant_id=%s and specimen_id=%s", (TENANT, SPECIMEN))
            require(cursor.fetchone() == (2, "SYN-LAB-A/ARCHIVE"),
                    "pending transfer requires an observable transaction-local effect")
            cursor.execute("select aggregate_version,payload->>'transfer_id',delivery_state,delivery_attempts "
                           "from public.transactional_outbox where tenant_id=%s and message_id=%s",
                           (TENANT, RUN + ":archive"))
            require(cursor.fetchone() == (2, RUN + ":archive", "ready", 0),
                    "pending transfer requires its aligned ready outbox record")


def source_coordinate() -> dict:
    paths = [Path(__file__), ROOT / "pyproject.toml", ROOT / "uv.lock",
             *sorted((ROOT / "src").rglob("*.py"))]
    digest = sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True,
                           capture_output=True, text=True, timeout=5).stdout != ""
    return {"commit": revision, "working_tree_changed": dirty,
            "runtime_and_harness_sha256": digest.hexdigest()}


def exercise(binaries: Path, expected_major: int, timeout: int = 30) -> dict:
    import psycopg
    started = datetime.now(UTC).isoformat()
    source = source_coordinate()
    with OwnedPostgres(binaries, expected_major, timeout) as cluster:
        migrations = cluster.install()
        proof = LaboratoryProof(cluster)
        original = proof.run(proof.service())
        require(original["specimen"]["state"] == "released" and original["specimen"]["version"] == 5,
                "seeded journey requires five accepted lifecycle transitions")
        before = proof.snapshot()
        for table in ("specimen", "specimen_event", "custody_event", "instrument_measurement",
                      "bounded_call_invocation", "bounded_call_receipt", "transactional_outbox"):
            require(bool(before[table]), "seeded recovery requires populated laboratory evidence")
        with cluster.connect("proof_owner") as connection:
            settings = dict(connection.execute(
                "select name,setting from pg_catalog.pg_settings where name in "
                "('fsync','synchronous_commit','full_page_writes','wal_level','data_checksums')"
            ).fetchall())
            start_time = connection.execute("select pg_postmaster_start_time()::text").fetchone()[0]
        require(all(settings[name] == "on" for name in ("fsync", "synchronous_commit", "full_page_writes")),
                "recovery observation requires enabled durability settings")
        lifetimes = [cluster._process_identity]
        cluster.stop("fast")
        require(cluster.control_state() == "shut down", "fast shutdown requires a clean control state")
        lifetimes.append(cluster.start())
        reloaded = proof.service()
        require(reloaded.specimen(TENANT, SPECIMEN) == original["specimen"],
                "clean restart requires the complete retained specimen")
        require(proof.run(reloaded) == original and proof.snapshot() == before,
                "clean restart replay requires the exact result and zero additional effects")
        pending = cluster.connect("laboratory_app")
        try:
            proof.transfer(pending)
            require(proof.snapshot() == before,
                    "independent observer requires committed state while the transfer is pending")
            cluster.stop("immediate")
        finally:
            pending.close()
        require(cluster.control_state() == "in production",
                "immediate stop requires the control state that triggers crash recovery")
        lifetimes.append(cluster.start())
        require(len(set(lifetimes)) == 3, "restart proof requires three distinct server lifetimes")
        with cluster.connect("proof_owner") as connection:
            require(connection.execute("select pg_postmaster_start_time()::text").fetchone()[0] != start_time,
                    "restart proof requires a new server start identity")
        recovered = proof.service()
        require(recovered.specimen(TENANT, SPECIMEN) == original["specimen"] and proof.snapshot() == before,
                "crash recovery requires committed state and rollback of every pending effect")
        require(proof.run(recovered) == original and proof.snapshot() == before,
                "crash recovery replay requires the exact result and zero additional effects")
        with cluster.connect("laboratory_app") as connection:
            proof.transfer(connection)
        after_retry = proof.snapshot()
        require(len(after_retry["custody_event"]) == len(before["custody_event"]) + 1,
                "corrected retry requires exactly one custody event")
        require({name: rows for name, rows in after_retry.items()
                 if name not in {"custody_event", "custody_position", "transactional_outbox"}}
                == {name: rows for name, rows in before.items()
                    if name not in {"custody_event", "custody_position", "transactional_outbox"}},
                "custody retry preserves every other committed evidence table")
        require(len(after_retry["transactional_outbox"]) == len(before["transactional_outbox"]) + 1
                and all(row in after_retry["transactional_outbox"]
                        for row in before["transactional_outbox"]),
                "custody retry adds one aligned outbox record and preserves earlier records")
        require(after_retry["custody_position"][0]["custody_version"] == 2,
                "corrected retry requires retained custody version two")
        with cluster.connect("laboratory_app") as connection:
            proof.transfer(connection)
        require(proof.snapshot() == after_retry, "custody replay requires zero additional effects")
        result = {"status": "passed", "observed_at_utc": started, "source": source,
                  "python_version": platform.python_version(), "psycopg_version": psycopg.__version__,
                  "postgresql_version": cluster.version, "durability_settings": settings,
                  "migration_method": "psql_single_transaction_per_source_file", "migration_sources": migrations,
                  "server_lifetimes": len(lifetimes),
                  "retained_table_rows": {name: len(rows) for name, rows in before.items()},
                  "retained_snapshot_sha256": sha256(encoded(before)).hexdigest(),
                  "scenarios": ["fast_database_restart", "immediate_crash_recovery",
                                "pending_transaction_rollback", "reconstructed_adapter",
                                "golden_replay_zero_effects", "custody_retry_and_replay"]}
    require(cluster.root is None, "successful proof requires owned cluster cleanup")
    # A failed encounter releases its process and files; a fresh encounter can start independently.
    failed_root = None
    try:
        with OwnedPostgres(binaries, expected_major, timeout) as failed:
            failed_root = failed.root
            raise RestartProofError("synthetic owned-cluster encounter failure")
    except RestartProofError as error:
        require(str(error) == "synthetic owned-cluster encounter failure" and failed.root is None,
                "failure cleanup requires preserving the primary error and releasing the cluster")
    require(failed_root is not None and not failed_root.exists(), "failed encounter requires removed owned files")
    with OwnedPostgres(binaries, expected_major, timeout):
        pass
    result["scenarios"].append("failure_cleanup_and_fresh_reentry")
    result["owned_clusters_cleaned"] = 3
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--expected-major", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    try:
        result = exercise(args.postgres_bin, args.expected_major, args.timeout_seconds)
    except Exception as error:
        # Keep database diagnostics in the private owner; return a value-free failure summary.
        detail = str(error) if isinstance(error, RestartProofError) else type(error).__name__
        print(f"owned database restart proof failed: {detail}", file=sys.stderr)
        for note in getattr(error, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
