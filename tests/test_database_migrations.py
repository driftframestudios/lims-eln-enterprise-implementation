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
    def test_direct_container_entrypoints_are_executable(self) -> None:
        for relative in (
            "infra/provision-migrator-identity.sh",
            "infra/run-flyway-with-secret.sh",
            "infra/postgres-init/010_application_password.sh",
        ):
            with self.subTest(entrypoint=relative):
                self.assertTrue((ROOT / relative).stat().st_mode & 0o100)

    def test_flyway_release_is_version_and_digest_pinned(self) -> None:
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(release["migration_product"], "Flyway Community")
        self.assertEqual(release["flyway_version"], "13.8.1")
        self.assertRegex(
            release["container_image"],
            rf"^flyway/flyway:{re.escape(release['flyway_version'])}"
            r"-alpine@sha256:[a-f0-9]{64}$",
        )
        dockerfile = (ROOT / "infra" / "migrator.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            dockerfile.splitlines()[0],
            f"FROM {release['container_image']}",
        )
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["database"]["migration_product_version"],
            release["flyway_version"],
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

    def test_hosted_receipt_binds_the_observed_flyway_coordinate(self) -> None:
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        repository_role = json.loads(
            (ROOT / "release" / "repository-role.json").read_text(encoding="utf-8")
        )
        receipt = json.loads(
            (ROOT / "receipts" / "hosted-postgresql-proof.json").read_text(
                encoding="utf-8"
            )
        )
        bindings = receipt["version_bindings"]
        coordinate = repository_role["database_hosted_evidence"]
        self.assertEqual(
            set(coordinate),
            {"receipt_path", "coordinate_state", "promotion_signal"},
        )
        self.assertEqual(
            coordinate["receipt_path"], "receipts/hosted-postgresql-proof.json"
        )
        self.assertEqual(coordinate["promotion_signal"], "implementation-validation")
        self.assertEqual(
            coordinate["coordinate_state"],
            "current_database_artifacts_observed",
        )
        self.assertEqual(
            receipt["release_claim_id"],
            "RELEASE-CLAIM-IMPLEMENTATION-0.3.2",
        )
        self.assertEqual(bindings["repository"], "0.3.2")
        self.assertEqual(
            bindings["repository_commit"],
            "2d12b111edb86f1f16f02338933a827b767a687f",
        )
        self.assertEqual(
            bindings["workflow_run"],
            "https://github.com/driftframestudios/"
            "lims-eln-enterprise-implementation/actions/runs/37071257377",
        )
        self.assertEqual(bindings["flyway"], release["flyway_version"])
        self.assertEqual(
            bindings["flyway_image"],
            release["container_image"],
        )
        self.assertEqual(receipt["observed_at"], "2026-10-02T22:14:32Z")
        self.assertEqual(
            set(receipt["artifact_digests"]),
            {
                "sha256:2e993316b59334071e5234cbb3d2c463a96f67e84550202a2df3f49d3c27a283",
                "sha256:c5ac44d9797df3f328cc4a8bd64f176317398abff564e2cb8f62fb33c123dc2f",
                "sha256:8bbada0ceaa11f264d2d6ad4c893abd8b4313482da387401fd9b0f1d0106666a",
            },
        )
        self.assertNotIn(
            "This receipt establishes the preceding Flyway 13.4.0 hosted "
            "coordinate. The Flyway 13.8.1 successor becomes the current hosted "
            "coordinate when its named implementation-validation run, commit, "
            "and artifact bindings are recorded.",
            receipt["limitations"],
        )
        self.assertIn(
            "The independently signed v0.3.2 release subject retains its existing "
            "promotion observation; this receipt binds only the named post-release "
            "development commit.",
            receipt["limitations"],
        )

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
