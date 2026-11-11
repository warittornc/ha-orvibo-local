"""ORVIBO LAN sensor platform."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..devices.capabilities import (
    battery_percentage,
    measurement_value,
    percentage_value,
    property_value,
    state_properties,
)
from ..devices.profiles import Platform, profile_for
from ..runtime.coordinator import OrviboLanCoordinator
from .base import OrviboLanEntity, async_setup_platform, device_name

Device: TypeAlias = Mapping[str, object]


class OrviboLanBatterySensor(OrviboLanEntity, SensorEntity):
    """Generic battery sensor."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: Device,
        model: str,
        unique_suffix: str = "battery",
    ) -> None:
        super().__init__(coordinator, device_id, device, model=model)
        self._attr_unique_id = f"{DOMAIN}_{unique_suffix}_{device_id}"
        self._attr_name = "Battery"

    @property
    def native_value(self) -> int | None:
        return battery_percentage(self.coordinator.get_device_state(self._device_id) or {})


class OrviboLanTemperatureSensor(OrviboLanEntity, SensorEntity):
    """Temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device_id, device, model="Orvibo Temp/Humidity Sensor")
        self._attr_unique_id = f"{DOMAIN}_temperature_{device_id}"
        self._attr_name = f"{device_name(device, device_id)} Temperature"

    @property
    def native_value(self) -> float | None:
        state = self.coordinator.get_device_state(self._device_id)
        return measurement_value(state, "temperature", "value1") if state else None


class OrviboLanHumiditySensor(OrviboLanEntity, SensorEntity):
    """Humidity sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device_id, device, model="Orvibo Temp/Humidity Sensor")
        self._attr_unique_id = f"{DOMAIN}_humidity_{device_id}"
        self._attr_name = f"{device_name(device, device_id)} Humidity"

    @property
    def native_value(self) -> float | None:
        state = self.coordinator.get_device_state(self._device_id)
        if not state:
            return None
        value = measurement_value(state, "humidity", "value2")
        if value is None or value < 0 or value > 100:
            return None
        return value


class OrviboLanDryBatterySensor(OrviboLanBatterySensor):
    """Door lock dry-cell battery sensor."""

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: Device,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device,
            model="Orvibo Door Lock",
            unique_suffix="dry_battery",
        )
        self._attr_name = "Dry-cell battery"

    @property
    def native_value(self) -> int | None:
        state = self.coordinator.get_device_state(self._device_id)
        if not state:
            return None
        value = state.get("dry_battery_level")
        return battery_percentage(state) if value is None else percentage_value(value)


class OrviboLanLithiumBatterySensor(OrviboLanBatterySensor):
    """Door lock lithium battery sensor."""

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: Device,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device,
            model="Orvibo Door Lock",
            unique_suffix="lithium_battery",
        )
        self._attr_name = "Lithium battery"

    @property
    def native_value(self) -> int | None:
        state = self.coordinator.get_device_state(self._device_id)
        if not state:
            return None
        value = state.get("lithium_battery_level")
        return battery_percentage(state) if value is None else percentage_value(value)


# Battery sensor identity for each flag-reading sensor family, keyed by its state key.
_FLAG_BATTERIES: dict[str, tuple[str, str]] = {
    "gas_detected": ("Orvibo Gas Sensor", "gas_battery"),
    "motion_detected": ("Orvibo Motion Sensor", "motion_battery"),
    "smoke_detected": ("Orvibo Smoke Sensor", "smoke_battery"),
    "door_state": ("Orvibo Door/Window Sensor", "door_battery"),
    "water_leak_detected": ("Orvibo Water Leak Sensor", "water_battery"),
    "emergency_state": ("Orvibo Emergency Button", "emergency_battery"),
}
_BATTERY_CELLS = {
    "dry": OrviboLanDryBatterySensor,
    "lithium": OrviboLanLithiumBatterySensor,
}
_ENVIRONMENT_MODEL = "Orvibo Temp/Humidity Sensor"


def _legacy_suffix(suffix: str, device_id: str) -> str:
    """Unique-ID suffix for profile batteries.

    These IDs historically embed the device id twice (``..._<id>_<id>``). Changing
    them needs an entity-registry migration, so they stay as they are.
    """
    return f"{suffix}_{device_id}"


def sensors_for_device(
    coordinator: OrviboLanCoordinator,
    device_id: str,
    device: Device,
    device_type: int,
    state: Mapping[str, object],
) -> list[SensorEntity]:
    """Return the sensor entities a device's profile and current state support."""
    profile = profile_for(device_type)
    entities: list[SensorEntity] = []
    number_keys = {r.state_key for r in profile.readings if r.kind == "number"}

    if number_keys:
        if "temperature" in number_keys:
            entities.append(OrviboLanTemperatureSensor(coordinator, device_id, device))
        if "humidity" in number_keys:
            entities.append(OrviboLanHumiditySensor(coordinator, device_id, device))
        entities.append(
            OrviboLanBatterySensor(
                coordinator,
                device_id,
                device,
                _ENVIRONMENT_MODEL,
                _legacy_suffix("th_battery", device_id),
            )
        )
    for reading in profile.readings:
        if reading.kind == "flag" and reading.state_key in _FLAG_BATTERIES:
            model, suffix = _FLAG_BATTERIES[reading.state_key]
            entities.append(
                OrviboLanBatterySensor(
                    coordinator, device_id, device, model, _legacy_suffix(suffix, device_id)
                )
            )
    for cell in profile.battery_cells:
        entities.append(_BATTERY_CELLS[cell](coordinator, device_id, device))

    if profile.property_measurements:
        properties = state_properties(state)
        if property_value(properties, "temperature") is not None:
            entities.append(OrviboLanTemperatureSensor(coordinator, device_id, device))
        if property_value(properties, "humidity") is not None:
            entities.append(OrviboLanHumiditySensor(coordinator, device_id, device))

    has_profile_battery = bool(number_keys or profile.battery_cells) or any(
        isinstance(entity, OrviboLanBatterySensor) for entity in entities
    )
    if not has_profile_battery and battery_percentage(state) is not None:
        model_value = device.get("model")
        model = str(model_value) if model_value not in (None, "") else "Orvibo Property Device"
        entities.append(
            OrviboLanBatterySensor(coordinator, device_id, device, model, "property_battery")
        )
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for selected devices."""
    await async_setup_platform(
        hass, entry, async_add_entities, Platform.SENSOR, sensors_for_device
    )
