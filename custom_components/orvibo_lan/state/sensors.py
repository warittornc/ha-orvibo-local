"""Derive sensor values from device wire state without changing the input."""

from collections.abc import Mapping

from ..devices.capabilities import (
    PROPERTY_BATTERY_POWER,
    PROPERTY_DOOR_STATUS,
    normalize_device_type,
    property_percentage,
    property_switch_state,
    state_properties,
)
from ..devices.profiles import profile_for


def sensor_state(values: Mapping[str, object], device: Mapping[str, object]) -> dict[str, object]:
    """Return detached state with normalized sensor properties."""
    state = dict(values)
    device_type = normalize_device_type(device.get("deviceType"))

    def integer(value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    for reading in profile_for(device_type).readings:
        value = integer(state.get(reading.wire_field))
        if value is not None:
            state[reading.state_key] = value == 1 if reading.kind == "flag" else float(value)
    value4 = integer(state.get("value4"))
    if value4 is not None and 0 <= value4 <= 100:
        state["battery"] = value4

    properties = state_properties(state)
    battery = property_percentage(properties, PROPERTY_BATTERY_POWER)
    if battery is not None:
        state["battery"] = battery
    door_open = property_switch_state(properties, PROPERTY_DOOR_STATUS)
    if door_open is not None:
        state["property_door_open"] = door_open
    return state
