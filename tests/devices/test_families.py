"""Device-family adapters: one table per family, state in and payload out."""

from __future__ import annotations

import itertools

import pytest

from custom_components.orvibo_lan.devices import families
from custom_components.orvibo_lan.devices.control import _wire


@pytest.fixture(autouse=True)
def fixed_serials(monkeypatch):
    serials = itertools.count(1)
    monkeypatch.setattr(_wire, "next_serial", lambda: next(serials))


def device(device_type: int, **extra: object) -> dict[str, object]:
    return {"deviceId": "dev", "uid": "gw", "deviceType": device_type, **extra}


def command(payload: dict[str, object]) -> dict[str, object]:
    """The parts of a payload that carry intent; envelope fields are pinned elsewhere."""
    keys = ("order", "value1", "value2", "value3", "value4", "properties")
    return {key: payload[key] for key in keys if key in payload}


# ---- Lights ----


@pytest.mark.parametrize(
    ("device_type", "state", "expected"),
    [
        (1, {"value1": 0, "value2": 200, "value3": 250}, (True, 200, 4000)),
        (1, {"value1": 1, "value2": 200}, (False, None, None)),
        (1, {"value1": "garbage"}, (False, None, None)),
        (1, {"value1": 0, "value3": 100}, (True, None, None)),
        (
            503,
            {"properties": {"onoff": {"status": "on"}, "brightness": {"percent": 50},
                            "colorTemp": {"value": 4000}}},
            (True, 127, 4000),
        ),
        # 502 is ThingModel but reads colour temperature from legacy value3.
        (502, {"properties": {"onoff": {"status": "on"}}, "value3": 250}, (True, None, 4000)),
        (502, {"properties": {"onoff": {"status": "off"}}}, (False, None, None)),
    ],
)
def test_light_reads_state(device_type, state, expected):
    light = families.LightFamily(device(device_type), "user")
    assert (light.is_on(state), light.brightness(state), light.color_temp_kelvin(state)) == expected


@pytest.mark.parametrize(
    ("device_type", "intent", "expected"),
    [
        (1, {}, {"order": "on", "value1": 0, "value2": 255, "value3": 0, "value4": 0}),
        (
            503,
            {},
            {"order": "set property", "value1": 0, "value2": 0, "value3": 0, "value4": 0,
             "properties": {"onoff": {"status": "on"}}},
        ),
        (38, {"brightness": 100}, {"order": "move to level", "value1": 0, "value2": 100,
                                    "value3": 0, "value4": 0}),
        (
            502,
            {"brightness": 255},
            {"order": "set property", "value1": 0, "value2": 0, "value3": 0, "value4": 0,
             "properties": {"brightness": {"percent": 100}}},
        ),
        (
            1,
            {"kelvin": 4000},
            {"order": "fast color temperature", "value1": 0, "value2": 255, "value3": 250,
             "value4": 0},
        ),
        (
            503,
            {"brightness": 255, "kelvin": 9000},
            {"order": "set property", "value1": 0, "value2": 0, "value3": 0, "value4": 0,
             "properties": {"onoff": {"status": "on"}, "brightness": {"percent": 100},
                            "colorTemp": {"value": families.LightFamily.max_kelvin}}},
        ),
        # UNVERIFIED (see the type-102 profile note): every other 102 command is
        # legacy, but the combined power+brightness command is ThingModel.
        (
            102,
            {"brightness": 255, "kelvin": 4000},
            {"order": "set property", "value1": 0, "value2": 0, "value3": 0, "value4": 0,
             "properties": {"onoff": {"status": "on"}, "brightness": {"percent": 100}}},
        ),
        (102, {}, {"order": "on", "value1": 0, "value2": 255, "value3": 0, "value4": 0}),
    ],
)
def test_light_builds_turn_on(device_type, intent, expected):
    light = families.LightFamily(device(device_type), "user")
    assert command(light.turn_on({}, **intent)) == expected


def test_light_colour_temperature_uses_current_brightness():
    light = families.LightFamily(device(1), "user")
    payload = light.turn_on({"value1": 0, "value2": 80}, kelvin=4000)
    assert payload["value2"] == 80


def test_power_only_relay_ignores_brightness():
    light = families.LightFamily(device(102, subDeviceType="1"), "user")
    assert light.color_mode == "onoff"
    assert command(light.turn_on({}, brightness=10))["order"] == "on"
    assert light.turn_on({}, brightness=10)["groupId"] == ""
    assert command(light.turn_off())["value1"] == 1


def test_light_payload_targets_device_gateway_and_account():
    payload = families.LightFamily(device(1), "user").turn_off()
    assert (payload["deviceId"], payload["uid"], payload["userName"]) == ("dev", "gw", "user")


# ---- Plugs ----


@pytest.mark.parametrize(("value1", "on"), [(0, True), ("0", True), (1, False), ("x", False)])
def test_plug_reads_value1(value1, on):
    assert families.PlugFamily(device(1, subDeviceType="12"), "u").is_on({"value1": value1}) is on


def test_plug_commands_are_legacy_light_commands():
    plug = families.PlugFamily(device(1, subDeviceType="12"), "u")
    assert command(plug.turn_on())["order"] == "on"
    assert command(plug.turn_off())["order"] == "off"


# ---- Covers ----


@pytest.mark.parametrize(
    ("state", "position", "closed"),
    [({"value1": 40}, 40, False), ({"value1": 3}, 3, True), ({"value1": 150}, 100, False),
     ({}, None, None), ({"value1": "bad"}, None, None)],
)
def test_cover_reads_position(state, position, closed):
    cover = families.CoverFamily(device(34), "u")
    assert (cover.position(state), cover.is_closed(state)) == (position, closed)


def test_cover_class_comes_from_profile():
    assert families.CoverFamily(device(35), "u").shutter
    assert not families.CoverFamily(device(34), "u").shutter


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda c: c.open(), ("on", 100)),
        (lambda c: c.close(), ("off", 0)),
        (lambda c: c.stop(), ("stop", 0)),
        (lambda c: c.set_position(75), ("on", 75)),
        (lambda c: c.set_position(20), ("off", 20)),
    ],
)
def test_cover_commands(call, expected):
    payload = call(families.CoverFamily(device(34), "u"))
    assert (payload["order"], payload["value1"]) == expected


# ---- Fans ----


@pytest.mark.parametrize(
    ("device_type", "state", "on", "percentage"),
    [
        (516, {"properties": {"onoff": {"status": "on"}, "fanSpeed": {"value": 75}}}, True, 75),
        (516, {"value1": 50}, False, 0),
        (516, {"value1": 0}, True, 33),
        (516, {"value1": 100}, True, 100),
        (516, {"value1": 7}, True, None),
        (81, {"value2": 0}, False, 0),
        (81, {"value2": 2}, True, 66),
        (81, {"value2": "bad"}, False, None),
    ],
)
def test_fan_reads_state(device_type, state, on, percentage):
    fan = families.FanFamily(device(device_type), "u")
    assert (fan.is_on(state), fan.percentage(state)) == (on, percentage)


@pytest.mark.parametrize("device_type", [516, 81])
@pytest.mark.parametrize(
    ("call", "value1"),
    [
        (lambda f: f.turn_on(), 100),
        (lambda f: f.turn_off(), 50),
        (lambda f: f.set_percentage(0), 50),
        (lambda f: f.set_percentage(33), 0),
        (lambda f: f.set_percentage(90), 100),
    ],
)
def test_fan_commands_use_ventilation_presets(device_type, call, value1):
    # UNVERIFIED for type 81 (see its profile note): it reads value2 0-3, but
    # commands send the type-516 ventilation presets.
    payload = call(families.FanFamily(device(device_type), "u"))
    assert (payload["order"], payload["value1"]) == ("set property", value1)


# ---- Climate ----

COOLING = {"value1": 0, "value2": 3, "value3": 2, "value4": (2200 << 16) | 2150}


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (COOLING, ("cool", 22.0, 21.5, "medium")),
        ({"value1": 1}, ("off", 25.0, 25.0, "auto")),
        ({"value1": 0, "value2": 7, "value3": 9}, ("fan_only", 25.0, 25.0, "auto")),
        ({"value1": 0, "value2": "bad", "value3": "bad", "value4": "bad"},
         ("cool", 25.0, 25.0, "auto")),
    ],
)
def test_climate_reads_state(state, expected):
    ac = families.ClimateFamily(device(36), "u")
    assert (
        ac.hvac_mode(state), ac.target_temperature(state), ac.current_temperature(state),
        ac.fan_mode(state),
    ) == expected


def test_climate_commands_retain_other_settings():
    ac = families.ClimateFamily(device(36), "u")
    assert command(ac.set_temperature(23, COOLING)) == {
        "order": "temperature setting", "value1": 0, "value2": 3, "value3": 2,
        "value4": 2300 << 16,
    }
    assert command(ac.set_fan_mode("high", COOLING)) == {
        "order": "wind setting", "value1": 0, "value2": 3, "value3": 3, "value4": 2200 << 16,
    }
    assert command(ac.set_hvac_mode("heat", COOLING)) == {
        "order": "on", "value1": 0, "value2": 4, "value3": 2, "value4": 2200 << 16,
    }
    assert command(ac.set_hvac_mode("off", COOLING))["order"] == "off"
