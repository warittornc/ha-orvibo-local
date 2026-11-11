"""The home snapshot every consumer shares."""

from custom_components.orvibo_lan.devices.catalog import build_home_snapshot

MIXPAD = {"deviceId": "mixpad", "deviceType": 114, "uid": "gw"}
GATEWAYS = [{"uid": "gw", "localStaticIP": "192.0.2.10:8088"}]


def test_hidden_types_never_reach_the_catalogue():
    ir_remote = {"deviceId": "ir", "deviceType": 14, "uid": "gw"}
    light = {"deviceId": "light", "deviceType": 1, "uid": "gw"}
    home = build_home_snapshot([MIXPAD, ir_remote, light], {}, GATEWAYS, [])
    assert list(home.devices) == ["light"]
    assert home.counts.hidden_devices == 2
    assert home.devices["light"]["_orvibo_lan_capable"] is True


def test_gateway_type_given_as_text_still_maps_the_gateway():
    mixpad = {**MIXPAD, "deviceType": "114"}
    home = build_home_snapshot([mixpad], {}, GATEWAYS, [])
    assert dict(home.gateway_ips) == {"gw": "192.0.2.10"}


def test_room_name_prefers_room_id_then_state_descriptor_then_device_field():
    devices = [
        MIXPAD,
        {"deviceId": "a", "deviceType": 1, "uid": "gw", "roomId": "r1"},
        {"deviceId": "b", "deviceType": 1, "uid": "gw"},
        {"deviceId": "c", "deviceType": 1, "uid": "gw", "roomName": "Porch"},
    ]
    rooms = [{"roomId": "r1", "roomName": "Office"}, {"roomId": "r2", "roomName": "Hall"}]
    home = build_home_snapshot(devices, {}, GATEWAYS, rooms)
    assert home.room_name("a") == "Office"
    assert home.room_name("b", {"properties": {"Descriptor": {"roomId": "r2"}}}) == "Hall"
    assert home.room_name("b") is None
    assert home.room_name("c") == "Porch"
    assert home.room_name("missing") is None


def test_limited_keeps_the_first_devices_in_cloud_order():
    devices = [MIXPAD] + [{"deviceId": f"d{i}", "deviceType": 1, "uid": "gw"} for i in range(5)]
    home = build_home_snapshot(devices, {}, GATEWAYS, [])
    assert list(home.limited(2).devices) == ["d0", "d1"]
    assert home.limited(10) is home
