"""Flyway release, ordering, safety, and immutable-history proofs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "flyway.conf"
RELEASE_PATH = ROOT / "database" / "flyway-release.json"
INVENTORY_PATH = ROOT / "database" / "flyway-artifact-inventory.json"
MIGRATION_NAME = re.compile(r"^V(?P<version>[0-9]{3})__[a-z0-9_]+\.sql$")
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
        self.assertEqual(release["migration_head"], "005")
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
        inventory_reference = release["artifact_inventory"]
        self.assertEqual(
            inventory_reference["sha256"],
            hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest(),
        )
        inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(inventory["canonicalization"], "ordered-path-nul-sha256-lf-v1")
        self.assertEqual(
            [artifact["path"] for artifact in inventory["artifacts"]],
            [
                "flyway.conf",
                "sql/afterConnect.sql",
                "database/provision_cluster_roles.sql",
                "sql/V001__laboratory_core.sql",
                "sql/V002__principal_data_boundaries.sql",
                "sql/V003__trusted_routines_and_outbox_cas.sql",
                "sql/V004__outbox_attempt_evidence_and_recovery.sql",
                "sql/V005__golden_specimen_workbench.sql",
            ],
        )
        for artifact in inventory["artifacts"]:
            with self.subTest(artifact=artifact["path"]):
                self.assertEqual(
                    hashlib.sha256((ROOT / artifact["path"]).read_bytes()).hexdigest(),
                    artifact["sha256"],
                )
        aggregate_payload = "".join(
            f"{artifact['path']}\0{artifact['sha256']}\n"
            for artifact in inventory["artifacts"]
        ).encode("utf-8")
        aggregate = "sha256:" + hashlib.sha256(aggregate_payload).hexdigest()
        self.assertEqual(inventory["aggregate_sha256"], aggregate)
        self.assertEqual(inventory_reference["aggregate_sha256"], aggregate)

    def test_flyway_safety_controls_are_explicit(self) -> None:
        config = load_properties(CONFIG_PATH)
        self.assertEqual(config["flyway.locations"], "filesystem:sql")
        self.assertEqual(config["flyway.validateMigrationNaming"], "true")
        self.assertEqual(config["flyway.validateOnMigrate"], "true")
        self.assertEqual(config["flyway.outOfOrder"], "false")
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

    def test_versioned_sequence_is_complete_and_transaction_compatible(self) -> None:
        migrations = sorted((ROOT / "sql").glob("V*__*.sql"))
        self.assertEqual(
            [MIGRATION_NAME.fullmatch(path.name).group("version") for path in migrations],
            ["001", "002", "003", "004", "005"],
        )
        for migration in migrations:
            sql = migration.read_text(encoding="utf-8")
            with self.subTest(migration=migration.name):
                self.assertIsNone(TRANSACTION_CONTROL.search(sql))
                self.assertNotRegex(sql.lower(), r"\bcreate\s+index\s+concurrently\b")

    def test_migration_003_retains_its_published_bytes(self) -> None:
        migration = ROOT / "sql" / "V003__trusted_routines_and_outbox_cas.sql"
        self.assertEqual(
            hashlib.sha256(migration.read_bytes()).hexdigest(),
            "13925ea70a930ef69240de8e0ffe56e5cb4479fb64e48cf41e6051dc8eb66a70",
        )

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
