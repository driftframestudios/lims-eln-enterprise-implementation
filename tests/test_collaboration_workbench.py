"""Material contracts for the repository-local collaboration workbench."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "enterprise_validate_repository",
    ROOT / "scripts" / "validate_repository.py",
)
assert SPEC and SPEC.loader
validation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validation
SPEC.loader.exec_module(validation)


class CollaborationWorkbenchTests(unittest.TestCase):
    def copy_workbench(self, destination: Path) -> None:
        shutil.copytree(ROOT / ".agents", destination / ".agents")
        shutil.copy2(ROOT / "README.md", destination / "README.md")
        shutil.copy2(ROOT / "AGENTS.md", destination / "AGENTS.md")

    def test_repository_local_workbench_has_exact_lineage_and_routes(self) -> None:
        self.assertEqual([], validation.validate_collaboration_workbench())
        self.assertEqual(
            {
                "configured-environment-evidence-binding",
                "contextual-jargon-scan",
                "proportionate-recovery-routing",
                "repository-reentry",
                "source-authority-mapping",
            },
            {
                validation.parse_skill_source(ROOT / relative)[0]["name"]
                for relative in validation.PUBLIC_POSSIBLE_SKILL_METADATA
            },
        )
        self.assertTrue(
            all(
                validation.parse_skill_source(ROOT / relative)[0]["source_band"]
                == "public_possible"
                for relative in validation.PUBLIC_POSSIBLE_SKILL_METADATA
            )
        )

    def test_upstream_lineage_drift_is_visible(self) -> None:
        with tempfile.TemporaryDirectory(prefix="enterprise-workbench-") as temporary:
            copy_root = Path(temporary)
            self.copy_workbench(copy_root)
            target = copy_root / ".agents/skills/repository-reentry/SKILL.md"
            source = target.read_text(encoding="utf-8")
            target.write_text(
                source.replace(
                    "0c023343e46cd9b1333a63c2d509787352fbad14",
                    "f" * 40,
                    1,
                ),
                encoding="utf-8",
            )
            findings = validation.validate_collaboration_workbench(copy_root)
            self.assertTrue(any("metadata differs" in item for item in findings))

    def test_public_inspection_inventory_carries_the_workbench(self) -> None:
        inspection = json.loads(
            (ROOT / "release/public-inspection-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        paths = {
            artifact["path"]
            for group in inspection["artifact_groups"]
            for artifact in group["artifacts"]
        }
        self.assertTrue(
            set(validation.PUBLIC_POSSIBLE_SKILL_METADATA).issubset(paths)
        )
        self.assertIn("AGENTS.md", paths)

    def test_recovery_and_evidence_binding_keep_distinct_jobs(self) -> None:
        recovery = (
            ROOT / ".agents/skills/proportionate-recovery-routing/SKILL.md"
        ).read_text(encoding="utf-8")
        binding = (
            ROOT
            / ".agents/skills/configured-environment-evidence-binding/SKILL.md"
        ).read_text(encoding="utf-8")
        for material_rule in (
            "Repeated execution requires a changed signal",
            "result stays at the existing assurance stage",
            "supplies environment facts",
            "Activation uses current authority",
        ):
            self.assertIn(material_rule, recovery)
        for material_rule in (
            "Bind the complete observation coordinate",
            "Keep evidence and assurance states distinct",
            "Scenarios distinguish behavior",
            "Secret evidence remains value-free",
            "does not diagnose",
            "authorize a retry",
        ):
            self.assertIn(material_rule, binding)


if __name__ == "__main__":
    unittest.main()
