"""Climate device control payloads."""

from typing import Any

from ...protocol.constants import CONTROL_DEBUG_INFO
from ._wire import _serial, _to_lan, _uni_serial, command_fields


def _ac_base(device_id: str, uid: str, username: str = "") -> dict:
    """Base AC command fields matching the app format."""
    return {
        "uid": uid,
        "userName": username,
        "deviceId": device_id,
        "groupId": "",
        "delayTime": 0,
        "qualityOfService": 1,
        "defaultResponse": 1,
        "propertyResponse": 0,
        **command_fields(_serial(), _uni_serial()),
        "debugInfo": CONTROL_DEBUG_INFO,
    }


def ac_off(device_id: str, uid: str, username: str = "") -> dict:
    """Turn off the air conditioner."""
    payload = _ac_base(device_id, uid, username)
    payload.update(
        {
            "order": "off",
            "value1": 1,
            "value2": 0,
            "value3": 0,
            "value4": 0,
        }
    )
    return _to_lan(payload)


def ac_on_with_mode(
    device_id: str,
    uid: str,
    mode: int,
    username: str = "",
    current_state: dict[str, Any] | None = None,
) -> dict:
    """Turn on and set mode; the app uses order='on' for power and 'mode setting' for mode changes.

    The captured app request uses order='on' when starting from off.
    The existing running-mode path uses order='mode setting'.
    Pass current_state to retain temperature and fan speed.
    """
    temp = 2500  # Default 25 C
    fan = 1  # Default low fan speed
    if current_state:
        v3 = current_state.get("value3", 0)
        if v3 and 1 <= int(v3) <= 3:
            fan = int(v3)
        v4 = current_state.get("value4", 0)
        if v4:
            hi = int(v4) >> 16
            if hi > 0:
                temp = hi

    payload = _ac_base(device_id, uid, username)
    payload.update(
        {
            "order": "on",  # The app starts with "on" rather than "mode setting".
            "value1": 0,
            "value2": mode,
            "value3": fan,
            "value4": temp << 16,
        }
    )
    return _to_lan(payload)


def ac_set_temp(
    device_id: str,
    uid: str,
    temp: int,
    username: str = "",
    current_state: dict[str, Any] | None = None,
) -> dict:
    """Set AC temperature, retaining mode in value2 and fan speed in value3."""
    mode = 3  # Default to cooling
    fan = 1  # Default low fan speed
    if current_state:
        v2 = current_state.get("value2", 0)
        if v2:
            mode = int(v2)
        v3 = current_state.get("value3", 0)
        if v3 and 1 <= int(v3) <= 3:
            fan = int(v3)

    payload = _ac_base(device_id, uid, username)
    payload.update(
        {
            "order": "temperature setting",
            "value1": 0,
            "value2": mode,
            "value3": fan,
            "value4": (temp * 100) << 16,
        }
    )
    return _to_lan(payload)


def ac_wind(
    device_id: str,
    uid: str,
    speed: int,
    username: str = "",
    current_state: dict[str, Any] | None = None,
) -> dict:
    """Set AC fan speed, retaining mode in value2 and temperature in value4."""
    mode = 3  # Default to cooling
    temp = 2500  # Default 25 C
    if current_state:
        v2 = current_state.get("value2", 0)
        if v2:
            mode = int(v2)
        v4 = current_state.get("value4", 0)
        if v4:
            hi = int(v4) >> 16
            if hi > 0:
                temp = hi

    payload = _ac_base(device_id, uid, username)
    payload.update(
        {
            "order": "wind setting",
            "value1": 0,
            "value2": mode,
            "value3": speed,
            "value4": temp << 16,
        }
    )
    return _to_lan(payload)
