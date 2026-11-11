"""Device profiles and readtable normalization for ORVIBO devices."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Optional

from .profiles import LightMode, Platform, is_status_only_type, platforms_for_type, profile_for

PROPERTY_DOOR_STATUS = "door_status"
PROPERTY_BATTERY_POWER = "battery_power"
READ_ONLY_PROPERTIES = frozenset({PROPERTY_DOOR_STATUS, PROPERTY_BATTERY_POWER})

VERIFIED_PROPERTY_LIGHT_MODELS = frozenset(
    {
        "294339fdc9b04613bb6cf1569305b78c",
        "71b94d0309094d1e9c678e4c21bbf878",
        "f731c19a484c419282051494ceecd66a",
    }
)


def normalize_device_type(value: Any) -> int:
    """Return a numeric device type, or zero for an invalid value."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_sub_device_type(value: Any) -> str:
    """Normalize sub-device types for profile matching."""
    return "" if value in (None, "") else str(value).strip()


def state_properties(state: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return a state's property mapping."""
    if not isinstance(state, Mapping):
        return {}
    properties = state.get("properties")
    return properties if isinstance(properties, Mapping) else {}


def property_value(properties: Mapping[str, Any], key: str) -> Any:
    """Extract scalar values from both cloud and ThingModel property shapes."""
    value = properties.get(key)
    if not isinstance(value, Mapping):
        return value
    for nested_key in ("value", "power", "status", "percent"):
        if nested_key in value:
            return value[nested_key]
    return None


def property_switch_state(properties: Mapping[str, Any], key: str) -> Optional[bool]:
    """Normalize an on/off property."""
    value = property_value(properties, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "open"}:
            return True
        if normalized in {"0", "false", "off", "closed"}:
            return False
    return None


def property_percentage(properties: Mapping[str, Any], key: str) -> Optional[int]:
    """Normalize a percentage property and reject invalid values."""
    return percentage_value(property_value(properties, key))


def platforms_for_device(
    device: Mapping[str, Any],
    state: Mapping[str, Any] | None = None,
) -> frozenset[Platform]:
    """Return all HA platforms supported by a device profile."""
    raw_device_type = device.get("deviceType")
    platforms: set[Platform] = set()
    if raw_device_type not in (None, ""):
        platforms.update(platforms_for_type(normalize_device_type(raw_device_type)))
        if is_plug(device) and Platform.LIGHT in platforms:
            platforms.discard(Platform.LIGHT)
            platforms.add(Platform.SWITCH)
    properties = state_properties(state)
    if PROPERTY_DOOR_STATUS in properties:
        platforms.add(Platform.BINARY_SENSOR)
    if PROPERTY_BATTERY_POWER in properties:
        platforms.add(Platform.SENSOR)
    return frozenset(platforms)


def supports_platform(
    device: Mapping[str, Any],
    state: Mapping[str, Any] | None,
    platform: str,
) -> bool:
    """Return whether a normalized device supports one HA platform."""
    return platform in platforms_for_device(device, state)


_RELAY_LIGHT_TYPES = frozenset({1, 102})
_RELAY_SUB_TYPE = "1"
_TUNABLE_SUB_TYPES = frozenset({"4", "6", "13"})
# Type-1 endpoints observed as plain on/off lights. They accept the legacy on/off
# payloads, so only the colour capability changes; commands stay the same.
_ONOFF_SUB_TYPES_BY_TYPE: Mapping[int, frozenset[str]] = {1: frozenset({"2"})}
# Type-1 endpoints that are plugs: exposed as switches instead of lights, using the
# same legacy on/off payloads.
_PLUG_SUB_TYPES_BY_TYPE: Mapping[int, frozenset[str]] = {1: frozenset({"12"})}


def is_plug(device: Mapping[str, Any]) -> bool:
    """Return whether a device is a plug that belongs on the switch platform."""
    device_type = normalize_device_type(device.get("deviceType"))
    sub_type = normalize_sub_device_type(device.get("subDeviceType"))
    return sub_type in _PLUG_SUB_TYPES_BY_TYPE.get(device_type, frozenset())
_PROPERTY_TUNABLE_SUB_TYPE = "436"


def _is_power_only_relay(device: Mapping[str, Any]) -> bool:
    """Captured relay endpoints expose power only even when their broad type is a light."""
    return (
        normalize_device_type(device.get("deviceType")) in _RELAY_LIGHT_TYPES
        and normalize_sub_device_type(device.get("subDeviceType")) == _RELAY_SUB_TYPE
    )


def light_color_mode(device: Mapping[str, Any]) -> LightMode:
    """Return the HA light capability for a verified or compatible profile."""
    if _is_power_only_relay(device):
        return "onoff"
    device_type = normalize_device_type(device.get("deviceType"))
    sub_type = normalize_sub_device_type(device.get("subDeviceType"))
    if sub_type in _ONOFF_SUB_TYPES_BY_TYPE.get(device_type, frozenset()):
        return "onoff"
    return profile_for(device_type).light_mode or "onoff"


def verified_profile_name(device: Mapping[str, Any]) -> str:
    """Return a stable profile name useful in diagnostics and tests."""
    device_type = normalize_device_type(device.get("deviceType"))
    sub_type = normalize_sub_device_type(device.get("subDeviceType"))
    model = str(device.get("model") or "").strip()

    if _is_power_only_relay(device):
        return "power_only_light"
    if device_type == 38 and sub_type in _TUNABLE_SUB_TYPES:
        return "tunable_light"
    if (
        device_type == 503
        and sub_type == _PROPERTY_TUNABLE_SUB_TYPE
        and model in VERIFIED_PROPERTY_LIGHT_MODELS
    ):
        return "property_tunable_light"
    return "legacy_type_profile"


def _first_text(item: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _has_read_only_capability(state: Mapping[str, Any] | None) -> bool:
    return bool(READ_ONLY_PROPERTIES.intersection(state_properties(state)))


def normalize_readtable_devices(
    devices: Sequence[Mapping[str, Any]],
    statuses: Mapping[str, Mapping[str, Any]],
    gateway_uids: set[str],
) -> list[dict[str, Any]]:
    """Filter LAN devices and retain property-capable status-only devices."""
    normalized: dict[str, dict[str, Any]] = {}

    for raw in devices:
        if not isinstance(raw, Mapping) or raw.get("delFlag") in (1, "1"):
            continue
        device_id = _first_text(raw, ("deviceId", "deviceID"))
        if not device_id:
            continue
        state = statuses.get(device_id)
        device_uid = _first_text(raw, ("uid",))
        lan_capable = bool(device_uid and device_uid in gateway_uids)
        read_only_capable = _has_read_only_capability(state)

        # Preserve the existing LAN rule, with a narrow exception for useful
        # property-based devices whose state comes from the cloud snapshot.
        if device_uid and not lan_capable and not read_only_capable:
            continue

        device = dict(raw)
        device["deviceId"] = device_id
        raw_device_type = device.get("deviceType")
        device["deviceType"] = (
            normalize_device_type(raw_device_type) if raw_device_type not in (None, "") else None
        )
        device["_orvibo_lan_capable"] = lan_capable
        device["_orvibo_read_only"] = not lan_capable
        device["_orvibo_status_only"] = (
            is_status_only_type(normalize_device_type(raw_device_type))
            if raw_device_type not in (None, "")
            else False
        )
        normalized[device_id] = device

    for device_id, state in statuses.items():
        if (
            device_id in normalized
            or not isinstance(state, Mapping)
            or state.get("delFlag") in (1, "1")
            or not _has_read_only_capability(state)
        ):
            continue

        source_uid = _first_text(state, ("uid",))
        lan_capable = bool(source_uid and source_uid in gateway_uids)
        model = _first_text(
            state,
            (
                "model",
                "modelName",
                "modelId",
                "modelID",
                "pdid",
            ),
        )
        normalized[device_id] = {
            "deviceId": device_id,
            "uid": source_uid if lan_capable else "",
            "sourceUid": source_uid,
            "deviceName": _first_text(
                state,
                ("deviceName", "devName", "name", "nickName", "nickname"),
            )
            or model
            or f"ORVIBO {device_id[-6:]}",
            "model": model,
            "deviceType": (
                normalize_device_type(state.get("deviceType"))
                if state.get("deviceType") not in (None, "")
                else None
            ),
            "subDeviceType": normalize_sub_device_type(
                state.get("subDeviceType", state.get("subDevType")),
            ),
            "roomId": _first_text(state, ("roomId", "roomID")),
            "_orvibo_lan_capable": lan_capable,
            "_orvibo_read_only": not lan_capable,
            "_orvibo_status_only": True,
        }

    return list(normalized.values())


def finite_number(value: object) -> float | None:
    """Convert one scalar to a finite float, rejecting booleans."""

    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def percentage_value(value: object) -> int | None:
    """Convert one scalar to an integer percentage."""

    number = finite_number(value)
    if number is None:
        return None
    percentage = int(number)
    if percentage < 0 or percentage > 100:
        return None
    return percentage


def battery_percentage(state: Mapping[str, Any]) -> int | None:
    """Read a battery percentage from known property and legacy shapes."""

    properties = state_properties(state)
    for property_key in (PROPERTY_BATTERY_POWER, "battery"):
        property_battery = property_percentage(properties, property_key)
        if property_battery is not None:
            return property_battery
    for key in ("battery", "batteryLevel", "powerLevel"):
        value = percentage_value(state.get(key))
        if value is not None:
            return value
    return percentage_value(state.get("value4"))


def measurement_value(state: Mapping[str, Any], key: str, fallback: str) -> float | None:
    """Read normalized, ThingModel, then legacy measurement fields."""

    value = finite_number(state.get(key))
    if value is not None:
        return value
    value = finite_number(property_value(state_properties(state), key))
    return value if value is not None else finite_number(state.get(fallback))
