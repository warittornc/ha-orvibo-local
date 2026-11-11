"""Shared account discovery and LAN credential validation."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

import aiohttp

from ..auth.credentials import ProtocolDigest
from ..cloud.client import CloudClient
from ..cloud.exceptions import CloudAuthenticationError, CloudClientError
from ..devices.capabilities import platforms_for_device

_LOGGER = logging.getLogger(__name__)
JsonObject = dict[str, object]


async def load_devices(
    client: CloudClient,
) -> tuple[list[JsonObject], Mapping[str, str]]:
    """Return the devices offered for selection, with room names, and gateway hosts."""
    snapshot = await client.fetch_home()
    result: list[JsonObject] = []
    unsupported_count = 0
    for device_id, device in snapshot.devices.items():
        state = snapshot.statuses.get(device_id, {})
        if not device.get("_orvibo_lan_capable") and not platforms_for_device(device, state):
            unsupported_count += 1
            continue
        result.append({**device, "roomName": snapshot.room_name(device_id, state) or ""})
    counts = snapshot.counts
    _LOGGER.debug(
        "Discovery counts: homes=%d cloud_devices=%d cloud_states=%d "
        "cloud_gateways=%d mapped_gateway_ips=%d normalized_devices=%d "
        "hidden_devices=%d unsupported_devices=%d selectable_devices=%d",
        len(client.family_list),
        counts.cloud_devices,
        counts.cloud_states,
        counts.cloud_gateways,
        len(snapshot.gateway_ips),
        counts.normalized_devices,
        counts.hidden_devices,
        unsupported_count,
        len(result),
    )
    return result, dict(snapshot.gateway_ips)


async def probe_gateway_credentials(
    username: str,
    digest: ProtocolDigest,
    gateway_ips: Mapping[str, str],
) -> bool:
    """Validate credentials against one available LAN gateway."""
    if not gateway_ips:
        return True
    from ..gateway.connection import GatewayConnection
    from ..gateway.exceptions import GatewayLoginRejectedError

    uid, host = next(iter(gateway_ips.items()))
    connection = GatewayConnection(str(host))
    try:
        await connection.connect(
            username,
            digest,
            expected_uid=str(uid),
            allow_missing_uid=True,
        )
    except GatewayLoginRejectedError as error:
        _LOGGER.debug(
            "MixPad rejected the LAN login after cloud discovery succeeded (status=%s)",
            error.status,
        )
        return False
    except Exception:
        # A timeout or temporarily unreachable gateway is not proof that the
        # replacement password is invalid. Only explicit rejection fails it.
        return True
    finally:
        await connection.close()
    return True


@dataclass(slots=True)
class AccountValidation:
    """Account metadata and an optional form error after ordered validation."""

    client: CloudClient
    devices: list[JsonObject] = field(default_factory=list)
    gateway_ips: Mapping[str, str] = field(default_factory=dict)
    error: str | None = None


async def validate_account(
    session: aiohttp.ClientSession,
    username: str,
    digest: ProtocolDigest,
    family_id: str | None = None,
) -> AccountValidation:
    """Sign in, discover devices, then test LAN acceptance of the same digest."""
    client = CloudClient(session, username, digest, family_id)
    result = AccountValidation(client)
    try:
        await client.login()
        result.devices, result.gateway_ips = await load_devices(client)
    except CloudAuthenticationError:
        result.error = "auth_failed"
    except CloudClientError:
        result.error = "cannot_connect"
    else:
        if not await probe_gateway_credentials(
            username,
            digest,
            result.gateway_ips,
        ):
            result.error = "gateway_auth_failed"
    return result
