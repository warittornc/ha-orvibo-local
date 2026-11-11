"""Orvibo LAN climate platform; wire format lives in ``ClimateFamily``."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..devices.families import ClimateFamily
from ..devices.profiles import Platform
from .base import OrviboLanEntity, async_setup_platform, device_name

_LOGGER = logging.getLogger(__name__)

_HVAC_MODES = {
    "off": HVACMode.OFF,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "fan_only": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
}


class OrviboLanClimate(OrviboLanEntity, ClimateEntity):
    """Orvibo air conditioner entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
    )

    def __init__(self, coordinator, device_id, device, device_type=None):
        super().__init__(coordinator, device_id, device, model="Orvibo AC", name_prefix="AC")
        self._family = ClimateFamily({**device, "deviceId": device_id}, coordinator.username)
        self._attr_unique_id = f"{DOMAIN}_climate_{device_id}"
        self._attr_name = device_name(device, device_id, "AC")
        self._attr_hvac_modes = [_HVAC_MODES[mode] for mode in self._family.hvac_modes]
        self._attr_fan_modes = list(self._family.fan_modes)

    @property
    def hvac_mode(self) -> HVACMode:
        return _HVAC_MODES[self._family.hvac_mode(self._state())]

    @property
    def hvac_action(self) -> HVACAction:
        mode = self.hvac_mode
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        return HVACAction.COOLING if mode == HVACMode.COOL else HVACAction.IDLE

    @property
    def target_temperature(self) -> float | None:
        state = self._state()
        return self._family.target_temperature(state) if state else None

    @property
    def current_temperature(self) -> float | None:
        state = self._state()
        return self._family.current_temperature(state) if state else None

    @property
    def fan_mode(self) -> str | None:
        state = self._state()
        return self._family.fan_mode(state) if state else None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode | str) -> None:
        mode = str(hvac_mode).split(".")[-1].lower()
        await self._send(self._family.set_hvac_mode(mode, self._state()))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        await self._send(self._family.set_temperature(temperature, self._state()))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._send(self._family.set_fan_mode(fan_mode, self._state()))

    async def _send(self, payload: dict[str, Any]) -> None:
        _LOGGER.debug(
            "[AC] Sending command: order=%s, v1=%s, v2=%s",
            payload.get("order"),
            payload.get("value1"),
            payload.get("value2"),
        )
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
        Platform.CLIMATE,
        lambda coordinator, device_id, device, device_type, _state: [
            OrviboLanClimate(coordinator, device_id, device, device_type)
        ],
    )
