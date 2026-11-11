"""Orvibo LAN cover platform; wire format lives in ``devices.families.CoverFamily``."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import ATTR_POSITION, CoverDeviceClass, CoverEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..devices.families import CoverFamily
from ..devices.profiles import Platform
from .base import OrviboLanEntity, async_setup_platform, device_name


class OrviboLanCover(OrviboLanEntity, CoverEntity):
    """Orvibo curtain entity."""

    def __init__(self, coordinator, device_id, device, device_type=None):
        super().__init__(
            coordinator, device_id, device, model="Orvibo Curtain", name_prefix="Cover"
        )
        self._family = CoverFamily({**device, "deviceId": device_id}, coordinator.username)
        self._attr_unique_id = f"{DOMAIN}_cover_{device_id}"
        self._attr_name = device_name(device, device_id, "Cover")
        if self._family.shutter:
            self._attr_device_class = CoverDeviceClass.SHUTTER
            self._attr_icon = "mdi:roller-shade"
        else:
            self._attr_device_class = CoverDeviceClass.CURTAIN

    @property
    def is_closed(self) -> bool | None:
        return self._family.is_closed(self._state())

    @property
    def current_cover_position(self) -> int | None:
        return self._family.position(self._state())

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_control_device(self._device_id, self._family.open())

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_control_device(self._device_id, self._family.close())

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_control_device(self._device_id, self._family.stop())

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        payload = self._family.set_position(kwargs[ATTR_POSITION])
        await self.coordinator.async_control_device(self._device_id, payload)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    await async_setup_platform(
        hass,
        entry,
        async_add_entities,
        Platform.COVER,
        lambda coordinator, device_id, device, device_type, _state: [
            OrviboLanCover(coordinator, device_id, device, device_type)
        ],
    )
