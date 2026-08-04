"""Migration ordering, immutability, and transaction-runner proofs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "apply_database_migrations.py"
SPEC = importlib.util.spec_from_file_location("apply_database_migrations", TOOL_PATH)
assert SPEC and SPEC.loader
apply_database_migrations = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = apply_database_migrations
SPEC.loader.exec_module(apply_database_migrations)


class DatabaseMigrationTests(unittest.TestCase):
    def test_released_manifest_covers_every_sql_migration_with_valid_hashes(self) -> None:
        migrations = apply_database_migrations.load_manifest()
        self.assertEqual(
            tuple(item.migration_id for item in migrations),
            ("001", "002", "003"),
        )
        self.assertEqual(
            {item.path for item in migrations},
            set((ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql")),
        )

    def test_runner_owns_lock_transaction_drift_guard_and_history_write(self) -> None:
        migration = apply_database_migrations.load_manifest()[1]
        rendered = apply_database_migrations.render_migration(migration)
        self.assertIn("begin;", rendered)
        self.assertIn("pg_advisory_xact_lock", rendered)
        self.assertIn("differs from applied history", rendered)
        self.assertIn("\\if :migration_already_applied", rendered)
        self.assertIn("insert into laboratory_migration.applied_migration", rendered)
        self.assertTrue(rendered.rstrip().endswith("commit;"))

        bootstrap = apply_database_migrations.bootstrap_sql()
        self.assertIn("preserve_applied_history", bootstrap)
        self.assertIn("applied_migration_append_only", bootstrap)
        self.assertIn("isfinite(applied_at_utc)", bootstrap)

    def test_checksum_drift_fails_before_database_contact(self) -> None:
        source_manifest = json.loads(
            (ROOT / "database" / "migration-manifest.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(prefix="migration-contract-") as temporary:
            temporary_root = Path(temporary)
            (temporary_root / "database").mkdir()
            (temporary_root / "sql").mkdir()
            (temporary_root / "scripts").mkdir()
            (temporary_root / source_manifest["runner"]["path"]).write_bytes(
                TOOL_PATH.read_bytes()
            )
            for entry in source_manifest["migrations"]:
                source = ROOT / entry["path"]
                target = temporary_root / entry["path"]
                target.write_bytes(source.read_bytes())
            (temporary_root / source_manifest["migrations"][0]["path"]).write_text(
                "select 'drift';\n",
                encoding="utf-8",
            )
            manifest_path = temporary_root / "database" / "migration-manifest.json"
            manifest_path.write_text(
                json.dumps(source_manifest),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                apply_database_migrations.MigrationContractError,
                "checksum differs",
            ):
                apply_database_migrations.load_manifest(manifest_path)

            first_migration = source_manifest["migrations"][0]["path"]
            (temporary_root / first_migration).write_bytes(
                (ROOT / first_migration).read_bytes()
            )
            (temporary_root / source_manifest["runner"]["path"]).write_text(
                "raise SystemExit('synthetic runner drift')\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                apply_database_migrations.MigrationContractError,
                "runner differs",
            ):
                apply_database_migrations.load_manifest(manifest_path)

    def test_rendered_migration_has_one_runner_owned_transaction(self) -> None:
        migration = apply_database_migrations.Migration(
            migration_id="999",
            path=ROOT / "sql" / "999_synthetic.sql",
            relative_path="sql/999_synthetic.sql",
            sha256_hex="a" * 64,
            sql="select 1;",
        )
        rendered = apply_database_migrations.render_migration(migration)
        self.assertEqual(rendered.lower().count("begin;"), 1)
        self.assertEqual(rendered.lower().count("commit;"), 1)


if __name__ == "__main__":
    unittest.main()
