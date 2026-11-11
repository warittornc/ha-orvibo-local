"""Orvibo LAN binary sensor platform.

Supported device types:
- 26: Motion sensor -> motion detection
- 46: Contact sensor -> contact state
- 25: Gas sensor -> gas detection
- 27: Smoke sensor -> smoke detection
- 54: Water leak sensor -> water detection
- 56: Emergency button -> button state
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..devices.capabilities import PROPERTY_DOOR_STATUS, state_properties
from ..devices.profiles import Platform, profile_for
from ..runtime.coordinator import OrviboLanCoordinator
from .base import OrviboLanEntity, async_setup_platform


class OrviboLanBinarySensorBase(OrviboLanEntity, BinarySensorEntity):
    """Base binary sensor entity."""

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: dict,
        state_key: str,
        device_class: BinarySensorDeviceClass,
        name: str,
        icon: str,
        model: str,
    ) -> None:
        super().__init__(coordinator, device_id, device, model=model)
        self._state_key = state_key
        self._attr_unique_id = f"{DOMAIN}_binary_{state_key}_{device_id}"
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def is_on(self) -> Optional[bool]:
        state = self.coordinator.get_device_state(self._device_id)
        return state.get(self._state_key, False) if state else False


class OrviboLanPropertyDoorSensor(OrviboLanBinarySensorBase):
    """Door state exposed through a ThingModel/cloud property."""

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: dict,
    ) -> None:
        super().__init__(
            coordinator,
            device_id,
            device,
            state_key="property_door_open",
            device_class=BinarySensorDeviceClass.DOOR,
            name="Door state",
            icon="mdi:door",
            model=device.get("model") or "ORVIBO Property Device",
        )
        self._attr_unique_id = f"{DOMAIN}_binary_property_door_{device_id}"

    @property
    def is_on(self) -> Optional[bool]:
        # Derived once by state.sensors from the door_status property.
        value = self._state().get("property_door_open")
        return value if isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class FlagDescription:
    """Home Assistant presentation of one profile flag reading."""

    device_class: BinarySensorDeviceClass
    entity_name: str
    icon: str
    model: str


# Keyed by the profile reading's state key, so device types live only in profiles.py.
FLAG_DESCRIPTIONS: dict[str, FlagDescription] = {
    "motion_detected": FlagDescription(
        BinarySensorDeviceClass.MOTION, "Motion", "mdi:motion-sensor", "Motion Sensor"
    ),
    "door_state": FlagDescription(
        BinarySensorDeviceClass.DOOR, "Contact", "mdi:door-open", "Door Window Sensor"
    ),
    "gas_detected": FlagDescription(
        BinarySensorDeviceClass.GAS, "Gas", "mdi:gas-cylinder", "Gas Sensor"
    ),
    "smoke_detected": FlagDescription(
        BinarySensorDeviceClass.SMOKE, "Smoke", "mdi:smoke-detector", "Smoke Sensor"
    ),
    "water_leak_detected": FlagDescription(
        BinarySensorDeviceClass.MOISTURE, "Water leak", "mdi:water", "Water Leak Sensor"
    ),
    "emergency_state": FlagDescription(
        BinarySensorDeviceClass.PROBLEM,
        "Emergency button",
        "mdi:alert-octagon",
        "Emergency Button",
    ),
}


def binary_sensors_for_device(
    coordinator: OrviboLanCoordinator,
    device_id: str,
    device: Mapping[str, Any],
    device_type: int,
    state: Mapping[str, Any],
) -> list[OrviboLanBinarySensorBase]:
    """Return one entity per profile flag reading, plus a property door sensor."""
    entities: list[OrviboLanBinarySensorBase] = []
    flag_keys = set()
    for reading in profile_for(device_type).readings:
        description = FLAG_DESCRIPTIONS.get(reading.state_key)
        if reading.kind != "flag" or description is None:
            continue
        flag_keys.add(reading.state_key)
        entities.append(
            OrviboLanBinarySensorBase(
                coordinator,
                device_id,
                dict(device),
                state_key=reading.state_key,
                device_class=description.device_class,
                name=description.entity_name,
                icon=description.icon,
                model=description.model,
            )
        )
    if PROPERTY_DOOR_STATUS in state_properties(state) and "door_state" not in flag_keys:
        entities.append(OrviboLanPropertyDoorSensor(coordinator, device_id, dict(device)))
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    await async_setup_platform(
        hass, entry, async_add_entities, Platform.BINARY_SENSOR, binary_sensors_for_device
    )
