"""Configured pending-count semantics and normalized query-plan observation."""

import json
import os
import unittest
from uuid import uuid4

from tests.test_postgres_integration import signed_context

try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None

ADMIN_DSN = os.environ.get("LIMS_TEST_POSTGRES_ADMIN_DSN")
APP_DSN = os.environ.get("LIMS_TEST_POSTGRES_APP_DSN")
OUTBOX_DSN = os.environ.get("LIMS_TEST_POSTGRES_OUTBOX_DSN")
QUERY = (
    "select specimen_id, pending_outbox_count "
    "from public.specimen_workbench_snapshot where tenant_id=%s order by specimen_id"
)


def plan_nodes(node):
    yield node
    for child in node.get("Plans", ()):
        yield from plan_nodes(child)


@unittest.skipUnless(
    ADMIN_DSN and APP_DSN and OUTBOX_DSN and psycopg
    and os.environ.get("LIMS_TEST_TENANT_HMAC_HEX"),
    "configured PostgreSQL identities and synthetic signing key enable this proof",
)
class PendingOutboxPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tenants = tuple("SYN-PLAN-" + uuid4().hex for _ in range(3))
        with psycopg.connect(ADMIN_DSN) as connection:
            for tenant, specimens, messages in (
                (cls.tenants[0], 2, 4), (cls.tenants[1], 1, 7),
                (cls.tenants[2], 1000, 10000),
            ):
                connection.execute(
                    "insert into public.tenant(tenant_id,display_name) values (%s, 'Synthetic query fixture')", (tenant,),
                )
                connection.execute(
                    "insert into public.specimen(tenant_id,specimen_id,lifecycle_state,"
                    "aggregate_version,canonical_document,canonical_sha256,updated_at_utc) "
                    "select %s,'SYN-'||n,'registered',1,'{}',repeat('a',64),now() "
                    "from generate_series(1,%s)n", (tenant, specimens),
                )
                connection.execute(
                    "insert into public.transactional_outbox(tenant_id,message_id,topic,"
                    "aggregate_id,aggregate_version,payload,payload_sha256) "
                    "select %s,'SYN-MESSAGE-'||n,'synthetic.query',"
                    "'SYN-'||(((n-1)%% %s)+1),1,'{}',encode(digest('{}','sha256'),'hex') "
                    "from generate_series(1,%s)n",
                    (tenant, specimens if messages == 10000 else 1, messages),
                )
            connection.execute("analyze public.specimen")
            connection.execute("analyze public.transactional_outbox")
        # Trusted transitions keep delivered, recovery, leased, and ready rows coherent.
        with psycopg.connect(OUTBOX_DSN) as connection:
            cls.bind(connection, cls.tenants[0])
            for state in ("delivered", "recovery_required", "leased"):
                message, token, fence = connection.execute(
                    "select message_id,lease_token,fencing_token "
                    "from public.claim_outbox_delivery('SYN-PLAN-WORKER',300)"
                ).fetchone()
                if state == "delivered":
                    connection.execute(
                        "select public.confirm_outbox_delivery(%s,'SYN-PLAN-WORKER',%s,%s,"
                        "'SYN-TRANSPORT','SYN-ACK')", (message, token, fence),
                    )
                elif state == "recovery_required":
                    connection.execute(
                        "select public.fail_outbox_delivery(%s,'SYN-PLAN-WORKER',%s,%s,"
                        "'SYN.QUERY.FAILURE')", (message, token, fence),
                    )

    @staticmethod
    def bind(connection, tenant):
        connection.execute(
            "select laboratory_security.bind_tenant_context(%s::jsonb)",
            (signed_context(tenant),),
        )

    def test_partial_index_has_the_owned_keys_and_pending_predicate(self):
        with psycopg.connect(ADMIN_DSN) as connection:
            keys, predicate, owner, valid, schema_create = connection.execute(
                "select pg_get_indexdef(i.indexrelid),pg_get_expr(i.indpred,i.indrelid),"
                "pg_get_userbyid(c.relowner),i.indisvalid,"
                "has_schema_privilege('laboratory_outbox_authority','public','CREATE') "
                "from pg_index i join pg_class c on c.oid=i.indexrelid "
                "where i.indexrelid='public.transactional_outbox_pending_specimen_idx'::regclass"
            ).fetchone()
        self.assertIn("(tenant_id, aggregate_id)", keys)
        self.assertEqual(predicate, "(delivery_state <> 'delivered'::text)")
        self.assertEqual(owner, "laboratory_outbox_authority")
        self.assertTrue(valid)
        self.assertFalse(schema_create)

    def test_pending_counts_preserve_states_empty_specimens_and_tenant_scope(self):
        with psycopg.connect(APP_DSN) as connection:
            self.bind(connection, self.tenants[0])
            self.assertEqual(connection.execute(QUERY, (self.tenants[0],)).fetchall(),
                             [("SYN-1", 3), ("SYN-2", 0)])
            self.assertEqual(connection.execute(QUERY, (self.tenants[1],)).fetchall(), [])
        with psycopg.connect(APP_DSN) as connection:
            self.bind(connection, self.tenants[1])
            self.assertEqual(connection.execute(QUERY, (self.tenants[1],)).fetchall(), [("SYN-1", 7)])

    def test_observe_pending_count_plan_at_explicit_synthetic_cardinality(self):
        with psycopg.connect(APP_DSN) as connection:
            self.bind(connection, self.tenants[2])
            connection.execute("set local statement_timeout=30000")
            rows = connection.execute(QUERY, (self.tenants[2],)).fetchall()
            self.assertEqual(len(rows), 1000)
            self.assertTrue(all(count == 10 for _, count in rows))
            record = connection.execute(
                "explain (analyze,buffers,format json) " + QUERY, (self.tenants[2],),
            ).fetchone()[0][0]
            engine = connection.execute("show server_version_num").fetchone()[0]
        observed = []
        for node in plan_nodes(record["Plan"]):
            if node.get("Relation Name") == "transactional_outbox":
                observed.append({key: node[key] for key in (
                    "Node Type", "Actual Rows", "Actual Loops", "Rows Removed by Filter",
                    "Shared Hit Blocks", "Shared Read Blocks",
                ) if key in node})
        # Planner choices and timing are observations; exact counts define correctness.
        print(json.dumps({
            "observation": "pending_outbox_count", "server_version_num": engine,
            "specimens": 1000, "pending_messages": 10000,
            "outbox_nodes": observed, "execution_ms": record["Execution Time"],
            "shared_hit_blocks": record["Plan"]["Shared Hit Blocks"],
            "shared_read_blocks": record["Plan"]["Shared Read Blocks"],
        }, sort_keys=True))
