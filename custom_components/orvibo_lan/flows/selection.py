"""Shared device-selection presentation for the flow adapters."""

import voluptuous as vol
from homeassistant.helpers import selector

from ..const import CONF_SELECTED_DEVICE_IDS

JsonObject = dict[str, object]


def device_label(device_id: str, name: str, room: str) -> str:
    return f"{name} [{room}]" if room and room != name else name or device_id[-8:]


def device_schema(
    devices: list[JsonObject],
    default_ids: list[str] | None = None,
) -> vol.Schema:
    options = [
        selector.SelectOptionDict(
            value=str(device["deviceId"]),
            label=device_label(
                str(device["deviceId"]),
                str(device.get("deviceName") or ""),
                str(device.get("roomName") or ""),
            ),
        )
        for device in devices
    ]
    defaults = default_ids or [str(device["deviceId"]) for device in devices]
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED_DEVICE_IDS, default=defaults): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


def validated_selection(value: object, devices: list[JsonObject]) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    requested = {str(item) for item in value}
    return [str(device["deviceId"]) for device in devices if str(device["deviceId"]) in requested]
