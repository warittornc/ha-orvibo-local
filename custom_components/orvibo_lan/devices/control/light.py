"""Light device control payloads.

Which format each command uses comes from the device profile's ``LightWire``;
this module never compares raw type codes.
"""

from typing import Any

from ..profiles import profile_for, uses_thing_model
from ._wire import _base, _serial, _to_lan, _uni_serial, command_fields

# One colour temperature range for both the entity and the payloads (kelvin).
MIN_KELVIN = 2700
MAX_KELVIN = 6000


def clamp_kelvin(kelvin: int) -> int:
    return max(MIN_KELVIN, min(int(kelvin), MAX_KELVIN))


def _percent(brightness: int) -> int:
    return max(1, brightness * 100 // 255)


def _payload(
    device_id: str,
    uid: str,
    username: str,
    order: str,
    values: tuple[int, int, int, int],
    *,
    group: bool,
    properties: dict[str, Any] | None = None,
) -> dict:
    """Build one light command, keeping the captured wire field order."""
    payload: dict[str, Any] = {"uid": uid, "userName": username, "deviceId": device_id}
    if group:
        payload["groupId"] = ""
    payload["order"] = order
    payload.update(zip(("value1", "value2", "value3", "value4"), values))
    payload["delayTime"] = 0
    payload.update(command_fields(_serial(), _uni_serial()))
    if properties is not None:
        payload["properties"] = properties
    return _to_lan(payload)


def light_on(device_id: str, uid: str, device_type: int, username: str = "") -> dict:
    """Turn on a light."""
    if uses_thing_model(device_type):
        return _payload(
            device_id,
            uid,
            username,
            "set property",
            (0, 0, 0, 0),
            group=False,
            properties={"onoff": {"status": "on"}},
        )
    return _payload(device_id, uid, username, "on", (0, 255, 0, 0), group=False)


def light_off(device_id: str, uid: str, device_type: int, username: str = "") -> dict:
    """Turn off a light."""
    if uses_thing_model(device_type):
        return _payload(
            device_id,
            uid,
            username,
            "set property",
            (0, 0, 0, 0),
            group=False,
            properties={"onoff": {"status": "off"}},
        )
    return _payload(device_id, uid, username, "off", (1, 0, 0, 0), group=False)


def power_only_light(device_id: str, uid: str, state: bool, username: str = "") -> dict:
    """Control captured type-1/type-102 subtype-1 relay endpoints."""
    payload = _base(device_id, uid, username)
    payload.update(
        {
            "groupId": "",
            "order": "on" if state else "off",
            "value1": 0 if state else 1,
            "value2": 0,
            "value3": 0,
            "value4": 0,
        }
    )
    return _to_lan(payload)


def light_brightness(
    device_id: str, uid: str, device_type: int, brightness: int, username: str = ""
) -> dict:
    """Set brightness in the 0-255 range."""
    bri = max(0, min(int(brightness), 255))
    dimming = profile_for(device_type).light_wire.dimming
    if dimming == "property":
        return _payload(
            device_id,
            uid,
            username,
            "set property",
            (0, 0, 0, 0),
            group=True,
            properties={"brightness": {"percent": _percent(bri)}},
        )
    if dimming == "level":
        # Tunable lights use move to level (standard ZCL dimming).
        return _payload(device_id, uid, username, "move to level", (0, bri, 0, 0), group=False)
    return _payload(device_id, uid, username, "on", (0, bri, 0, 0), group=True)


def light_colortemp(
    device_id: str,
    uid: str,
    device_type: int,
    kelvin: int,
    brightness: int = 255,
    username: str = "",
) -> dict:
    """Set colour temperature, clamped to MIN_KELVIN-MAX_KELVIN."""
    ct = clamp_kelvin(kelvin)
    bri = max(0, min(int(brightness), 255))
    if profile_for(device_type).light_wire.color_temp == "property":
        return _payload(
            device_id,
            uid,
            username,
            "set property",
            (0, 0, 0, 0),
            group=True,
            properties={"colorTemp": {"value": ct}},
        )
    return _payload(
        device_id, uid, username, "fast color temperature", (0, bri, 1000000 // ct, 0), group=True
    )


def light_on_off(
    device_id: str,
    uid: str,
    device_type: int,
    power: bool,
    brightness: int = 0,
    color_temp_k: int | None = None,
    username: str = "",
) -> dict:
    """Send power, brightness, and colour temperature together."""
    bri = max(0, min(int(brightness), 255))
    wire = profile_for(device_type).light_wire

    if wire.combined == "property":
        properties: dict[str, Any] = {
            "onoff": {"status": "on" if power else "off"},
            "brightness": {"percent": _percent(bri)},
        }
        if color_temp_k and wire.color_temp == "property":
            properties["colorTemp"] = {"value": clamp_kelvin(color_temp_k)}
        return _payload(
            device_id,
            uid,
            username,
            "set property",
            (0, 0, 0, 0),
            group=True,
            properties=properties,
        )
    # Legacy: order=on/off, value2=brightness, value3=colour temperature (mired).
    ct_val = 1000000 // clamp_kelvin(color_temp_k) if color_temp_k else 0
    return _payload(
        device_id,
        uid,
        username,
        "on" if power else "off",
        (0 if power else 1, bri, ct_val, 0),
        group=True,
    )
