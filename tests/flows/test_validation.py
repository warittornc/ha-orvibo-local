"""Shared validation distinguishes authentication rejection from reachability."""

import pytest

from custom_components.orvibo_lan.cloud.exceptions import (
    CloudAuthenticationError,
    CloudTransportError,
)
from custom_components.orvibo_lan.devices.catalog import build_home_snapshot
from custom_components.orvibo_lan.flows import validation
from custom_components.orvibo_lan.gateway import connection
from custom_components.orvibo_lan.gateway.exceptions import GatewayLoginRejectedError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,expected",
    [
        (None, None),
        ("reject", "gateway_auth_failed"),
        ("timeout", None),
        ("cloud", "auth_failed"),
        ("discovery", "cannot_connect"),
    ],
)
async def test_account_validation_orders_cloud_discovery_and_lan(monkeypatch, failure, expected):
    events = []

    class Account:
        family_list = []

        async def login(self):
            events.append("login")
            if failure == "cloud":
                raise CloudAuthenticationError("rejected")

        async def fetch_home(self):
            events.append("discovery")
            if failure == "discovery":
                raise CloudTransportError("offline")
            return build_home_snapshot(
                [
                    {"deviceId": "mixpad", "deviceType": 114, "uid": "g"},
                    {"deviceId": "d", "deviceType": 1, "uid": "g"},
                ],
                {},
                [{"uid": "g", "localStaticIP": "192.168.1.2"}],
                [],
            )

    class Gateway:
        def __init__(self, host):
            assert host == "192.168.1.2"

        async def connect(self, username, digest, **kwargs):
            assert (username, digest, kwargs) == (
                "account",
                "digest",
                {"expected_uid": "g", "allow_missing_uid": True},
            )
            events.append("lan")
            if failure == "reject":
                raise GatewayLoginRejectedError("rejected", status=12)
            if failure == "timeout":
                raise TimeoutError()

        async def close(self):
            events.append("close")

    def make_client(session, username, digest, family_id, **kwargs):
        assert family_id == "family"
        assert kwargs == {}
        return Account()

    monkeypatch.setattr(validation, "CloudClient", make_client)
    monkeypatch.setattr(connection, "GatewayConnection", Gateway)
    result = await validation.validate_account(object(), "account", "digest", "family")
    assert result.error == expected
    if failure == "cloud":
        assert events == ["login"]
    elif failure == "discovery":
        assert events == ["login", "discovery"]
    else:
        assert events == ["login", "discovery", "lan", "close"]
        assert result.devices[0]["deviceId"] == "d"


@pytest.mark.asyncio
async def test_no_gateway_does_not_prevent_cloud_only_discovery():
    assert await validation.probe_gateway_credentials(
        "account", "digest", {}
    )
