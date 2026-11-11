"""Read cloud discovery responses and replay them through the production parser.

Run with uv run --locked python dev/probe_cloud.py --mock for an offline demo.
No device-control commands are sent. Raw responses remain in memory only.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib
import ipaddress
import json
import sys
import types
from collections.abc import Mapping
from pathlib import Path

# Only known protocol field names are emitted; account IDs can also be mapping keys.
FIELDS = frozenset(
    {
        "code",
        "status",
        "data",
        "message",
        "account",
        "userGatewayBind",
        "familyInfo",
        "device",
        "devices",
        "deviceList",
        "subDevice",
        "subDevices",
        "subDeviceList",
        "deviceStatus",
        "deviceStatuses",
        "gateway",
        "gateways",
        "room",
        "rooms",
        "deviceId",
        "deviceID",
        "deviceType",
        "subDeviceType",
        "statusType",
        "uid",
        "deviceName",
        "model",
        "roomId",
        "familyId",
        "localStaticIP",
        "ip",
        "delFlag",
        "properties",
        "onoff",
        "brightness",
        "colorTemp",
        "battery_power",
        "door_status",
        "value",
        "percent",
        "power",
        "value1",
        "value2",
        "value3",
        "value4",
        "pageIndex",
        "pageCount",
        "total",
        "hasMore",
        "lastUpdateTime",
    }
)


def load_modules():
    """Load the pure protocol modules without executing Home Assistant's entry point."""
    name = "_orvibo_cloud_probe"
    package = types.ModuleType(name)
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/orvibo_lan")]
    sys.modules[name] = package
    return (
        importlib.import_module(f"{name}.cloud.client"),
        importlib.import_module(f"{name}.devices.catalog"),
    )


def shape(value: object, depth: int = 0) -> object:
    """Expose known schema fields and list counts, never scalar values or unknown keys."""
    if depth >= 6:
        return {"type": type(value).__name__}
    if isinstance(value, Mapping):
        return {
            "type": "object",
            "fields": {key: shape(item, depth + 1) for key, item in value.items() if key in FIELDS},
            "other_field_count": sum(key not in FIELDS for key in value),
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "count": len(value),
            "sample_shapes": [shape(item, depth + 1) for item in value[:2]],
        }
    return {"type": type(value).__name__}


def mock_payloads():
    """Synthetic account-only response followed by device-level tables."""
    return {
        0: {
            "code": 0,
            "data": {
                "gateway": [{"uid": "mock-gateway", "localStaticIP": "192.0.2.10"}],
                "account": [{"userName": "SECRET-MOCK-ACCOUNT"}],
            },
        },
        1: {
            "code": 0,
            "data": {
                "device": [
                    {"deviceId": "mock-hub", "deviceType": 114, "uid": "mock-gateway"},
                    {"deviceId": "mock-light", "deviceType": 1, "uid": "mock-gateway"},
                ],
                "deviceStatus": [{"deviceId": "mock-light", "value1": 0}],
            },
        },
    }


async def probe_lan(gateway_module, gateway_ips, username, digest):
    """Test one Hello/Login per discovered private gateway; never send controls."""
    gateway_module._LOGGER.disabled = True
    results = []
    for index, (uid, host) in enumerate(gateway_ips.items()):
        result = {"gateway_index": index}
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is None or not address.is_private or address.is_loopback or address.is_multicast:
            results.append({**result, "result": "skipped_non_private_address"})
            continue
        connection = gateway_module.GatewayConnection(host)
        try:
            await connection.connect(
                username, digest, expected_uid=uid, allow_missing_uid=True, timeout=8
            )
            result["result"] = "accepted"
        except gateway_module.GatewayLoginRejectedError as error:
            result["result"] = "rejected"
            if type(getattr(error, "status", None)) is int:
                result["status"] = error.status
        except Exception as error:
            result["result"] = "inconclusive"
            result["error_type"] = type(error).__name__
        finally:
            await connection.close()
        results.append(result)
    return results


async def run(args):
    cloud, catalog = load_modules()
    # This namespace is isolated from the running integration and its endpoint setting.
    cloud._LOGGER.disabled = True
    import aiohttp

    report = {"mode": "mock" if args.mock else "live", "host": cloud.HTTPS_HOST, "homes": []}
    if args.mock:
        username = password = ""
    else:
        username = getpass.getpass("Orvibo account (hidden): ")
        password = getpass.getpass("Orvibo password: ")
        if not username or not password:
            return {**report, "error": "Account and password are required"}, 1
    credentials = importlib.import_module("_orvibo_cloud_probe.auth.credentials")
    digest = credentials.ProtocolDigest.from_password(password)
    del password

    async with aiohttp.ClientSession() as session:
        client = cloud.CloudClient(session, username, digest)
        if not args.mock:
            try:
                await client.login()
            except cloud.CloudClientError as error:
                return {**report, "login_error": type(error).__name__}, 1
        families = [None] if args.mock else client.family_list
        report["home_count"] = len(families)
        if args.family_index is not None:
            if not 0 <= args.family_index < len(families):
                return {**report, "error": "Home index is out of range"}, 1
            indices = [args.family_index]
        else:
            indices = range(len(families))

        for index in indices:
            if not args.mock:
                client.family_id = families[index]["familyId"]
            captured = mock_payloads() if args.mock else {}
            home = {"index": index, "scopes": {}}
            if not args.mock:
                original_request = client._request_json

                async def capture(method, path, operation, **kwargs):
                    payload = await original_request(method, path, operation, **kwargs)
                    if path == "/v2/cmd/app/readtable":
                        captured[kwargs["json_body"]["deviceFlag"]] = payload
                    return payload

                client._request_json = capture
                try:
                    for flag in (0, 1):
                        try:
                            await client._request_readtable(flag)
                        except cloud.CloudClientError as error:
                            home["scopes"][str(flag)] = {"error": type(error).__name__}
                finally:
                    client._request_json = original_request
            for flag, payload in captured.items():
                home["scopes"].setdefault(str(flag), {})["response_shape"] = shape(payload)

            class ReplayClient(cloud.CloudClient):
                async def _request_readtable(self, device_flag):
                    if device_flag not in captured:
                        raise cloud.CloudSchemaError("Response not captured")
                    payload = captured[device_flag]
                    self._raise_for_api_error(payload, "device list", require_code=True)
                    return self._require_mapping(payload.get("data"), "device list data")

            replay = ReplayClient(session, "", digest)
            try:
                devices, states, gateways, rooms = await replay._fetch_readtable()
                snapshot = catalog.build_home_snapshot(devices, states, gateways, rooms)
                gateway_ips = dict(snapshot.gateway_ips)
                if getattr(args, "probe_lan", False):
                    if args.mock:
                        home["lan_login"] = [{"result": "skipped_mock_mode"}]
                    else:
                        gateway_module = importlib.import_module(
                            "_orvibo_cloud_probe.gateway.connection"
                        )
                        home["lan_login"] = await probe_lan(
                            gateway_module, gateway_ips, username, digest
                        )
                home["parsed"] = {
                    "devices": len(devices),
                    "states": len(states),
                    "gateways": len(gateways),
                    "rooms": len(rooms),
                    "mapped_gateway_ips": len(gateway_ips),
                    "normalized_devices": snapshot.counts.normalized_devices,
                    "hidden_devices": snapshot.counts.hidden_devices,
                }
            except cloud.CloudClientError as error:
                home["parser_error"] = type(error).__name__
            report["homes"].append(home)
    successful = bool(report["homes"]) and all(
        home.get("parsed", {}).get("devices", 0) > 0
        and (
            not getattr(args, "probe_lan", False)
            or args.mock
            or (
                bool(home.get("lan_login"))
                and all(result["result"] == "accepted" for result in home["lan_login"])
            )
        )
        for home in report["homes"]
    )
    return report, 0 if successful else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", help="Use synthetic responses; no network")
    parser.add_argument("--family-index", type=int, help="Probe one home by zero-based index")
    parser.add_argument(
        "--probe-lan",
        action="store_true",
        help="Also test Hello/Login with the same credentials against discovered private gateways",
    )
    args = parser.parse_args()
    try:
        report, status = asyncio.run(run(args))
    except (EOFError, KeyboardInterrupt):
        print("Probe cancelled.", file=sys.stderr)
        return 1
    except Exception as error:
        # Exception messages/tracebacks can contain request URLs and credentials.
        report, status = {"error": type(error).__name__}, 1
    print(json.dumps(report, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
