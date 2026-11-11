"""Numeric device control payloads."""

from typing import Any

from ._wire import _serial, _to_lan, _uni_serial, command_fields


def _numeric_control(
    device_id: str,
    uid: str,
    order: str,
    value: int,
    username: str,
    *,
    include_group: bool = False,
) -> dict[str, Any]:
    """Build the shared legacy numeric command without changing its wire fields."""
    payload: dict[str, Any] = {"uid": uid, "userName": username, "deviceId": device_id}
    if include_group:
        payload["groupId"] = ""
    payload.update(
        {
            "order": order,
            "value1": value,
            "value2": 0,
            "value3": 0,
            "value4": 0,
            "delayTime": 0,
            **command_fields(_serial(), _uni_serial()),
        }
    )
    return _to_lan(payload)


def curtain_position(
    device_id: str,
    uid: str,
    position: int | str,
    username: str = "",
) -> dict:
    """Set curtain position: 0-100 or 'stop'."""

    if isinstance(position, str) and position == "stop":
        order, value1 = "stop", 0
    else:
        pos = max(0, min(int(position), 100))
        order = "close" if pos == 0 else "open"
        value1 = pos

    return _numeric_control(device_id, uid, order, value1, username, include_group=True)


def ventilation_control(device_id: str, uid: str, value1: int, username: str = "") -> dict:
    """Ventilation control: value1 0=slow, 50=stop, 100=fast."""
    return _numeric_control(device_id, uid, "set property", value1, username, include_group=True)


def fan_on(device_id: str, uid: str, device_type: int, username: str = "") -> dict:
    """Turn on a verified ventilation profile at its fast preset."""
    return ventilation_control(device_id, uid, 100, username)


def fan_off(device_id: str, uid: str, device_type: int, username: str = "") -> dict:
    """Stop a ventilation profile."""
    return ventilation_control(device_id, uid, 50, username)


def fan_set_speed(
    device_id: str, uid: str, device_type: int, percentage: int, username: str = ""
) -> dict:
    """Map HA percentage to the protocol's slow/stop/fast presets."""
    requested = max(0, min(int(percentage), 100))
    if requested == 0:
        value1 = 50
    elif requested <= 50:
        value1 = 0
    else:
        value1 = 100
    return ventilation_control(device_id, uid, value1, username)


def cover_open(device_id: str, uid: str, username: str = "") -> dict:
    return curtain_control(device_id, uid, "open", username)


def cover_close(device_id: str, uid: str, username: str = "") -> dict:
    return curtain_control(device_id, uid, "close", username)


def cover_stop(device_id: str, uid: str, username: str = "") -> dict:
    return curtain_control(device_id, uid, "stop", username)


def cover_position(
    device_id: str,
    uid: str,
    position: int,
    username: str = "",
) -> dict:
    return curtain_control(device_id, uid, max(0, min(int(position), 100)), username)


def curtain_control(
    device_id: str,
    uid: str,
    cmd: str | int,
    username: str = "",
) -> dict:

    if cmd == "open":
        order, value1 = "on", 100
    elif cmd == "close":
        order, value1 = "off", 0
    elif cmd == "stop":
        order, value1 = "stop", 0
    else:
        pos = max(0, min(int(cmd), 100))
        order = "on" if pos >= 50 else "off"
        value1 = pos

    return _numeric_control(device_id, uid, order, value1, username)
