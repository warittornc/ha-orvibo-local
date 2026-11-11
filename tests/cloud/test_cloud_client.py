"""Unit tests for the externally-sessioned Orvibo cloud client."""

from __future__ import annotations

import asyncio
import sys
import traceback
import types
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from unittest.mock import patch

try:
    import aiohttp  # type: ignore[import-not-found]
except ImportError:
    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        """Fake aiohttp client error."""

    @dataclass(frozen=True)
    class ClientTimeout:
        """Fake aiohttp timeout value."""

        total: float | None = None
        connect: float | None = None
        sock_read: float | None = None

    aiohttp.ClientError = ClientError
    aiohttp.ClientTimeout = ClientTimeout
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

from custom_components.orvibo_lan.auth.credentials import ProtocolDigest
from custom_components.orvibo_lan.cloud import client as cloud_client
from custom_components.orvibo_lan.devices.catalog import build_home_snapshot

CloudApiError = cloud_client.CloudApiError
CloudClient = cloud_client.CloudClient
CloudHttpError = cloud_client.CloudHttpError
CloudJsonError = cloud_client.CloudJsonError
CloudSchemaError = cloud_client.CloudSchemaError
CloudTransportError = cloud_client.CloudTransportError
PASSWORD = ProtocolDigest.from_password("password")


class FakeResponse:
    def __init__(
        self,
        payload: object = None,
        *,
        status: int = 200,
        json_error: Exception | None = None,
    ) -> None:
        self.status = status
        self._payload = payload
        self._json_error = json_error
        self.released = False

    async def json(self, *, content_type: object = None) -> object:
        del content_type
        if self._json_error is not None:
            raise self._json_error
        return self._payload

    def release(self) -> None:
        self.released = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def get(self, url: str, **kwargs: object) -> FakeResponse:
        return self._request("GET", url, kwargs)

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        return self._request("POST", url, kwargs)

    def _request(
        self,
        method: str,
        url: str,
        kwargs: dict[str, object],
    ) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def oauth_payload() -> dict[str, object]:
    return {
        "status": 0,
        "data": {"access_token": "secret-token", "user_id": "user-1"},
    }


class CloudClientLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_oauth_uses_form_post(self) -> None:
        session = FakeSession(
            [
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": {"familyInfo": []}}),
            ]
        )
        client = CloudClient(session, "account@example.com", PASSWORD)
        await client.login()
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.startswith("https://"))
        self.assertTrue(url.endswith("/getOauthToken"))
        self.assertNotIn("account@example.com", url)
        self.assertEqual(kwargs["allow_redirects"], False)
        self.assertIsInstance(kwargs["timeout"], aiohttp.ClientTimeout)
        self.assertNotIn("params", kwargs)
        data = kwargs["data"]
        self.assertIsInstance(data, Mapping)
        self.assertEqual(data["userName"], "account@example.com")
        self.assertEqual(len(data["password"]), 32)

    async def test_explicit_get_oauth_retains_compatibility(self) -> None:
        session = FakeSession(
            [
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": []}),
            ]
        )
        client = CloudClient(session, "account", PASSWORD, oauth_method="GET")
        await client.login()
        method, _, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertIn("params", kwargs)
        self.assertNotIn("data", kwargs)

    async def test_default_oauth_retries_get_when_post_response_is_incompatible(self) -> None:
        session = FakeSession(
            [
                FakeResponse({"status": 0, "data": None}),
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": {"familyInfo": []}}),
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": {"familyInfo": []}}),
            ]
        )
        client = CloudClient(session, "account", PASSWORD)

        await client.login()

        self.assertEqual([call[0] for call in session.calls], ["POST", "GET", "POST"])
        self.assertEqual(client.access_token, "secret-token")
        self.assertEqual(client.user_id, "user-1")

        await client.login()

        self.assertEqual(
            [call[0] for call in session.calls],
            ["POST", "GET", "POST", "GET", "POST"],
        )

    async def test_default_oauth_retries_get_for_unsupported_form_post(self) -> None:
        session = FakeSession(
            [
                FakeResponse({}, status=415),
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": {"familyInfo": []}}),
            ]
        )
        client = CloudClient(session, "account", PASSWORD)

        await client.login()

        self.assertEqual([call[0] for call in session.calls], ["POST", "GET", "POST"])

    async def test_login_parses_families_and_selects_first(self) -> None:
        family = {"familyId": "family-1", "familyName": "Home"}
        session = FakeSession(
            [
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": {"familyInfo": [family]}}),
            ]
        )
        client = CloudClient(session, "account", PASSWORD)
        await client.login()
        self.assertEqual(client.family_list, [family])
        self.assertEqual(client.family_id, "family-1")
        self.assertEqual(client.family_name, "Home")

    async def test_login_rejects_invalid_credentials(self) -> None:
        client = CloudClient(
            FakeSession([FakeResponse({"status": 1, "code": 1})]),
            "a",
            PASSWORD,
        )
        with self.assertRaises(cloud_client.CloudAuthenticationError):
            await client.login()


class CloudClientErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_error_has_status_and_releases_response(self) -> None:
        response = FakeResponse({}, status=503)
        client = CloudClient(FakeSession([response]), "a", PASSWORD)
        with self.assertRaises(CloudHttpError) as raised:
            await client.login()
        self.assertEqual(raised.exception.status, 503)
        self.assertTrue(response.released)

    async def test_invalid_json_raises_explicit_error(self) -> None:
        responses = [
            FakeResponse(json_error=ValueError("bad post")),
            FakeResponse(json_error=ValueError("bad get")),
        ]
        session = FakeSession(responses)
        client = CloudClient(session, "a", PASSWORD)
        with self.assertRaises(CloudJsonError):
            await client.login()
        self.assertTrue(all(response.released for response in responses))
        self.assertEqual([call[0] for call in session.calls], ["POST", "GET"])

    async def test_non_object_json_raises_schema_error(self) -> None:
        responses = [FakeResponse([]), FakeResponse([])]
        session = FakeSession(responses)
        client = CloudClient(session, "a", PASSWORD)
        with self.assertRaises(CloudSchemaError):
            await client.login()
        self.assertTrue(all(response.released for response in responses))
        self.assertEqual([call[0] for call in session.calls], ["POST", "GET"])

    async def test_readtable_api_error_is_explicit(self) -> None:
        client = CloudClient(
            FakeSession(
                [
                    FakeResponse({"code": 7}),
                    FakeResponse(oauth_payload()),
                    FakeResponse({"code": 0, "data": {"familyInfo": []}}),
                    FakeResponse({"code": 7}),
                ]
            ),
            "a",
            PASSWORD,
        )
        client.access_token = "token"
        client.user_id = "user"
        with self.assertRaises(CloudApiError):
            await client.fetch_readtable()

    async def test_timeout_is_transport_error_without_secret_leakage(self) -> None:
        digest = ProtocolDigest.from_password("private-password")
        secrets = (
            "private-user",
            "private-password",
            "secret-token",
            "https://",
            "cloud.invalid",
            digest.value,
        )
        session = FakeSession(
            [
                asyncio.TimeoutError("private-password at https://cloud.invalid"),
                asyncio.TimeoutError("secret-token at https://cloud.invalid"),
            ]
        )
        client = CloudClient(session, secrets[0], digest)
        client.access_token = secrets[2]

        with self.assertRaises(CloudTransportError) as raised:
            await client.login()

        self.assertEqual([call[0] for call in session.calls], ["POST"])

        rendered_error = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertEqual(str(raised.exception), "OAuth login request failed")
        for secret in secrets:
            self.assertNotIn(secret, rendered_error)

        with patch.object(cloud_client._LOGGER, "debug") as debug:
            with self.assertRaises(CloudTransportError):
                await client.login()
        self.assertEqual([call[0] for call in session.calls], ["POST", "POST"])
        rendered_log = " ".join(str(value) for call in debug.call_args_list for value in call.args)
        for secret in secrets:
            self.assertNotIn(secret, rendered_log)


class CloudClientDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_readtable_reauthenticates_once_after_api_rejection(self) -> None:
        session = FakeSession(
            [
                FakeResponse({"code": 7}),
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": {"familyInfo": []}}),
                FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "device": [],
                            "deviceStatus": [],
                            "gateway": [],
                            "room": [],
                        },
                    }
                ),
            ]
        )
        client = CloudClient(session, "a", PASSWORD, family_id="family-1")
        client.access_token = "expired"
        client.user_id = "user"

        devices, *_ = await client.fetch_readtable()

        self.assertEqual(devices, [])
        self.assertEqual([call[0] for call in session.calls], ["POST", "POST", "POST", "POST"])

    async def test_fetch_home_returns_one_normalized_snapshot(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "device": [
                    {"deviceId": "gw", "deviceType": 114, "uid": "gw-1"},
                    {"deviceId": "switch", "deviceType": 1, "uid": "gw-1"},
                ],
                "deviceStatus": [{"deviceId": "switch", "value": 1}],
                "gateway": [
                    {"uid": "gw-1", "localStaticIP": "192.0.2.10:8088"},
                    {"uid": "other", "localStaticIP": "192.0.2.11"},
                ],
                "room": [{"roomId": "room-1", "roomName": "Office"}],
            },
        }
        session = FakeSession([FakeResponse(payload)])
        client = CloudClient(session, "a", PASSWORD, family_id="family-1")
        client.access_token = "token"
        client.user_id = "user"
        home = await client.fetch_home()
        # The MixPad itself is a hidden type and never reaches the catalogue.
        self.assertEqual(list(home.devices), ["switch"])
        self.assertTrue(home.devices["switch"]["_orvibo_lan_capable"])
        self.assertEqual(home.statuses["switch"]["value"], 1)
        self.assertEqual(dict(home.gateway_ips), {"gw-1": "192.0.2.10"})
        self.assertEqual(dict(home.room_names), {"room-1": "Office"})
        self.assertEqual(home.counts.cloud_gateways, 2)
        self.assertEqual(home.counts.hidden_devices, 1)

    async def test_invalid_status_item_is_schema_error(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "device": [],
                "deviceStatus": [{}],
                "gateway": [],
                "room": [],
            },
        }
        client = CloudClient(FakeSession([FakeResponse(payload)]), "a", PASSWORD)
        client.access_token = "token"
        client.user_id = "user"
        with self.assertRaises(CloudSchemaError):
            await client.fetch_readtable()

    async def test_logs_do_not_include_secrets_or_url(self) -> None:
        digest = ProtocolDigest.from_password("private-password")
        client = CloudClient(
            FakeSession([FakeResponse({"status": 1, "code": 1})]),
            "private-user",
            digest,
        )
        with patch.object(cloud_client._LOGGER, "debug") as debug:
            with self.assertRaises(cloud_client.CloudAuthenticationError):
                await client.login()
        rendered = " ".join(str(value) for call in debug.call_args_list for value in call.args)
        for secret in (
            "private-user",
            "private-password",
            "secret-token",
            "https://",
            digest.value,
        ):
            self.assertNotIn(secret, rendered)


class CloudDeviceTableFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_only_readtable_fetches_device_tables_without_losing_gateway(self):
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "gateway": [{"uid": "gw-1", "localStaticIP": "192.0.2.10"}],
                            "room": [{"roomId": "room-1"}],
                        },
                    }
                ),
                FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "device": [
                                {"deviceId": "gw", "deviceType": 114, "uid": "gw-1"},
                                {"deviceId": "light", "deviceType": 1, "uid": "gw-1"},
                            ],
                            "deviceStatus": [{"deviceId": "light", "value1": 0}],
                            "gateway": [],
                        },
                    }
                ),
            ]
        )
        client = CloudClient(session, "account", PASSWORD, family_id="family-1")
        client.access_token = "token"
        client.user_id = "user"

        devices, statuses, gateways, rooms = await client.fetch_readtable()
        gateway_ips = build_home_snapshot(devices, statuses, gateways, rooms).gateway_ips

        self.assertEqual(len(devices), 2)
        self.assertEqual(statuses["light"]["value1"], 0)
        self.assertEqual(gateway_ips, {"gw-1": "192.0.2.10"})
        self.assertEqual(rooms, [{"roomId": "room-1"}])
        bodies = [call[2]["json"] for call in session.calls]
        self.assertEqual([body["deviceFlag"] for body in bodies], [0, 1])
        self.assertTrue(all(body["familyId"] == "family-1" for body in bodies))
        self.assertTrue(all("sign" in body for body in bodies))

    async def test_explicit_empty_device_table_does_not_trigger_extra_request(self):
        session = FakeSession([FakeResponse({"code": 0, "data": {"device": []}})])
        client = CloudClient(session, "account", PASSWORD, family_id="family-1")
        client.access_token = "token"
        client.user_id = "user"
        devices, *_ = await client.fetch_readtable()
        self.assertEqual(devices, [])
        self.assertEqual(len(session.calls), 1)

    async def test_missing_device_table_in_both_scopes_stops_after_one_fallback(self):
        session = FakeSession(
            [
                FakeResponse({"code": 0, "data": {"gateway": []}}),
                FakeResponse({"code": 0, "data": {"room": []}}),
            ]
        )
        client = CloudClient(session, "account", PASSWORD, family_id="family-1")
        client.access_token = "token"
        client.user_id = "user"
        devices, *_ = await client.fetch_readtable()
        self.assertEqual(devices, [])
        self.assertEqual(len(session.calls), 2)


class GlobalCloudTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_uses_global_service_without_region_configuration(self):
        session = FakeSession([FakeResponse({"code": 0, "data": {"device": []}})])
        client = CloudClient(session, "account", PASSWORD)
        client.access_token = "token"
        client.user_id = "user"
        await client.fetch_readtable()
        self.assertEqual(client.api_host, "homemate.orvibo.com")
        self.assertTrue(session.calls[0][1].startswith("https://homemate.orvibo.com/"))


if __name__ == "__main__":
    unittest.main()


class HashedCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_digest_is_sent_without_double_hashing_or_retaining_plaintext(self):
        digest = "5F4DCC3B5AA765D61D8327DEB882CF99"
        session = FakeSession(
            [
                FakeResponse(oauth_payload()),
                FakeResponse({"code": 0, "data": {"familyInfo": []}}),
            ]
        )
        client = CloudClient(session, "account", ProtocolDigest(digest))
        await client.login()
        self.assertEqual(session.calls[0][2]["data"]["password"], digest)
        self.assertFalse(hasattr(client, "_password"))
