"""Wire-payload regression fixtures captured before command builder consolidation."""

import itertools
import json
from pathlib import Path

import pytest

from custom_components.orvibo_lan.devices.control import _wire, climate, light, numeric

NUMERIC_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "numeric_controls.json").read_text()
)
CASES = NUMERIC_CASES + json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "light_climate_controls.json").read_text()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case['function']}({case['args'][2]})")
def test_numeric_control_preserves_payload_and_serial_allocation(case, monkeypatch):
    serials = itertools.count(1)
    monkeypatch.setattr(_wire, "next_serial", lambda: next(serials))
    module = (
        climate
        if case["function"].startswith("ac_")
        else light
        if case["function"].startswith(("light_", "power_only"))
        else numeric
    )
    payload = getattr(module, case["function"])(*case["args"])
    assert payload == case["payload"]
    # JSON insertion order is preserved as well as field names and values.
    assert json.dumps(payload) == json.dumps(case["payload"])
    assert next(serials) == case.get("next_serial", 3)
