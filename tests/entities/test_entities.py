"""Production-path tests for Home Assistant entity adapters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.orvibo_lan.auth.credentials import ProtocolDigest
from custom_components.orvibo_lan.const import DOMAIN
from custom_components.orvibo_lan.devices.catalog import HomeSnapshot
from custom_components.orvibo_lan.entities import binary_sensor, climate, cover, fan, light, sensor
from custom_components.orvibo_lan.runtime.coordinator import OrviboLanCoordinator
from custom_components.orvibo_lan.runtime.lifecycle import OrviboLanRuntimeData

PASSWORD = ProtocolDigest.from_password("password")


def entity_context():
    coordinator = OrviboLanCoordinator(
        SimpleNamespace(),
        MagicMock(),
        "user",
        PASSWORD,
    )
    devices = {
        "light": {
            "deviceId": "light",
            "deviceType": 503,
            "uid": "gateway",
            "deviceName": "Desk light",
            "_orvibo_lan_capable": True,
            "_orvibo_read_only": False,
        },
        "cover": {
            "deviceId": "cover",
            "deviceType": 34,
            "uid": "gateway",
            "_orvibo_lan_capable": True,
            "_orvibo_read_only": False,
        },
        "fan": {
            "deviceId": "fan",
            "deviceType": 516,
            "uid": "gateway",
            "_orvibo_lan_capable": True,
            "_orvibo_read_only": False,
        },
        "climate": {
            "deviceId": "climate",
            "deviceType": 36,
            "uid": "gateway",
            "_orvibo_lan_capable": True,
            "_orvibo_read_only": False,
        },
        "environment": {
            "deviceId": "environment",
            "deviceType": 22,
            "uid": "gateway",
            "_orvibo_lan_capable": True,
            "_orvibo_read_only": False,
        },
        "door": {
            "deviceId": "door",
            "deviceType": 46,
            "uid": "gateway",
            "_orvibo_lan_capable": True,
            "_orvibo_read_only": False,
        },
    }
    states = {
        "light": {
            "online": True,
            "properties": {
                "onoff": {"status": "on"},
                "brightness": {"percent": 50},
                "colorTemp": {"value": 4000},
            },
        },
        "cover": {"online": True, "value1": 40},
        "fan": {
            "online": True,
            "properties": {
                "onoff": {"status": "on"},
                "fanSpeed": {"value": 75},
            },
        },
        "climate": {
            "online": True,
            "value1": 0,
            "value2": 3,
            "value3": 2,
            "value4": (2200 << 16) | 2150,
        },
        "environment": {
            "online": True,
            "temperature": 21.5,
            "humidity": 48,
            "battery": 87,
        },
        "door": {
            "online": True,
            "door_state": True,
            "battery": 70,
        },
    }
    coordinator.load_home(HomeSnapshot(devices=devices, statuses=states))
    coordinator.gateway_manager = SimpleNamespace(is_connected=lambda uid: uid == "gateway")
    coordinator.last_update_success = True
    coordinator.async_control_device = AsyncMock(return_value=True)
    runtime = OrviboLanRuntimeData(coordinator, MagicMock())
    entry = SimpleNamespace(entry_id="entry", options={})
    hass = SimpleNamespace(data={DOMAIN: {"entry": runtime}})
    return hass, entry, coordinator


@pytest.mark.asyncio
async def test_read_only_entities_do_not_reference_a_missing_gateway() -> None:
    coordinator = OrviboLanCoordinator(
        SimpleNamespace(),
        MagicMock(),
        "user",
        PASSWORD,
    )
    device = {
        "deviceId": "w-lock",
        "deviceType": 522,
        "uid": "wifi-lock-uid",
        "deviceName": "Door lock",
        "_orvibo_lan_capable": False,
        "_orvibo_read_only": True,
    }

    battery = sensor.OrviboLanBatterySensor(
        coordinator,
        "w-lock",
        device,
        "Door lock",
    )
    door = binary_sensor.OrviboLanPropertyDoorSensor(
        coordinator,
        "w-lock",
        device,
    )

    assert "via_device" not in battery._attr_device_info
    assert "via_device" not in door._attr_device_info

    lan_device = {**device, "_orvibo_lan_capable": True}
    lan_battery = sensor.OrviboLanBatterySensor(
        coordinator,
        "w-lock",
        lan_device,
        "Door lock",
    )
    lan_door = binary_sensor.OrviboLanPropertyDoorSensor(
        coordinator,
        "w-lock",
        lan_device,
    )
    expected_gateway = (DOMAIN, "gateway_wifi-lock-uid")
    assert lan_battery._attr_device_info["via_device"] == expected_gateway
    assert lan_door._attr_device_info["via_device"] == expected_gateway

    devices = {
        "wifi-light": {**device, "deviceId": "wifi-light", "deviceType": 503},
        "wifi-cover": {**device, "deviceId": "wifi-cover", "deviceType": 34},
        "wifi-fan": {**device, "deviceId": "wifi-fan", "deviceType": 516},
        "wifi-climate": {**device, "deviceId": "wifi-climate", "deviceType": 36},
    }
    states = {
        device_id: {"properties": {"battery_power": {"percent": 80}}} for device_id in devices
    }
    coordinator.load_home(HomeSnapshot(devices=devices, statuses=states))
    runtime = OrviboLanRuntimeData(coordinator, MagicMock())
    hass = SimpleNamespace(data={DOMAIN: {"entry": runtime}})
    entry = SimpleNamespace(entry_id="entry", options={})

    for platform in (light, cover, fan, climate):
        entities: list[object] = []
        await platform.async_setup_entry(hass, entry, entities.extend)
        assert len(entities) == 1
        assert "via_device" not in entities[0]._attr_device_info

    coordinator.load_home(
        HomeSnapshot(
            devices={
                device_id: {**item, "_orvibo_lan_capable": True}
                for device_id, item in devices.items()
            },
            statuses=states,
        )
    )
    for platform in (light, cover, fan, climate):
        entities = []
        await platform.async_setup_entry(hass, entry, entities.extend)
        assert len(entities) == 1
        assert entities[0]._attr_device_info["via_device"] == expected_gateway


@pytest.mark.asyncio
async def test_platform_entities_parse_state_and_send_commands() -> None:
    hass, entry, coordinator = entity_context()
    platform_entities: dict[str, list[object]] = {}

    for name, platform in (
        ("light", light),
        ("cover", cover),
        ("fan", fan),
        ("climate", climate),
        ("sensor", sensor),
        ("binary_sensor", binary_sensor),
    ):
        entities: list[object] = []
        await platform.async_setup_entry(hass, entry, entities.extend)
        platform_entities[name] = entities

    light_entity = platform_entities["light"][0]
    assert light_entity.available
    assert light_entity.is_on
    assert light_entity.brightness == 127
    assert light_entity.color_temp_kelvin == 4000
    await light_entity.async_turn_off()

    cover_entity = platform_entities["cover"][0]
    assert cover_entity.current_cover_position == 40
    assert cover_entity.is_closed is False
    await cover_entity.async_set_cover_position(position=75)

    fan_entity = platform_entities["fan"][0]
    assert fan_entity.is_on
    assert fan_entity.percentage == 75
    await fan_entity.async_set_percentage(33)

    climate_entity = platform_entities["climate"][0]
    assert climate_entity.hvac_mode == "cool"
    assert climate_entity.target_temperature == 22
    assert climate_entity.current_temperature == 21.5
    assert climate_entity.fan_mode == "medium"
    await climate_entity.async_set_temperature(temperature=23)

    sensor_values = {
        entity._attr_unique_id: entity.native_value
        for entity in platform_entities["sensor"]
        if entity._device_id == "environment"
    }
    assert set(sensor_values.values()) == {21.5, 48.0, 87}

    door_entity = next(
        entity for entity in platform_entities["binary_sensor"] if entity._device_id == "door"
    )
    assert door_entity.is_on is True
    sent = [
        (call.args[0], call.args[1]["order"], call.args[1].get("value1"))
        for call in coordinator.async_control_device.await_args_list
    ]
    assert sent == [
        ("light", "set property", 0),
        ("cover", "on", 75),
        ("fan", "set property", 0),
        ("climate", "temperature setting", 0),
    ]
    light_payload = coordinator.async_control_device.await_args_list[0].args[1]
    assert light_payload["properties"] == {"onoff": {"status": "off"}}
    climate_payload = coordinator.async_control_device.await_args_list[3].args[1]
    assert climate_payload["value4"] == 2300 << 16


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [light, cover, fan, climate, sensor, binary_sensor])
async def test_all_platforms_respect_empty_and_partial_selection(platform) -> None:
    hass, entry, coordinator = entity_context()
    entry.options = {"selected_device_ids": []}
    entities = []
    await platform.async_setup_entry(hass, entry, entities.extend)
    assert entities == []

    entry.options = {}
    await platform.async_setup_entry(hass, entry, entities.extend)
    assert entities
    selected = entities[0]._device_id
    original_ids = {item._attr_unique_id for item in entities if item._device_id == selected}
    entry.options = {"selected_device_ids": [selected, "missing-device"]}
    entities = []
    await platform.async_setup_entry(hass, entry, entities.extend)
    assert {item._device_id for item in entities} == {selected}
    assert {item._attr_unique_id for item in entities} == original_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [light, cover, fan, climate, sensor, binary_sensor])
async def test_shared_registry_identity_and_availability(platform) -> None:
    hass, entry, coordinator = entity_context()
    coordinator.is_device_available = MagicMock(return_value=False)
    entities = []
    await platform.async_setup_entry(hass, entry, entities.extend)
    assert entities
    for item in entities:
        info = item._attr_device_info
        assert info["identifiers"] == {(DOMAIN, f"device_{item._device_id}")}
        assert info["manufacturer"] == "ORVIBO"
        assert info["name"]
        assert info["via_device"] == (DOMAIN, "gateway_gateway")
        assert item.available is False
    coordinator.is_device_available.return_value = True
    assert all(item.available for item in entities)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("device_type", "state_key", "name"),
    [
        (26, "motion_detected", "Motion"),
        (46, "door_state", "Contact"),
        (25, "gas_detected", "Gas"),
        (27, "smoke_detected", "Smoke"),
        (54, "water_leak_detected", "Water leak"),
        (56, "emergency_state", "Emergency button"),
    ],
)
async def test_binary_sensor_types_preserve_entity_identity_and_state(device_type, state_key, name):
    hass, entry, coordinator = entity_context()
    device = {"deviceId": "sensor", "deviceType": device_type}
    coordinator.load_home(
        HomeSnapshot(devices={"sensor": device}, statuses={"sensor": {state_key: True}})
    )
    entities = []
    await binary_sensor.async_setup_entry(hass, entry, entities.extend)
    assert len(entities) == 1
    entity = entities[0]
    assert entity._attr_unique_id == f"{DOMAIN}_binary_{state_key}_sensor"
    assert entity._attr_name == name
    assert entity.is_on is True
    coordinator.load_home(
        HomeSnapshot(devices={"sensor": device}, statuses={"sensor": {state_key: False}})
    )
    assert entity.is_on is False


@pytest.mark.asyncio
async def test_unknown_binary_sensor_type_keeps_property_door_support():
    hass, entry, coordinator = entity_context()
    coordinator.load_home(
        HomeSnapshot(
            devices={"sensor": {"deviceId": "sensor", "deviceType": 999}},
            statuses={"sensor": {"properties": {"door_status": "on"}}},
        )
    )
    entities = []
    await binary_sensor.async_setup_entry(hass, entry, entities.extend)
    assert len(entities) == 1
    assert entities[0]._attr_unique_id == f"{DOMAIN}_binary_property_door_sensor"
    assert entities[0].is_on is True
