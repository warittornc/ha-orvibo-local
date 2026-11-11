"""LAN admission must reject spoofed updates before state reconciliation."""

import importlib

import pytest


def admission():
    module = importlib.import_module("custom_components.orvibo_lan.state.ingestion")
    return module.admit_lan_state


@pytest.mark.parametrize(
    "payload",
    [
        {"cmd": True, "deviceId": "d"},
        {"cmd": 42, "deviceId": "d", "gatewayUid": "wrong"},
        {"cmd": 42, "deviceId": "d", "properties": []},
        {"cmd": 42, "deviceId": "d", "battery": 100},
        {"cmd": 42, "deviceId": "d", "value1": True},
        {"cmd": 42, "deviceId": "unknown"},
    ],
)
def test_rejects_untrusted_state(payload):
    assert admission()("g", payload, {"d": {"uid": "g"}}, {"d"}) is None


def test_normalizes_compatible_command_and_strips_metadata():
    payload = {"cmd": "99", "deviceID": " d ", "uid": "g", "value1": "1", "__generation": 8}
    assert admission()("g", payload, {"d": {"uid": "g"}}, {"d"}) == {"deviceId": "d", "value1": "1"}
    assert "deviceID" in payload


def test_gateway_owner_must_match_even_without_payload_uid():
    assert admission()("other", {"cmd": 42, "deviceId": "d"}, {"d": {"uid": "g"}}, {"d"}) is None
