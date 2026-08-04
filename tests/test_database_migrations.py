"""Flyway release, ordering, safety, and immutable-history proofs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "flyway.conf"
RELEASE_PATH = ROOT / "database" / "flyway-release.json"
MIGRATION_NAME = re.compile(
    r"^V(?P<version>(?:[0-9]{3}|[0-9]{14}))__[a-z0-9]+(?:_[a-z0-9]+)*\.sql$"
)
REPEATABLE_NAME = re.compile(r"^R__[a-z0-9]+(?:_[a-z0-9]+)*\.sql$")
LEGACY_MIGRATIONS = (
    "V001__laboratory_core.sql",
    "V002__principal_data_boundaries.sql",
    "V003__trusted_routines_and_outbox_cas.sql",
    "V004__outbox_attempt_evidence_and_recovery.sql",
)
TRANSACTION_CONTROL = re.compile(
    r"^\s*(?:begin|commit|rollback)\s*;",
    flags=re.IGNORECASE | re.MULTILINE,
)


def load_properties(path: Path) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            properties[key] = value
    return properties


class DatabaseMigrationTests(unittest.TestCase):
    def test_flyway_release_is_version_and_digest_pinned(self) -> None:
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(release["migration_product"], "Flyway Community")
        self.assertEqual(release["flyway_version"], "13.0.0")
        self.assertRegex(
            release["container_image"],
            r"^flyway/flyway:13\.0\.0-alpine@sha256:[a-f0-9]{64}$",
        )
        self.assertEqual(release["credentials"], "runtime_environment_only")
        self.assertEqual(
            release["deployment_cadence"],
            "independent_from_application_releases",
        )
        self.assertEqual(
            release["versioning"],
            {
                "legacy_versions": "V001-through-V004",
                "successor_format": "VyyyyMMddHHmmss__description.sql",
                "clock": "UTC",
            },
        )
        self.assertNotIn("migration_head", release)
        self.assertNotIn("artifact_inventory", release)
        self.assertEqual(release["authenticated_login"], "laboratory_migrator")
        self.assertEqual(release["migration_role"], "laboratory_owner")
        self.assertEqual(
            release["role_assumption"],
            "database_scoped_startup_role_after_connect_verified_noinherit_membership",
        )
        callback = release["connection_callback"]
        callback_path = ROOT / callback["path"]
        self.assertEqual(
            hashlib.sha256(callback_path.read_bytes()).hexdigest(),
            callback["sha256"],
        )
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        database = manifest["database"]
        self.assertEqual(
            database["migration_deployment_cadence"],
            "independent_from_application_releases",
        )
        self.assertNotIn("migration_head", database)

    def test_flyway_safety_controls_are_explicit(self) -> None:
        config = load_properties(CONFIG_PATH)
        self.assertEqual(config["flyway.locations"], "filesystem:sql")
        self.assertEqual(config["flyway.validateMigrationNaming"], "true")
        self.assertEqual(config["flyway.validateOnMigrate"], "true")
        self.assertEqual(config["flyway.outOfOrder"], "true")
        self.assertEqual(config["flyway.cleanDisabled"], "true")
        self.assertEqual(config["flyway.baselineOnMigrate"], "false")
        self.assertEqual(config["flyway.group"], "false")
        self.assertEqual(config["flyway.mixed"], "false")
        self.assertNotIn("flyway.initSql", config)

        callback = (ROOT / "sql" / "afterConnect.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("session_user <> 'laboratory_migrator'", callback)
        self.assertIn("current_user <> 'laboratory_owner'", callback)
        self.assertIn(
            "current_setting('role', true) <> 'laboratory_owner'",
            callback,
        )
        self.assertIn("pg_catalog.pg_db_role_setting", callback)
        self.assertIn("configuration.value = 'role=laboratory_owner'", callback)
        self.assertIn(
            "granted_role.rolname = 'laboratory_outbox_authority'",
            callback,
        )
        self.assertIn("member_role.rolname = 'laboratory_owner'", callback)
        self.assertIn("not membership.admin_option", callback)
        self.assertIn("not membership.inherit_option", callback)
        self.assertIn("membership.set_option", callback)

        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        provisioning = release["cluster_role_provisioning"]
        provisioning_path = ROOT / provisioning["path"]
        self.assertEqual(
            provisioning["sha256"],
            hashlib.sha256(provisioning_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            provisioning["execution"],
            "separate_privileged_deployment_step",
        )

    def test_migration_names_support_immutable_legacy_and_timestamp_successors(self) -> None:
        migrations = sorted((ROOT / "sql").glob("V*__*.sql"))
        self.assertEqual(
            tuple(path.name for path in migrations[: len(LEGACY_MIGRATIONS)]),
            LEGACY_MIGRATIONS,
        )
        versions: list[str] = []
        for migration in migrations:
            match = MIGRATION_NAME.fullmatch(migration.name)
            self.assertIsNotNone(match, migration.name)
            assert match is not None
            version = match.group("version")
            versions.append(version)
            if len(version) == 3:
                self.assertIn(migration.name, LEGACY_MIGRATIONS)
            else:
                parsed = datetime.strptime(version, "%Y%m%d%H%M%S")
                self.assertEqual(parsed.strftime("%Y%m%d%H%M%S"), version)
            sql = migration.read_text(encoding="utf-8")
            with self.subTest(migration=migration.name):
                self.assertIsNone(TRANSACTION_CONTROL.search(sql))
                self.assertNotRegex(sql.lower(), r"\bcreate\s+index\s+concurrently\b")
        self.assertEqual(len(versions), len(set(versions)))

        repeatables = sorted((ROOT / "sql").glob("R__*.sql"))
        for migration in repeatables:
            self.assertRegex(migration.name, REPEATABLE_NAME)

        discovered = {path.name for path in migrations + repeatables}
        candidates = {
            path.name
            for path in (ROOT / "sql").glob("*.sql")
            if path.name != "afterConnect.sql"
        }
        self.assertEqual(discovered, candidates)

    def test_outbox_owner_transfer_schema_capability_is_transaction_bounded(self) -> None:
        migration = (
            ROOT / "sql" / "V004__outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        grant_index = migration.index(
            "grant create on schema public to laboratory_outbox_authority;"
        )
        table_transfer_index = migration.index(
            "alter table public.outbox_delivery_attempt "
            "owner to laboratory_outbox_authority;"
        )
        function_transfer_index = migration.index(
            "alter function public.release_outbox_recovery(text, bigint, integer, text)"
        )
        table_acl_index = migration.index(
            "revoke all privileges on public.transactional_outbox "
            "from laboratory_app;"
        )
        trigger_index = migration.index(
            "create trigger transactional_outbox_delivery_transition"
        )
        function_acl_index = migration.index(
            "grant execute on function public.release_outbox_recovery("
        )
        authority_role_index = migration.index(
            "set local role laboratory_outbox_authority;"
        )
        authority_revoke_index = migration.index(
            "revoke all privileges on public.transactional_outbox\n"
            "from laboratory_outbox_authority;"
        )
        authority_dml_index = migration.index(
            "grant select, insert, update on public.transactional_outbox\n"
            "to laboratory_outbox_authority;"
        )
        owner_insert_index = migration.index(
            ") on public.transactional_outbox to laboratory_owner;"
        )
        owner_role_index = migration.index("set local role laboratory_owner;")
        revoke_index = migration.index(
            "revoke create on schema public from laboratory_outbox_authority;"
        )
        self.assertLess(table_acl_index, trigger_index)
        self.assertLess(trigger_index, grant_index)
        self.assertLess(function_acl_index, grant_index)
        self.assertLess(grant_index, table_transfer_index)
        self.assertLess(table_transfer_index, function_transfer_index)
        self.assertLess(function_transfer_index, authority_role_index)
        self.assertLess(authority_role_index, authority_revoke_index)
        self.assertLess(authority_revoke_index, authority_dml_index)
        self.assertLess(authority_dml_index, owner_insert_index)
        self.assertLess(owner_insert_index, owner_role_index)
        self.assertLess(owner_role_index, revoke_index)
        self.assertNotIn(
            "grant all privileges on public.transactional_outbox",
            migration,
        )

    def test_repository_delegates_migration_history_and_locking_to_flyway(self) -> None:
        self.assertFalse((ROOT / "scripts" / "apply_database_migrations.py").exists())
        self.assertFalse(
            (ROOT / "database" / "flyway-artifact-inventory.json").exists()
        )
        self.assertFalse((ROOT / "database" / "migration-manifest.json").exists())
        self.assertFalse(
            (ROOT / "database" / "migration-manifest-through-003.json").exists()
        )
        published = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"))
        )
        self.assertNotIn("laboratory_migration.applied_migration", published)


if __name__ == "__main__":
    unittest.main()
