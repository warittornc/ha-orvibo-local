"""The diagnostic runs without Home Assistant or network access in mock mode."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
from dev.probe_cloud import run, shape


@pytest.mark.asyncio
async def test_mock_replays_production_parser_without_network(monkeypatch):
    request = AsyncMock(side_effect=AssertionError("Mock mode must not use the network"))
    monkeypatch.setattr(aiohttp.ClientSession, "_request", request)
    report, status = await run(SimpleNamespace(mock=True, family_index=None))
    assert status == 0
    assert report["homes"][0]["parsed"] == {
        "devices": 2,
        "states": 1,
        "gateways": 1,
        "rooms": 0,
        "mapped_gateway_ips": 1,
        "normalized_devices": 2,
        "hidden_devices": 1,
    }
    request.assert_not_called()
    serialized = json.dumps(report)
    for secret in ("SECRET-MOCK-ACCOUNT", "mock-light", "mock-gateway", "192.0.2.10"):
        assert secret not in serialized


def test_response_summary_hides_scalar_values_and_unknown_keys():
    summary = json.dumps(
        shape(
            {
                "data": {"device": [{"deviceId": "PRIVATE-ID", "uid": "PRIVATE-UID"}]},
                "PRIVATE-KEY": {"password": "PRIVATE-PASSWORD"},
            }
        )
    )
    for secret in ("PRIVATE-ID", "PRIVATE-UID", "PRIVATE-KEY", "PRIVATE-PASSWORD"):
        assert secret not in summary
    assert "deviceId" in summary


def test_cli_runs_outside_home_assistant():
    script = Path(__file__).resolve().parents[2] / "dev" / "probe_cloud.py"
    result = subprocess.run(
        [sys.executable, str(script), "--mock"],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["host"] == "homemate.orvibo.com"
    assert report["homes"][0]["parsed"]["devices"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_lan_probe_closes_connection_and_never_exposes_credentials(rejected):
    from unittest.mock import MagicMock

    from dev.probe_cloud import probe_lan

    class RejectedError(Exception):
        status = 12

    connection = SimpleNamespace(
        connect=AsyncMock(side_effect=RejectedError() if rejected else None),
        close=AsyncMock(),
    )
    module = SimpleNamespace(
        _LOGGER=SimpleNamespace(disabled=False),
        GatewayConnection=MagicMock(return_value=connection),
        GatewayLoginRejectedError=RejectedError,
    )
    report = await probe_lan(
        module, {"private-uid": "192.168.1.165"}, "private-user", "private-pass"
    )
    expected = {"gateway_index": 0, "result": "rejected" if rejected else "accepted"}
    if rejected:
        expected["status"] = 12
    assert report == [expected]
    connection.close.assert_awaited_once()
    connection.connect.assert_awaited_once_with(
        "private-user",
        "private-pass",
        expected_uid="private-uid",
        allow_missing_uid=True,
        timeout=8,
    )
    assert "private" not in json.dumps(report)


@pytest.mark.asyncio
async def test_lan_probe_skips_public_addresses_without_connecting():
    from unittest.mock import MagicMock

    from dev.probe_cloud import probe_lan

    module = SimpleNamespace(_LOGGER=SimpleNamespace(disabled=False), GatewayConnection=MagicMock())
    report = await probe_lan(module, {"uid": "8.8.8.8"}, "account", "password")
    assert report[0]["result"] == "skipped_non_private_address"
    module.GatewayConnection.assert_not_called()
