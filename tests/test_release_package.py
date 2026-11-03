"""Release archives contain runtime code, not development or repository files."""
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from scripts.build_release import ROOT, build


class ReleasePackageTests(unittest.TestCase):
    def test_release_zip_is_minimal_and_complete(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        with tempfile.TemporaryDirectory() as temp:
            manifest = build("mrremka/-KREW-Bot", f"v{version}", Path(temp))
            with ZipFile(Path(temp) / "krew-update.zip") as archive:
                entries = set(archive.namelist())
        required = {"VERSION", "main.py", "launcher.py", "updater.py",
                    "krew/core.py", "krew/db.py", "krew/ui.py", ".env.example",
                    "release_notes.json"}
        self.assertTrue(required.issubset(entries), sorted(required - entries))
        excluded = {"README.md", "CHANGELOG.md", "Dockerfile", "compose.yaml",
                    ".gitignore", ".dockerignore", "START_WINDOWS.txt"}
        self.assertFalse(entries.intersection(excluded))
        self.assertFalse(any(name.startswith(("tests/", ".github/", "updates/", "scripts/"))
                             for name in entries))
        self.assertEqual(manifest["version"], version)
