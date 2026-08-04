from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SqlSchemaSourceTests(unittest.TestCase):
    def test_custody_change_and_outbox_insert_share_one_database_function(self) -> None:
        migration = (ROOT / "sql/V003__trusted_routines_and_outbox_cas.sql").read_text(
            encoding="utf-8"
        )
        start = migration.index("create or replace function public.record_custody_transfer")
        end = migration.index("$custody_transfer$;", start)
        function = migration[start:end]
        self.assertIn("insert into public.custody_event", function)
        self.assertIn("insert into public.transactional_outbox", function)


if __name__ == "__main__":
    unittest.main()
