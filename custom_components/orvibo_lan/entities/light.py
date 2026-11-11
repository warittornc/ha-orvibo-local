"""Orvibo LAN light platform; wire formats live in ``devices.families.LightFamily``."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..devices.families import LightFamily
from ..devices.profiles import Platform
from .base import OrviboLanEntity, async_setup_platform, device_name

_COLOR_MODES = {
    "color_temp": ColorMode.COLOR_TEMP,
    "brightness": ColorMode.BRIGHTNESS,
    "onoff": ColorMode.ONOFF,
}


class OrviboLanLight(OrviboLanEntity, LightEntity):
    def __init__(self, coordinator, device_id, device, device_type=None):
        super().__init__(coordinator, device_id, device, model="Orvibo Light", name_prefix="Light")
        self._family = LightFamily({**device, "deviceId": device_id}, coordinator.username)
        self._attr_unique_id = f"{DOMAIN}_light_{device_id}"
        self._attr_name = device_name(device, device_id, "Light")
        color_mode = _COLOR_MODES[self._family.color_mode]
        self._attr_supported_color_modes = {color_mode}
        self._attr_color_mode = color_mode
        if color_mode == ColorMode.COLOR_TEMP:
            self._attr_min_color_temp_kelvin = self._family.min_kelvin
            self._attr_max_color_temp_kelvin = self._family.max_kelvin

    @property
    def is_on(self) -> bool:
        return self._family.is_on(self._state())

    @property
    def brightness(self) -> int | None:
        return self._family.brightness(self._state())

    @property
    def color_temp_kelvin(self) -> int | None:
        return self._family.color_temp_kelvin(self._state())

    @property
    def color_temp(self) -> int | None:
        """Return mireds for compatibility with older HA versions."""
        kelvin = self.color_temp_kelvin
        return 1000000 // kelvin if kelvin else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        kelvin = kwargs.get("color_temp_kelvin")
        mired = kwargs.get("color_temp")
        if kelvin is None and mired is not None and mired > 0:
            kelvin = 1000000 // mired
        payload = self._family.turn_on(
            self._state(), brightness=kwargs.get("brightness"), kelvin=kelvin
        )
        await self.coordinator.async_control_device(self._device_id, payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_control_device(self._device_id, self._family.turn_off())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    await async_setup_platform(
        hass,
        entry,
        async_add_entities,
        Platform.LIGHT,
        lambda coordinator, device_id, device, device_type, _state: [
            OrviboLanLight(coordinator, device_id, device, device_type)
        ],
    )
