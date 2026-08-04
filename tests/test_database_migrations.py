"""Flyway and final-schema posture checks."""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_NAME = re.compile(
    r"^V(?P<version>(?:[0-9]{3}|[0-9]{14}))__[a-z0-9]+(?:_[a-z0-9]+)*\.sql$"
)
TRANSACTION_CONTROL = re.compile(
    r"^\s*(?:begin|commit|rollback)\s*;",
    flags=re.IGNORECASE | re.MULTILINE,
)


def load_properties(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
        for key, value in (line.split("=", 1),)
    }


class DatabaseMigrationTests(unittest.TestCase):
    def test_flyway_owns_history_ordering_and_validation(self) -> None:
        config = load_properties(ROOT / "flyway.conf")
        self.assertEqual(config["flyway.locations"], "filesystem:sql")
        self.assertEqual(config["flyway.validateMigrationNaming"], "true")
        self.assertEqual(config["flyway.validateOnMigrate"], "true")
        self.assertEqual(config["flyway.outOfOrder"], "true")
        self.assertEqual(config["flyway.cleanDisabled"], "true")
        self.assertEqual(config["flyway.baselineOnMigrate"], "false")
        self.assertFalse((ROOT / "scripts/apply_database_migrations.py").exists())

    def test_timestamped_successors_coexist_with_immutable_legacy_history(self) -> None:
        migrations = sorted((ROOT / "sql").glob("V*__*.sql"))
        versions: list[str] = []
        for migration in migrations:
            match = MIGRATION_NAME.fullmatch(migration.name)
            self.assertIsNotNone(match, migration.name)
            assert match is not None
            version = match.group("version")
            versions.append(version)
            if len(version) == 14:
                self.assertEqual(
                    datetime.strptime(version + "+0000", "%Y%m%d%H%M%S%z").strftime("%Y%m%d%H%M%S"),
                    version,
                )
            self.assertIsNone(TRANSACTION_CONTROL.search(migration.read_text("utf-8")))
        self.assertEqual(len(versions), len(set(versions)))
        self.assertEqual(
            [path.name for path in migrations[:4]],
            [
                "V001__laboratory_core.sql",
                "V002__principal_data_boundaries.sql",
                "V003__trusted_routines_and_outbox_cas.sql",
                "V004__outbox_attempt_evidence_and_recovery.sql",
            ],
        )

    def test_debezium_routes_the_append_only_outbox(self) -> None:
        properties = load_properties(ROOT / "infra/debezium/outbox-event-router.properties")
        self.assertEqual(
            properties["transforms.outbox.type"],
            "io.debezium.transforms.outbox.EventRouter",
        )
        self.assertEqual(properties["transforms.outbox.table.field.event.id"], "message_id")
        self.assertEqual(properties["transforms.outbox.table.field.event.key"], "aggregate_id")
        self.assertEqual(properties["transforms.outbox.table.op.invalid.behavior"], "error")

    def test_release_metadata_has_no_artifact_digest_lattice(self) -> None:
        release = json.loads((ROOT / "database/flyway-release.json").read_text(encoding="utf-8"))
        self.assertEqual(release["migration_product"], "Flyway Community")
        self.assertEqual(
            release["cross_service_events"]["capture"],
            "Debezium Outbox Event Router",
        )
        self.assertNotIn("artifact_inventory", release)
        self.assertNotIn("migration_head", release)


if __name__ == "__main__":
    unittest.main()
