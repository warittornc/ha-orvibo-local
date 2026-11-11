"""Async client for the Orvibo cloud discovery APIs."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
import uuid
from collections.abc import Mapping
from typing import Literal, TypeAlias, cast

import aiohttp

from ..auth.credentials import ProtocolDigest
from ..devices.catalog import HomeSnapshot, build_home_snapshot
from ..protocol.constants import HTTPS_HOST, SIGN_KEY, SOFTWARE_VER
from .exceptions import (
    CloudApiError,
    CloudAuthenticationError,
    CloudClientError,
    CloudHttpError,
    CloudJsonError,
    CloudSchemaError,
    CloudTransportError,
)

_LOGGER = logging.getLogger(__name__)

JsonObject: TypeAlias = dict[str, object]
ObjectList: TypeAlias = list[JsonObject]
StatusMap: TypeAlias = dict[str, JsonObject]
OAuthMethod: TypeAlias = Literal["GET", "POST"]


class CloudClient:
    """Fetch cloud metadata through an externally owned aiohttp session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        digest: ProtocolDigest,
        family_id: str | None = None,
        *,
        timeout: aiohttp.ClientTimeout | None = None,
        oauth_method: OAuthMethod = "POST",
    ) -> None:
        if oauth_method not in ("GET", "POST"):
            raise ValueError("oauth_method must be 'GET' or 'POST'")
        self.api_host = HTTPS_HOST
        self._session = session
        self._username = username
        self._digest = digest
        self._timeout = timeout or aiohttp.ClientTimeout(
            total=20,
            connect=5,
            sock_read=15,
        )
        self._oauth_method = oauth_method
        self.family_id = family_id
        self.access_token: str | None = None
        self.user_id: str | None = None
        self.family_list: ObjectList = []
        self.family_name = ""

    async def login(self) -> None:
        """Authenticate and populate account and family metadata."""
        credentials = {
            "userName": self._username,
            "type": "0",
            "password": self._digest.value,
        }
        methods: tuple[OAuthMethod, ...] = (
            ("GET",) if self._oauth_method == "GET" else ("POST", "GET")
        )
        for method in methods:
            try:
                payload = await self._request_json(
                    method,
                    "/getOauthToken",
                    "OAuth login",
                    params=credentials if method == "GET" else None,
                    data=credentials if method == "POST" else None,
                )
                token, user_id = self._parse_oauth_credentials(payload)
            except CloudClientError as err:
                if method != "POST" or not self._should_retry_oauth_with_get(err):
                    raise
                _LOGGER.debug(
                    "OAuth POST response was incompatible (%s); retrying legacy GET",
                    type(err).__name__,
                )
                continue
            self._oauth_method = method
            break
        self.access_token = token
        self.user_id = user_id
        await self.fetch_family_list()

    @classmethod
    def _parse_oauth_credentials(
        cls,
        payload: Mapping[str, object],
    ) -> tuple[str, str]:
        if payload.get("status") != 0 and payload.get("code") != 0:
            raise CloudAuthenticationError("OAuth login was rejected")
        data = cls._require_mapping(payload.get("data"), "OAuth data")
        token = data.get("access_token")
        user_id = data.get("user_id")
        if not isinstance(token, str) or not token:
            raise CloudSchemaError("OAuth data has no access token")
        if not isinstance(user_id, str) or not user_id:
            raise CloudSchemaError("OAuth data has no user ID")
        return token, user_id

    @staticmethod
    def _should_retry_oauth_with_get(error: CloudClientError) -> bool:
        if isinstance(error, CloudHttpError):
            return error.status in {400, 404, 405, 415, 422}
        return isinstance(error, (CloudJsonError, CloudSchemaError))

    async def fetch_family_list(self) -> ObjectList:
        """Fetch families and select the first when none is configured."""
        token, user_id = self._require_credentials()
        params: JsonObject = {
            "accessToken": token,
            "random": uuid.uuid4().hex,
            "timestamp": int(time.time() * 1000),
            "userId": user_id,
        }
        body = dict(params)
        body["sign"] = self._create_sign(params)
        payload = await self._request_json(
            "POST",
            "/v2/family/statistics/users",
            "family list",
            json_body=body,
        )
        self._raise_for_api_error(payload, "family list")

        raw = payload.get("data")
        if isinstance(raw, Mapping):
            family_value = raw.get("familyInfo", [])
        elif isinstance(raw, list):
            family_value = raw
        elif raw is None:
            family_value = []
        else:
            raise CloudSchemaError("family list data must be an object or list")
        families = self._require_object_list(family_value, "family list")
        self.family_list = [
            family
            for family in families
            if isinstance(family.get("familyId"), str) and family["familyId"]
        ]
        if self.family_list:
            first = self.family_list[0]
            name = first.get("familyName", "")
            self.family_name = name if isinstance(name, str) else ""
            if not self.family_id:
                self.family_id = cast(str, first["familyId"])
        return self.family_list

    async def fetch_home(self) -> HomeSnapshot:
        """Return the selected home's device catalogue, re-authenticating once if rejected."""
        return build_home_snapshot(*await self.fetch_readtable())

    async def fetch_readtable(self) -> tuple[ObjectList, StatusMap, ObjectList, ObjectList]:
        """Return the raw devices, states, gateways, and rooms tables."""
        if not self.access_token or not self.user_id:
            await self.login()
        try:
            return await self._fetch_readtable()
        except CloudApiError:
            self.access_token = None
            self.user_id = None
            await self.login()
            return await self._fetch_readtable()

    async def _request_readtable(self, device_flag: int) -> JsonObject:
        """Read one table scope using a freshly signed request."""
        token, user_id = self._require_credentials()
        params: JsonObject = {
            "accessToken": token,
            "dataType": "all",
            "deviceFlag": device_flag,
            "familyId": self.family_id or os.environ.get("ORVIBO_FAMILY_ID", ""),
            "lastUpdateTime": 0,
            "pageIndex": 0,
            "random": uuid.uuid4().hex,
            "serial": int(str(uuid.uuid4().int)[:9]),
            "sessionId": "",
            "timestamp": int(time.time() * 1000),
            "userId": user_id,
            "userName": self._username,
            "ver": SOFTWARE_VER,
        }
        body = dict(params)
        body["sign"] = self._create_sign(params)
        payload = await self._request_json(
            "POST",
            "/v2/cmd/app/readtable",
            "device list",
            json_body=body,
        )
        self._raise_for_api_error(payload, "device list", require_code=True)
        return self._require_mapping(payload.get("data"), "device list data")

    async def _fetch_readtable(
        self,
    ) -> tuple[ObjectList, StatusMap, ObjectList, ObjectList]:
        data = await self._request_readtable(0)
        if "device" not in data:
            _LOGGER.debug("Account table response omitted devices; requesting device tables")
            device_tables = await self._request_readtable(1)
            # Preserve gateway/room tables when the second scope returns empty lists.
            data.update(
                {key: value for key, value in device_tables.items() if value or key not in data}
            )
        devices = self._require_object_list(data.get("device", []), "devices")
        status_items = self._require_object_list(
            data.get("deviceStatus", []),
            "device statuses",
        )
        gateways = self._require_object_list(data.get("gateway", []), "gateways")
        rooms = self._require_object_list(data.get("room", []), "rooms")
        statuses: StatusMap = {}
        for item in status_items:
            device_id = item.get("deviceId")
            if not isinstance(device_id, (str, int)):
                raise CloudSchemaError("device status has no valid deviceId")
            statuses[str(device_id)] = item
        return devices, statuses, gateways, rooms

    async def _request_json(
        self,
        method: OAuthMethod,
        path: str,
        operation: str,
        *,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        json_body: JsonObject | None = None,
    ) -> JsonObject:
        try:
            if method == "GET":
                response = await self._session.get(
                    f"https://{self.api_host}{path}",
                    params=params,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            elif data is not None:
                response = await self._session.post(
                    f"https://{self.api_host}{path}",
                    data=data,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            elif json_body is not None:
                response = await self._session.post(
                    f"https://{self.api_host}{path}",
                    json=json_body,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            else:
                response = await self._session.post(
                    f"https://{self.api_host}{path}",
                    params=params,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise CloudTransportError(f"{operation} request failed") from None

        try:
            if not 200 <= response.status < 300:
                raise CloudHttpError(operation, response.status)
            try:
                payload = await response.json(content_type=None)
            except (ValueError, aiohttp.ClientError) as err:
                raise CloudJsonError(f"{operation} returned invalid JSON") from err
            return self._require_mapping(payload, f"{operation} response")
        finally:
            response.release()

    @staticmethod
    def _require_mapping(value: object, name: str) -> JsonObject:
        if not isinstance(value, Mapping):
            raise CloudSchemaError(f"{name} must be an object")
        return {str(key): item for key, item in value.items()}

    @classmethod
    def _require_object_list(cls, value: object, name: str) -> ObjectList:
        if not isinstance(value, list):
            raise CloudSchemaError(f"{name} must be a list")
        return [cls._require_mapping(item, f"{name} item") for item in value]

    @staticmethod
    def _raise_for_api_error(
        payload: Mapping[str, object],
        operation: str,
        *,
        require_code: bool = False,
    ) -> None:
        code = payload.get("code")
        if (require_code and code != 0) or (code is not None and code != 0):
            raise CloudApiError(f"{operation} was rejected")
        status = payload.get("status")
        if status is not None and status != 0:
            raise CloudApiError(f"{operation} was rejected")

    def _require_credentials(self) -> tuple[str, str]:
        if not self.access_token or not self.user_id:
            raise CloudAuthenticationError("cloud credentials are unavailable")
        return self.access_token, self.user_id

    @staticmethod
    def _create_sign(params: Mapping[str, object]) -> str:
        parts = [
            f"{key}={params[key]}&"
            for key in sorted(params)
            if params[key] is not None and str(params[key]).strip()
        ]
        parts.append(f"key={SIGN_KEY}")
        return (
            hmac.new(
                SIGN_KEY.encode(),
                "".join(parts).encode(),
                hashlib.sha256,
            )
            .hexdigest()
            .upper()
        )
