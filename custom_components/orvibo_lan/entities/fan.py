"""Orvibo LAN fan platform; wire formats live in ``devices.families.FanFamily``."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..devices.families import FanFamily
from ..devices.profiles import Platform
from .base import OrviboLanEntity, async_setup_platform, device_name


class OrviboLanFan(OrviboLanEntity, FanEntity):
    """Orvibo ventilation entity."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = 4  # low/medium/high/auto

    def __init__(self, coordinator, device_id, device, device_type=None):
        super().__init__(coordinator, device_id, device, model="Orvibo Fan", name_prefix="Fan")
        self._family = FanFamily({**device, "deviceId": device_id}, coordinator.username)
        self._attr_unique_id = f"{DOMAIN}_fan_{device_id}"
        self._attr_name = device_name(device, device_id, "Fan")

    @property
    def is_on(self) -> bool:
        return self._family.is_on(self._state())

    @property
    def percentage(self) -> int | None:
        state = self._state()
        return self._family.percentage(state) if state else None

    async def async_turn_on(
        self,
        speed: str | None = None,
        percentage: int | None = None,
        **kwargs: Any,
    ) -> None:
        if percentage is not None:
            await self.async_set_percentage(percentage)
            return
        await self.coordinator.async_control_device(self._device_id, self._family.turn_on())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_control_device(self._device_id, self._family.turn_off())

    async def async_set_percentage(self, percentage: int) -> None:
        payload = self._family.set_percentage(percentage)
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
        Platform.FAN,
        lambda coordinator, device_id, device, device_type, _state: [
            OrviboLanFan(coordinator, device_id, device, device_type)
        ],
    )
