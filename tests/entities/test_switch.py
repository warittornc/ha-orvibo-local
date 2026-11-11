"""Plugs are exposed as outlet switches that reuse the legacy on/off payloads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.orvibo_lan.auth.credentials import ProtocolDigest
from custom_components.orvibo_lan.const import DOMAIN
from custom_components.orvibo_lan.devices.capabilities import platforms_for_device
from custom_components.orvibo_lan.devices.catalog import HomeSnapshot
from custom_components.orvibo_lan.devices.control import light as light_control
from custom_components.orvibo_lan.devices.profiles import Platform
from custom_components.orvibo_lan.entities import light, switch
from custom_components.orvibo_lan.runtime.coordinator import OrviboLanCoordinator
from custom_components.orvibo_lan.runtime.lifecycle import OrviboLanRuntimeData

PLUG = {
    "deviceId": "plug",
    "deviceType": 1,
    "subDeviceType": "12",
    "uid": "gateway",
    "deviceName": "Plug",
    "_orvibo_lan_capable": True,
    "_orvibo_read_only": False,
}
LAMP = {**PLUG, "deviceId": "lamp", "subDeviceType": "2", "deviceName": "Lamp"}


def plug_context(value1: int = 0):
    coordinator = OrviboLanCoordinator(
        SimpleNamespace(), MagicMock(), "user", ProtocolDigest.from_password("password")
    )
    coordinator.load_home(
        HomeSnapshot(
            devices={"plug": dict(PLUG), "lamp": dict(LAMP)},
            statuses={
                "plug": {"online": True, "value1": value1},
                "lamp": {"online": True, "value1": 0},
            },
        )
    )
    coordinator.gateway_manager = SimpleNamespace(is_connected=lambda uid: uid == "gateway")
    coordinator.async_control_device = AsyncMock(return_value=True)
    runtime = OrviboLanRuntimeData(coordinator, MagicMock())
    entry = SimpleNamespace(entry_id="entry", options={})
    hass = SimpleNamespace(data={DOMAIN: {"entry": runtime}})
    return hass, entry, coordinator


def test_plug_moves_from_light_to_switch_platform():
    assert platforms_for_device(PLUG) == {Platform.SWITCH}
    assert platforms_for_device(LAMP) == {Platform.LIGHT}


@pytest.mark.asyncio
async def test_plug_becomes_one_outlet_switch_and_drops_its_old_light():
    hass, entry, coordinator = plug_context()
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "light.kitchen_plug_plug"
    added: list = []
    with patch.object(switch.er, "async_get", return_value=registry):
        await switch.async_setup_entry(hass, entry, added.extend)

    assert [entity._attr_unique_id for entity in added] == [f"{DOMAIN}_switch_plug"]
    assert added[0]._attr_device_class == "outlet"
    registry.async_get_entity_id.assert_called_once_with("light", DOMAIN, f"{DOMAIN}_light_plug")
    registry.async_remove.assert_called_once_with("light.kitchen_plug_plug")

    lights: list = []
    await light.async_setup_entry(hass, entry, lights.extend)
    assert [entity._attr_unique_id for entity in lights] == [f"{DOMAIN}_light_lamp"]


@pytest.mark.asyncio
async def test_switch_without_a_previous_light_removes_nothing():
    hass, entry, _ = plug_context()
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    with patch.object(switch.er, "async_get", return_value=registry):
        await switch.async_setup_entry(hass, entry, lambda entities: None)
    registry.async_remove.assert_not_called()


@pytest.mark.parametrize(("value1", "expected"), [(0, True), (1, False)])
def test_switch_reads_legacy_power_state(value1, expected):
    _, _, coordinator = plug_context(value1)
    assert switch.OrviboLanSwitch(coordinator, "plug", PLUG, 1).is_on is expected


@pytest.mark.asyncio
async def test_switch_sends_the_same_payloads_the_light_did():
    _, _, coordinator = plug_context()
    entity = switch.OrviboLanSwitch(coordinator, "plug", PLUG, 1)

    await entity.async_turn_on()
    await entity.async_turn_off()

    sent = [call.args[1] for call in coordinator.async_control_device.await_args_list]
    expected = [
        light_control.light_on("plug", "gateway", 1, "user"),
        light_control.light_off("plug", "gateway", 1, "user"),
    ]
    for payload in (*sent, *expected):
        payload.pop("serial", None)
        payload.pop("uniSerial", None)
    assert sent == expected
