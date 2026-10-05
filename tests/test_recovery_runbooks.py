"""Execute the documented resume sequence with bounded command doubles."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/runbooks/local-container-entry.v0.1.md"


class RecoveryRunbookTests(unittest.TestCase):
    def test_resume_stops_at_the_first_failed_stage(self):
        section = GUIDE.read_text(encoding="utf-8").split("After that admission,", 1)[1]
        command = section.split("~~~sh\n", 1)[1].split("\n~~~", 1)[0]
        driver = """
docker() {
  case "$*" in
    *" stop application") stage=stop ;;
    *" rm -f database-role-provisioner database-migrator database-role-bootstrap") stage=rm ;;
    *" up -d application") stage=up ;;
    *) return 90 ;;
  esac
  printf '%s\\n' "$stage" >> "$CALLS"
  test "$stage" != "$FAIL_AT"
}
"""
        cases = (
            ("stop", "retained", ["stop"], 1),
            ("rm", "retained", ["stop", "rm"], 1),
            ("up", "retained", ["stop", "rm", "up"], 1),
            ("", "retained", ["stop", "rm", "up"], 0),
            ("", "", [], None),
        )
        for failure, project, expected, code in cases:
            with self.subTest(failure=failure, project=project), tempfile.TemporaryDirectory() as temporary:
                calls = Path(temporary) / "calls"
                result = subprocess.run(
                    ["sh", "-c", driver + "\n" + command],
                    env={**os.environ, "PROJECT": project, "FAIL_AT": failure, "CALLS": str(calls)},
                    capture_output=True, text=True, timeout=5, check=False,
                )
                if code is None:
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, code)
                observed = calls.read_text().splitlines() if calls.exists() else []
                self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()
