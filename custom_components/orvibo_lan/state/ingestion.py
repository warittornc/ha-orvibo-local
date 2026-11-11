"""Admit gateway state only after source and payload validation."""

import logging
from collections.abc import Collection, Mapping

from ..auth.privacy import mask_identifier
from ..protocol.constants import CMD_STATE_UPDATE
from ..protocol.message import command_of, device_id_of, gateway_uid_of

_LOGGER = logging.getLogger(__name__)

_STATE_NUMBER_FIELDS = frozenset(("value1", "value2", "value3", "value4"))
_STATE_NUMBER_MIN = -(1 << 31)
_STATE_NUMBER_MAX = (1 << 32) - 1
_DERIVED_STATE_FIELDS = frozenset(
    (
        "battery",
        "door_state",
        "emergency_state",
        "gas_detected",
        "humidity",
        "motion_detected",
        "property_door_open",
        "smoke_detected",
        "temperature",
        "water_leak_detected",
    )
)
_LAN_METADATA_FIELDS = frozenset(
    (
        "cmd",
        "debugInfo",
        "gatewayUID",
        "gatewayUid",
        "serial",
        "serverRecord",
        "source",
        "uid",
        "uniSerial",
        "userName",
        "ver",
    )
)


def _valid_lan_state_payload(payload: Mapping[str, object]) -> bool:
    """Reject malformed state values before they reach entity state."""

    properties = payload.get("properties")
    if properties is not None and not isinstance(properties, Mapping):
        return False
    if _DERIVED_STATE_FIELDS.intersection(payload):
        return False
    for field in _STATE_NUMBER_FIELDS.intersection(payload):
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return False
        try:
            number = int(str(value).strip())
        except ValueError:
            return False
        if not _STATE_NUMBER_MIN <= number <= _STATE_NUMBER_MAX:
            return False
    return True


def admit_lan_state(
    gateway_uid: str,
    payload: Mapping[str, object],
    devices: Mapping[str, Mapping[str, object]],
    known_device_ids: Collection[str],
) -> dict[str, object] | None:
    """Return canonical state for an owned, known device; reject other updates."""
    fields = tuple(sorted(str(key) for key in payload if not str(key).startswith("__")))
    command = command_of(payload)
    if command is None:
        _LOGGER.debug(
            "Dropped LAN state from gateway %s with invalid command %r",
            mask_identifier(gateway_uid),
            command,
        )
        return None
    if command != CMD_STATE_UPDATE:
        _LOGGER.debug(
            "Validating compatibility LAN state command %r from gateway %s",
            command,
            mask_identifier(gateway_uid),
        )
    device_id = device_id_of(payload)
    if device_id is None:
        _LOGGER.debug(
            "Dropped LAN state from gateway %s without a device ID (cmd=%r, fields=%s)",
            mask_identifier(gateway_uid),
            command,
            fields,
        )
        return None
    if device_id not in known_device_ids:
        _LOGGER.debug(
            "Ignoring LAN state for unknown device %s (cmd=%r, fields=%s)",
            mask_identifier(device_id),
            command,
            fields,
        )
        return None

    device = devices.get(device_id)
    expected_gateway = device.get("uid") if device is not None else None
    if not isinstance(expected_gateway, str) or expected_gateway != gateway_uid:
        _LOGGER.debug(
            "Ignoring LAN state for device %s from wrong gateway %s",
            mask_identifier(device_id),
            mask_identifier(gateway_uid),
        )
        return None
    payload_gateway = gateway_uid_of(payload)
    if payload_gateway is not None and payload_gateway != gateway_uid:
        _LOGGER.debug(
            "Ignoring LAN state for device %s with mismatched gateway metadata",
            mask_identifier(device_id),
        )
        return None
    if not _valid_lan_state_payload(payload):
        _LOGGER.debug(
            "Rejected malformed LAN state for device %s (fields=%s)",
            mask_identifier(device_id),
            fields,
        )
        return None

    values = {
        str(key): value
        for key, value in payload.items()
        if not str(key).startswith("__") and value is not None
    }
    values.pop("deviceID", None)
    values.pop("device_id", None)
    for field in _LAN_METADATA_FIELDS:
        values.pop(field, None)
    values["deviceId"] = device_id
    return values
