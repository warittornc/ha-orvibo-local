"""Normalized sensor fields preserve wire input and property precedence."""

import pytest

from custom_components.orvibo_lan.state.sensors import sensor_state


@pytest.mark.parametrize(
    ("device_type", "field", "value", "expected"),
    [
        (46, "door_state", "1", True),
        (26, "motion_detected", "0", False),
        (27, "smoke_detected", "1", True),
        (25, "gas_detected", "0", False),
        (54, "water_leak_detected", "1", True),
        (56, "emergency_state", "0", False),
    ],
)
def test_binary_sensor_derivation_keeps_wire_state(device_type, field, value, expected):
    wire = {"value1": value, "value3": value, "value4": "42"}
    result = sensor_state(wire, {"deviceType": device_type})
    assert result[field] is expected
    assert result["battery"] == 42
    assert wire == {"value1": value, "value3": value, "value4": "42"}


def test_environment_and_property_precedence():
    wire = {
        "value1": "0",
        "value2": "55",
        "value4": "42",
        "properties": {"battery_power": {"percent": 88}},
    }
    result = sensor_state(wire, {"deviceType": 22})
    assert result["temperature"] == 0.0
    assert result["humidity"] == 55.0
    assert result["battery"] == 88
    assert "battery" not in wire
