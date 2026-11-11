"""Integration package contract tests using only the Python standard library."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "custom_components" / "orvibo_lan"


class PackageContractTests(unittest.TestCase):
    """Verify integration metadata that HACS and Home Assistant read from the repository."""

    def test_services_only_describe_registered_features(self) -> None:
        services = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")

        self.assertIn("refresh_devices:", services)
        self.assertNotIn("clothes_horse_control:", services)

    def test_versions_and_compatibility_are_manifest_driven(self) -> None:
        manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertEqual(manifest["domain"], "orvibo_lan")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["codeowners"], ["@warittornc"])
        self.assertEqual(
            manifest["documentation"],
            "https://github.com/warittornc/ha-orvibo-local",
        )
        self.assertEqual(
            manifest["issue_tracker"],
            "https://github.com/warittornc/ha-orvibo-local/issues",
        )
        self.assertEqual(hacs["homeassistant"], "2026.11.1")
        self.assertFalse(hacs.get("content_in_root", False))
        # HACS installs the integration folder straight from the repository.
        self.assertNotIn("zip_release", hacs)
        self.assertNotIn("filename", hacs)
        self.assertTrue((INTEGRATION / "manifest.json").is_file())
        self.assertNotRegex(pyproject, r"(?m)^\s*version\s*=")
        self.assertIn("package = false", pyproject)
        self.assertEqual((ROOT / ".python-version").read_text().strip(), "3.11")


if __name__ == "__main__":
    unittest.main()
