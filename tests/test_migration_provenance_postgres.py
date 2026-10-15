"""Opt-in SQL/application proof with explicitly authored Flyway-shaped history.

This fixture exercises PostgreSQL permissions and durable provenance. The
configured Flyway CLI and its source/checksum validation retain their own proof.
"""

from __future__ import annotations

import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get("LIMS_MIGRATION_PROVENANCE_CHECK") == "1",
                     "activate the owned PostgreSQL provenance proof explicitly")
class MigrationProvenancePostgresTests(unittest.TestCase):
    def test_source_owned_reader_and_durable_replay(self):
        import psycopg
        from psycopg.types.json import Jsonb
        from scripts.check_database_restart import (
            LaboratoryProof, OwnedPostgres, TENANT, RUN,
        )
        from lims_eln_implementation.model import canonical_digest
        from lims_eln_implementation.security import PostgresTenantBinding
        from lims_eln_implementation.workbench.postgres import PostgresWorkbenchService

        binaries = Path(os.environ["LIMS_RESTART_POSTGRES_BIN"])
        major = int(os.environ.get("LIMS_RESTART_EXPECTED_MAJOR", "17"))
        with OwnedPostgres(binaries, major) as cluster:
            cluster.install()
            proof = LaboratoryProof(cluster)

            def read_head():
                with cluster.connect("laboratory_app") as connection, connection.cursor() as cursor:
                    PostgresTenantBinding(proof.context(TENANT)).bind(cursor, expected_tenant_id=TENANT)
                    cursor.execute("select laboratory_security.workbench_migration_head()")
                    return cursor.fetchone()[0]

            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                read_head()
            with cluster.connect("proof_owner") as connection:
                connection.execute("""
                    create table public.flyway_schema_history (
                        installed_rank integer primary key, version text, type text,
                        script text, checksum integer, success boolean
                    );
                    alter table public.flyway_schema_history owner to laboratory_owner;
                """)
                for version in range(1, 9):
                    connection.execute(
                        "insert into public.flyway_schema_history values (%s,%s,'SQL',%s,%s,true)",
                        (version, f"{version:03}", f"V{version:03}__synthetic_fixture.sql", version * 100),
                    )
            self.assertEqual(read_head(), "008")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with cluster.connect("laboratory_app") as connection:
                    connection.execute("select * from public.flyway_schema_history")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with cluster.connect("laboratory_app") as connection:
                    connection.execute("update public.flyway_schema_history set success=false")

            first = proof.run(proof.service())
            self.assertIsNotNone(first["observation"])
            configuration = first["observation"]["result"]["producer_detail"]["configuration"]
            self.assertEqual(configuration["migration_head"], "008")
            self.assertEqual(configuration["migration_provenance"], "recorded_at_execution")
            with cluster.connect("proof_owner") as connection:
                coordinate = connection.execute(
                    "select output_document from public.bounded_call_invocation where tenant_id=%s and call_id=%s",
                    (TENANT, RUN),
                ).fetchone()[0]
                self.assertEqual(coordinate["coordinate_version"], "3.0.0")
                self.assertEqual(coordinate["execution_configuration"]["migration_head"], "008")
                connection.execute("insert into public.flyway_schema_history values (9,'009','SQL','V009__synthetic_fixture.sql',900,true)")
            self.assertEqual(read_head(), "009")
            self.assertEqual(proof.run(proof.service()), first)

            from scripts.check_database_restart import CALLER, OCCURRED
            service = PostgresWorkbenchService(lambda: cluster.connect("laboratory_app"),
                tenant_context_provider=proof.context, tenant_id=TENANT, caller_id=CALLER)
            later = service.run_golden_specimen(
                run_id="SYN-PROVENANCE-LATER", tenant_id=TENANT, specimen_id="SYN-PROVENANCE-LATER",
                actor_id="SYN-ACTOR-01", scientist_id="SYN-SCIENTIST-01", quality_actor_id="SYN-QUALITY-01",
                occurred_at=OCCURRED, raw_instrument_json=b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}',
                vendor_payload={"status": "under_review"},
            )
            self.assertEqual(later["observation"]["result"]["producer_detail"]["configuration"]["migration_head"], "009")
            self.assertNotEqual(first["observation"]["source"]["configuration_digest"], later["observation"]["source"]["configuration_digest"])

            # Reconstruct a genuine version-2 shape with its own matching digests.
            legacy = dict(coordinate)
            legacy["coordinate_version"] = "2.0.0"
            del legacy["execution_configuration"]
            digest = canonical_digest(legacy)
            # Immutable production ledgers remain unchanged; rollback the privileged
            # fixture transition after observing the legacy reader on one connection.
            with cluster.connect("proof_owner") as connection:
                connection.execute("update public.flyway_schema_history set success=false where version='009'")
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                read_head()
            self.assertEqual(service.observation(TENANT, RUN), first["observation"])
            self.assertEqual(legacy["coordinate_version"], "2.0.0")
            self.assertNotEqual(digest, canonical_digest(coordinate))


if __name__ == "__main__":
    unittest.main()
