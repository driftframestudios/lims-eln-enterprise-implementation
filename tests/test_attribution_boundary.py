"""Repository attribution carrier checks."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPANY = "Driftframe Studios, Limited Liability Company"
APPROVED_PERSONAL_NAME_CARRIERS = {"AUTHORS"}
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


def _personal_name(authors: str) -> str:
    match = re.search(
        r"is authored by (?P<name>[^\n]+) and\s+maintained by",
        authors,
    )
    if match is None:
        raise AssertionError("AUTHORS requires an explicit personal authorship entry")
    name = match.group("name").strip()
    if len(name.split()) < 2:
        raise AssertionError("AUTHORS requires an unambiguous personal name")
    return name


def _observed_personal_name_carriers(personal_name: str) -> set[str]:
    pattern = re.compile(
        rf"(?<!\w){re.escape(personal_name)}(?!\w)",
        re.IGNORECASE,
    )
    carriers: set[str] = set()
    for path in sorted(ROOT.rglob("*")):
        if (
            not path.is_file()
            or path.is_symlink()
            or any(part in IGNORED_PARTS for part in path.parts)
            or any(part.endswith(".egg-info") for part in path.parts)
        ):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if pattern.search(content):
            carriers.add(path.relative_to(ROOT).as_posix())
    return carriers


class AttributionBoundaryTests(unittest.TestCase):
    def test_personal_name_carriers_match_the_approved_set(self) -> None:
        authors = (ROOT / "AUTHORS").read_text(encoding="utf-8")
        package = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]

        self.assertIn(COMPANY, authors)
        self.assertEqual(package["authors"], [{"name": COMPANY}])
        self.assertEqual(
            _observed_personal_name_carriers(_personal_name(authors)),
            APPROVED_PERSONAL_NAME_CARRIERS,
        )


if __name__ == "__main__":
    unittest.main()
