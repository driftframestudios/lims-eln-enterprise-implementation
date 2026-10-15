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
        from scripts.check_database_restart import (
            LaboratoryProof, OwnedPostgres, TENANT, RUN,
        )
        from lims_eln_implementation.security import PostgresTenantBinding
        from lims_eln_implementation.workbench.postgres import PostgresWorkbenchService

        binaries = Path(os.environ["LIMS_RESTART_POSTGRES_BIN"])
        major = int(os.environ.get("LIMS_RESTART_EXPECTED_MAJOR", "17"))
        with OwnedPostgres(binaries, major) as cluster:
            migrations = cluster.install()
            proof = LaboratoryProof(cluster)

            def read_head():
                with cluster.connect("laboratory_app") as connection, connection.cursor() as cursor:
                    PostgresTenantBinding(proof.context(TENANT)).bind(cursor, expected_tenant_id=TENANT)
                    cursor.execute("select laboratory_security.workbench_migration_head()")
                    return cursor.fetchone()[0]

            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                read_head()
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                proof.service()
            self.assertEqual(cluster.install_authored_history_fixture(migrations)["origin"],
                             "authored_native_proof_fixture")
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
            later_arguments = {
                "run_id": "SYN-PROVENANCE-LATER", "tenant_id": TENANT, "specimen_id": "SYN-PROVENANCE-LATER",
                "actor_id": "SYN-ACTOR-01", "scientist_id": "SYN-SCIENTIST-01", "quality_actor_id": "SYN-QUALITY-01",
                "occurred_at": OCCURRED, "raw_instrument_json": b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}',
                "vendor_payload": {"status": "under_review"},
            }
            later = service.run_golden_specimen(**later_arguments)
            self.assertEqual(later["observation"]["result"]["producer_detail"]["configuration"]["migration_head"], "009")
            self.assertNotEqual(first["observation"]["source"]["configuration_digest"], later["observation"]["source"]["configuration_digest"])

            for script in ("V009xxsynthetic_fixture.sql", "V009__synthetic_fixtureXsql",
                           "V009__.sql", "V008__synthetic_fixture.sql", "V009__synthetic_fixture.sql\n"):
                with self.subTest(script=script):
                    with cluster.connect("proof_owner") as connection:
                        connection.execute("update public.flyway_schema_history set script=%s where installed_rank=9", (script,))
                    with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                        read_head()
            with cluster.connect("proof_owner") as connection:
                connection.execute("update public.flyway_schema_history set script='V009__synthetic_fixture.sql' where installed_rank=9")
            with cluster.connect("proof_owner") as connection:
                connection.execute("update public.flyway_schema_history set success=false where version='009'")
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                read_head()
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                service.check_ready()
            held_identity = "SYN-PROVENANCE-HELD"
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                service.run_golden_specimen(**{
                    **later_arguments, "run_id": held_identity, "specimen_id": held_identity,
                })
            with cluster.connect("proof_owner") as connection:
                self.assertEqual(connection.execute(
                    "select count(*) from public.bounded_call_invocation where tenant_id=%s and call_id=%s",
                    (TENANT, held_identity),
                ).fetchone()[0], 0)
                self.assertEqual(connection.execute(
                    "select count(*) from public.bounded_call_receipt where tenant_id=%s and call_id=%s",
                    (TENANT, held_identity),
                ).fetchone()[0], 0)
                self.assertEqual(connection.execute(
                    "select count(*) from public.specimen where tenant_id=%s and specimen_id=%s",
                    (TENANT, held_identity),
                ).fetchone()[0], 0)
            self.assertEqual(service.observation(TENANT, RUN), first["observation"])


if __name__ == "__main__":
    unittest.main()
