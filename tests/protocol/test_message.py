"""One reading of gateway message routing fields, shared by connection and ingestion."""

import pytest

from custom_components.orvibo_lan.protocol.message import (
    command_of,
    device_id_of,
    gateway_uid_of,
    is_device_update,
)


@pytest.mark.parametrize(
    ("cmd", "expected"), [(42, 42), (" 42 ", 42), ("x", None), (True, None), (None, None)]
)
def test_command_of(cmd, expected):
    assert command_of({"cmd": cmd}) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"deviceId": " dev "}, "dev"),
        ({"deviceID": 12}, "12"),
        ({"device_id": "dev"}, "dev"),
        ({"deviceId": "  "}, None),
        ({"deviceId": True}, None),
        ({"device": "dev"}, None),
    ],
)
def test_device_id_of(payload, expected):
    assert device_id_of(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [({"gatewayUid": " gw "}, "gw"), ({"uid": "gw"}, "gw"), ({"uid": " "}, None), ({}, None)],
)
def test_gateway_uid_of(payload, expected):
    assert gateway_uid_of(payload) == expected


@pytest.mark.parametrize(
    ("payload", "correlated", "expected"),
    [
        ({"cmd": 42}, True, True),
        ({"cmd": 99, "deviceId": "dev"}, False, True),
        ({"cmd": 99, "deviceId": "dev"}, True, False),
        ({"cmd": 99, "deviceId": " "}, False, False),
        ({"cmd": 99}, False, False),
    ],
)
def test_is_device_update(payload, correlated, expected):
    assert is_device_update(payload, correlated=correlated) is expected
