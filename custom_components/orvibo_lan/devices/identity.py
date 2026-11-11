"""Device-registry identity for Orvibo devices and MixPad gateways.

Lifecycle registration and every entity's ``device_info`` describe the same
registry device, so both build it here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import DOMAIN, MANUFACTURER


def device_identifier(device_id: str) -> tuple[str, str]:
    return (DOMAIN, f"device_{device_id}")


def gateway_identifier(gateway_uid: str) -> tuple[str, str]:
    return (DOMAIN, f"gateway_{gateway_uid}")


def device_registry_info(
    device_id: str,
    device: Mapping[str, Any],
    *,
    model: str,
    name_prefix: str,
) -> dict[str, Any]:
    """Return the registry fields for one device; LAN devices hang off their gateway."""
    name = device.get("deviceName")
    info: dict[str, Any] = {
        "identifiers": {device_identifier(device_id)},
        "name": str(name) if name not in (None, "") else f"{name_prefix} {device_id[:8]}",
        "manufacturer": MANUFACTURER,
        "model": model,
    }
    uid = device.get("uid")
    if isinstance(uid, str) and uid and device.get("_orvibo_lan_capable"):
        info["via_device"] = gateway_identifier(uid)
    return info
