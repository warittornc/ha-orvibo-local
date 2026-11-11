"""Orvibo LAN switch platform for plugs; wire format lives in ``PlugFamily``."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..devices.families import PlugFamily
from ..devices.profiles import Platform
from ..runtime.coordinator import OrviboLanCoordinator
from .base import OrviboLanEntity, async_setup_platform, device_name


class OrviboLanSwitch(OrviboLanEntity, SwitchEntity):
    """An Orvibo plug exposed as an outlet switch."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: dict[str, Any],
        device_type: int | None = None,
    ) -> None:
        super().__init__(coordinator, device_id, device, model="Orvibo Plug", name_prefix="Plug")
        self._family = PlugFamily({**device, "deviceId": device_id}, coordinator.username)
        self._attr_unique_id = f"{DOMAIN}_switch_{device_id}"
        self._attr_name = device_name(device, device_id, "Plug")

    @property
    def is_on(self) -> bool:
        return self._family.is_on(self._state())

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_control_device(self._device_id, self._family.turn_on())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_control_device(self._device_id, self._family.turn_off())


def _remove_superseded_light(hass: HomeAssistant, device_id: str) -> None:
    """Drop the light entity a plug had before it moved to the switch platform."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(Platform.LIGHT, DOMAIN, f"{DOMAIN}_light_{device_id}")
    if entity_id is not None:
        registry.async_remove(entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    def create(coordinator, device_id, device, device_type, _state):
        _remove_superseded_light(hass, device_id)
        return [OrviboLanSwitch(coordinator, device_id, device, device_type)]

    await async_setup_platform(hass, entry, async_add_entities, Platform.SWITCH, create)
