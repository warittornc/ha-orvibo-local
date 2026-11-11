"""Device selection and platform filtering for Orvibo LAN config entries."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from .capabilities import supports_platform

CONF_SELECTED_DEVICE_IDS = "selected_device_ids"


def config_entry_unique_id(user_id: str, family_id: str | None) -> str:
    """Scope one account identity to a family when available."""

    identity = f"{user_id}:{family_id}" if family_id else user_id
    return f"global:{identity}"


def selected_device_ids(
    options: Mapping[str, Any],
    available_device_ids: Iterable[str],
) -> set[str]:
    """Return selected device IDs; legacy entries default to all available devices."""
    available = {str(device_id) for device_id in available_device_ids}
    if CONF_SELECTED_DEVICE_IDS not in options:
        return available
    configured = options.get(CONF_SELECTED_DEVICE_IDS)
    if not isinstance(configured, (list, tuple, set)):
        return set()
    return {str(device_id) for device_id in configured} & available


def platform_devices(
    options: Mapping[str, Any],
    devices: Mapping[str, Mapping[str, Any]],
    get_state: Callable[[str], Mapping[str, Any] | None],
    platform: str,
) -> Iterator[tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    """Yield selected devices and their current state when the profile supports a platform."""
    selected = selected_device_ids(options, devices)
    for device_id, device in devices.items():
        if device_id not in selected:
            continue
        state = get_state(device_id) or {}
        if supports_platform(device, state, platform):
            yield device_id, device, state
