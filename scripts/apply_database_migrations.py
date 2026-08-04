#!/usr/bin/env python3
"""Verify and apply the immutable PostgreSQL migration sequence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "database" / "migration-manifest.json"
MIGRATION_ID = re.compile(r"^[0-9]{3}$")
SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")
TRANSACTION_CONTROL = re.compile(
    r"^\s*(?:begin|commit|rollback)\s*;",
    re.IGNORECASE | re.MULTILINE,
)


class MigrationContractError(RuntimeError):
    """The released migration sequence differs from its immutable contract."""


@dataclass(frozen=True, slots=True)
class Migration:
    migration_id: str
    path: Path
    relative_path: str
    sha256_hex: str
    sql: str


def _require_exact_keys(
    value: dict[str, object], expected: set[str], *, location: str
) -> None:
    observed = set(value)
    if observed != expected:
        raise MigrationContractError(
            f"{location} requires fields {sorted(expected)}; observed {sorted(observed)}"
        )


def load_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[Migration, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationContractError("migration manifest requires valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise MigrationContractError("migration manifest requires one JSON object")
    _require_exact_keys(
        document,
        {
            "schema_version",
            "database_engine",
            "transaction_policy",
            "runner",
            "migrations",
        },
        location="migration manifest",
    )
    if document["schema_version"] != "1.0.0":
        raise MigrationContractError("migration manifest requires schema version 1.0.0")
    if document["database_engine"] != "postgresql":
        raise MigrationContractError("migration manifest requires PostgreSQL")
    if document["transaction_policy"] != "one_transaction_per_migration":
        raise MigrationContractError(
            "migration manifest requires one_transaction_per_migration"
        )
    manifest_root = path.resolve().parents[1]
    runner = document["runner"]
    if not isinstance(runner, dict):
        raise MigrationContractError("migration manifest requires one runner binding")
    _require_exact_keys(runner, {"path", "sha256"}, location="migration runner")
    if runner["path"] != "scripts/apply_database_migrations.py":
        raise MigrationContractError("migration runner requires its released path")
    runner_hash = runner["sha256"]
    if not isinstance(runner_hash, str) or SHA256_HEX.fullmatch(runner_hash) is None:
        raise MigrationContractError("migration runner requires a lowercase SHA-256 checksum")
    runner_path = manifest_root / str(runner["path"])
    if sha256(runner_path.read_bytes()).hexdigest() != runner_hash:
        raise MigrationContractError("migration runner differs from the released manifest")
    entries = document["migrations"]
    if not isinstance(entries, list) or not entries:
        raise MigrationContractError("migration manifest requires an ordered sequence")

    migrations: list[Migration] = []
    previous_id = ""
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise MigrationContractError(f"migration {index} requires one JSON object")
        _require_exact_keys(
            raw_entry,
            {"id", "path", "sha256", "transactional"},
            location=f"migration {index}",
        )
        migration_id = raw_entry["id"]
        relative_path = raw_entry["path"]
        expected_hash = raw_entry["sha256"]
        if not isinstance(migration_id, str) or MIGRATION_ID.fullmatch(migration_id) is None:
            raise MigrationContractError(f"migration {index} requires a three-digit id")
        if migration_id <= previous_id:
            raise MigrationContractError("migration ids require strict ascending order")
        previous_id = migration_id
        if not isinstance(relative_path, str) or not relative_path.startswith(
            f"sql/{migration_id}_"
        ) or not relative_path.endswith(".sql"):
            raise MigrationContractError(
                f"migration {migration_id} path requires its ordered sql prefix"
            )
        candidate = (manifest_root / relative_path).resolve()
        sql_root = (manifest_root / "sql").resolve()
        if candidate.parent != sql_root:
            raise MigrationContractError(
                f"migration {migration_id} path requires the repository sql directory"
            )
        if not isinstance(expected_hash, str) or SHA256_HEX.fullmatch(expected_hash) is None:
            raise MigrationContractError(
                f"migration {migration_id} requires a lowercase SHA-256 checksum"
            )
        if raw_entry["transactional"] is not True:
            raise MigrationContractError(
                f"migration {migration_id} requires the released transactional mode"
            )
        try:
            raw_sql = candidate.read_bytes()
            sql = raw_sql.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise MigrationContractError(
                f"migration {migration_id} requires readable UTF-8 SQL"
            ) from error
        observed_hash = sha256(raw_sql).hexdigest()
        if observed_hash != expected_hash:
            raise MigrationContractError(
                f"migration {migration_id} checksum differs from the released manifest"
            )
        if TRANSACTION_CONTROL.search(sql):
            raise MigrationContractError(
                f"migration {migration_id} delegates transaction ownership to the runner"
            )
        if re.search(r"\bcreate\s+index\s+concurrently\b", sql, re.IGNORECASE):
            raise MigrationContractError(
                f"migration {migration_id} requires transaction-compatible index creation"
            )
        migrations.append(
            Migration(
                migration_id=migration_id,
                path=candidate,
                relative_path=relative_path,
                sha256_hex=expected_hash,
                sql=sql,
            )
        )
    return tuple(migrations)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def bootstrap_sql() -> str:
    return """\
\\set ON_ERROR_STOP on
begin;
select pg_advisory_xact_lock(hashtextextended('lims-eln-schema-migrations-v1', 0));
create schema if not exists laboratory_migration;
revoke all on schema laboratory_migration from public;
create table if not exists laboratory_migration.applied_migration (
    migration_id text primary key check (migration_id ~ '^[0-9]{3}$'),
    migration_path text not null unique,
    migration_sha256 text not null check (migration_sha256 ~ '^[a-f0-9]{64}$'),
    applied_at_utc timestamptz not null default clock_timestamp() check (
        isfinite(applied_at_utc)
    ),
    applied_by name not null default current_user
);
revoke all on laboratory_migration.applied_migration from public;
create or replace function laboratory_migration.preserve_applied_history()
returns trigger
language plpgsql
set search_path = pg_catalog
as $history_guard$
begin
    raise exception 'applied migration history is append-only';
end;
$history_guard$;
revoke all on function laboratory_migration.preserve_applied_history() from public;
drop trigger if exists applied_migration_append_only
    on laboratory_migration.applied_migration;
create trigger applied_migration_append_only
before update or delete on laboratory_migration.applied_migration
for each row execute function laboratory_migration.preserve_applied_history();
commit;
"""


def render_migration(migration: Migration) -> str:
    migration_id = _literal(migration.migration_id)
    relative_path = _literal(migration.relative_path)
    checksum = _literal(migration.sha256_hex)
    return f"""\
\\set ON_ERROR_STOP on
begin;
select pg_advisory_xact_lock(hashtextextended('lims-eln-schema-migrations-v1', 0));
do $migration_guard$
begin
    if exists (
        select 1
          from laboratory_migration.applied_migration
         where migration_id = {migration_id}
           and (
               migration_path <> {relative_path}
               or migration_sha256 <> {checksum}
           )
    ) then
        raise exception 'migration {migration.migration_id} differs from applied history';
    end if;
end;
$migration_guard$;
select count(*) as migration_already_applied
  from laboratory_migration.applied_migration
 where migration_id = {migration_id}
   and migration_path = {relative_path}
   and migration_sha256 = {checksum}
\\gset
\\if :migration_already_applied
\\echo 'migration {migration.migration_id} already applied with released checksum'
\\else
{migration.sql.rstrip()}
insert into laboratory_migration.applied_migration (
    migration_id,
    migration_path,
    migration_sha256
) values ({migration_id}, {relative_path}, {checksum});
\\endif
commit;
"""


def _run_psql(psql: str, dsn: str, sql: str) -> None:
    completed = subprocess.run(
        [psql, dsn, "--no-psqlrc", "--set", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise MigrationContractError(
            "PostgreSQL migration execution requires a successful transaction"
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dsn", default=os.environ.get("LIMS_DATABASE_DSN"))
    parser.add_argument("--psql", default=shutil.which("psql") or "psql")
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    migrations = load_manifest(args.manifest)
    if args.verify_only:
        print(f"verified {len(migrations)} immutable PostgreSQL migrations")
        return 0
    if not args.dsn:
        raise MigrationContractError(
            "database migration requires --dsn or LIMS_DATABASE_DSN"
        )
    _run_psql(args.psql, args.dsn, bootstrap_sql())
    for migration in migrations:
        _run_psql(args.psql, args.dsn, render_migration(migration))
    print(f"applied or verified {len(migrations)} PostgreSQL migrations")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MigrationContractError as error:
        print(f"migration contract error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
