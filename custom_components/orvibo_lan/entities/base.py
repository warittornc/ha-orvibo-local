"""Shared Home Assistant entity behavior for Orvibo devices."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..devices.identity import device_registry_info
from ..devices.profiles import Platform
from ..devices.selection import platform_devices
from ..runtime.coordinator import OrviboLanCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.entity import Entity

State = Mapping[str, Any]
EntityFactory = Callable[
    [OrviboLanCoordinator, str, Mapping[str, Any], int, State],
    Iterable["Entity"],
]


def device_name(device: Mapping[str, Any], device_id: str, prefix: str = "Sensor") -> str:
    """Return the device label with a stable fallback for missing or empty names."""
    value = device.get("deviceName")
    return str(value) if value not in (None, "") else f"{prefix} {device_id[:8]}"


async def async_setup_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: Platform,
    factory: EntityFactory,
) -> None:
    """Create entities for every selected device whose profile supports ``platform``."""
    from ..runtime.lifecycle import get_runtime_data

    coordinator = get_runtime_data(hass, entry).coordinator
    entities: list[Entity] = []
    for device_id, device, state in platform_devices(
        entry.options, coordinator.devices, coordinator.get_device_state, platform
    ):
        entities.extend(
            factory(coordinator, device_id, device, coordinator.device_type(device_id), state)
        )
    if entities:
        async_add_entities(entities)


class OrviboLanEntity(CoordinatorEntity[OrviboLanCoordinator]):
    """Apply transport-aware availability consistently across platforms."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OrviboLanCoordinator,
        device_id: str,
        device: Mapping[str, Any],
        *,
        model: str,
        name_prefix: str = "Sensor",
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device = device
        self._attr_device_info = device_registry_info(
            device_id, device, model=model, name_prefix=name_prefix
        )

    @property
    def available(self) -> bool:
        return self.coordinator.is_device_available(self._device_id)

    def _state(self) -> State:
        """Current merged state; empty when the device has none."""
        return self.coordinator.get_device_state(self._device_id) or {}
