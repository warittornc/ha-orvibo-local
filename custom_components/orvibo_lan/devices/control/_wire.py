"""Shared control envelope, LAN formatting, and serial allocation."""

from typing import Any

from ...protocol.constants import CMD_CONTROL, CONTROL_DEBUG_INFO, CONTROL_SOFTWARE_VER
from ...protocol.serial import next_serial


def _serial() -> int:
    return next_serial()


def _uni_serial() -> int:
    return next_serial()


def _to_lan(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt an SSL payload for LAN transport."""
    # Retain groupId; the app sends an empty groupId.
    # AC (type 36) uses gateway control and requires groupId.
    if "source" not in payload:
        payload["source"] = "ZhiJia365"
    # Retain groupid/qualityOfService/defaultResponse/propertyResponse.
    # The app sends these fields; groupid may affect Zapier/Zigbee devices,
    # but retaining it does not affect non-Zigbee AC (type 36).
    return payload


def command_fields(serial: int, uni_serial: int) -> dict[str, Any]:
    """Common ordered wire fields; callers retain control of serial allocation."""
    return {
        "cmd": CMD_CONTROL,
        "serial": serial,
        "clientType": 1,
        "uniSerial": uni_serial,
        "serverRecord": False,
        "ver": CONTROL_SOFTWARE_VER,
    }


def _base(device_id: str, uid: str, username: str = "") -> dict:
    """Base fields shared by control commands."""
    return {
        "uid": uid,
        "userName": username,
        "deviceId": device_id,
        "delayTime": 0,
        **command_fields(_serial(), _uni_serial()),
        "debugInfo": CONTROL_DEBUG_INFO,
    }
