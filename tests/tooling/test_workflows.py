"""Structural contracts for the validation workflow."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_ACTION = re.compile(r"^[\w.-]+(?:/[\w.-]+)+@[0-9a-f]{40}$")


def load_workflow(name: str) -> dict[str, object]:
    """Load JSON, a strict YAML subset accepted by GitHub Actions."""
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def action_references(workflow: dict[str, object]) -> list[str]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    references: list[str] = []
    for job in jobs.values():
        assert isinstance(job, dict)
        steps = job.get("steps", [])
        assert isinstance(steps, list)
        for step in steps:
            assert isinstance(step, dict)
            reference = step.get("uses")
            if isinstance(reference, str):
                references.append(reference)
    return references


class WorkflowTests(unittest.TestCase):
    """Verify triggers and validation duties."""

    def test_validate_owns_all_required_checks(self) -> None:
        workflow = load_workflow("validate.yml")
        triggers = workflow["on"]
        jobs = workflow["jobs"]
        assert isinstance(triggers, dict)
        assert isinstance(jobs, dict)
        self.assertTrue({"push", "pull_request"}.issubset(triggers))
        self.assertTrue(
            {"quality", "tests", "package-contract", "hassfest", "actionlint"}.issubset(jobs)
        )
        self.assertFalse((WORKFLOWS / "hacs.yml").exists())

        commands = "\n".join(
            str(step.get("run", ""))
            for job in jobs.values()
            if isinstance(job, dict)
            for step in job.get("steps", [])
            if isinstance(step, dict)
        )
        self.assertIn("ruff check custom_components tests", commands)
        self.assertIn("mypy custom_components/orvibo_lan", commands)
        self.assertIn("pytest --cov=custom_components.orvibo_lan", commands)
        self.assertIn("test_package_contract.py", commands)
        self.assertIn("test_workflows.py", commands)

        self.assertNotIn("pip install", commands)
        self.assertIn("uv sync --locked", commands)
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps", [])
            if any("uv run" in str(step.get("run", "")) for step in steps):
                self.assertTrue(any(step.get("name") == "Install uv" for step in steps))

        references = action_references(workflow)
        self.assertTrue(
            any(
                reference.startswith("home-assistant/actions/hassfest@") for reference in references
            )
        )
        self.assertTrue(any(reference.startswith("rhysd/actionlint@") for reference in references))
        self.assertTrue(
            all(SHA_ACTION.fullmatch(reference) for reference in references), references
        )


if __name__ == "__main__":
    unittest.main()
