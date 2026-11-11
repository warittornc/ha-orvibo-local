"""Read the routing fields of one gateway message.

The gateway connection (deciding push vs response, and checking identity) and
LAN state admission (deciding what to trust) must agree on these readings, so
both use this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .constants import CMD_STATE_UPDATE

_DEVICE_ID_FIELDS = ("deviceId", "deviceID", "device_id")
_GATEWAY_UID_FIELDS = ("gatewayUid", "gatewayUID", "uid")


def command_of(payload: Mapping[str, Any]) -> int | None:
    """Return the integer ``cmd``; booleans and malformed values read as missing."""
    value = payload.get("cmd")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def device_id_of(payload: Mapping[str, Any]) -> str | None:
    """Return the device identifier under any firmware spelling, stripped."""
    for field in _DEVICE_ID_FIELDS:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        device_id = str(value).strip()
        if device_id:
            return device_id
    return None


def gateway_uid_of(payload: Mapping[str, Any]) -> str | None:
    """Return the gateway uid a message claims, stripped."""
    for field in _GATEWAY_UID_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def is_device_update(payload: Mapping[str, Any], *, correlated: bool) -> bool:
    """Whether a message is an unsolicited device update rather than a response.

    Some firmware uses a non-standard command number for uncorrelated device
    updates; those still count when no request is waiting for them.
    """
    if command_of(payload) == CMD_STATE_UPDATE:
        return True
    return not correlated and device_id_of(payload) is not None
