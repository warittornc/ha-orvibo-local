"""Home Assistant coordinator for cloud metadata and LAN gateway state."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Protocol

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
)
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from ..auth.credentials import ProtocolDigest
from ..auth.privacy import mask_identifier
from ..cloud.client import CloudClient
from ..cloud.exceptions import CloudAuthenticationError
from ..const import DOMAIN, GATEWAY_DISCOVER_INTERVAL, UPDATE_INTERVAL
from ..devices.capabilities import normalize_device_type
from ..devices.catalog import HomeSnapshot
from ..exceptions import OrviboLanError
from ..gateway.exceptions import GatewayConnectionError
from ..gateway.manager import GatewayManager, ManagerPushCallback
from ..state.exceptions import StateStoreError
from ..state.ingestion import admit_lan_state
from ..state.models import StateSource, StateUpdate
from ..state.sensors import sensor_state
from ..state.store import StateStore

_LOGGER = logging.getLogger(__name__)

_MAX_DEVICES = 1000
_CONTROL_TIMEOUT = 8.0


class CloudSource(Protocol):
    """What the coordinator needs from the cloud: a login and a home snapshot."""

    async def login(self) -> object: ...

    async def fetch_home(self) -> HomeSnapshot: ...


GatewayManagerFactory = Callable[[Mapping[str, str], ManagerPushCallback], GatewayManager]


class OrviboLanCoordinator(DataUpdateCoordinator[dict[str, dict[str, object]]]):
    """Own the cloud client, gateway manager, and merged device state."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        username: str,
        digest: ProtocolDigest,
        family_id: str | None = None,
        *,
        cloud: CloudSource | None = None,
        gateway_manager_factory: GatewayManagerFactory | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} coordinator",
            update_interval=UPDATE_INTERVAL,
        )
        self.username = username
        self.digest = digest
        self.family_id = family_id
        self.cloud_client: CloudSource = cloud or CloudClient(
            session, username, digest, family_id
        )
        self._gateway_manager_factory = gateway_manager_factory or (
            lambda gateway_ips, push: GatewayManager(
                username, digest, gateway_ips, push_callback=push
            )
        )
        self.gateway_manager: GatewayManager | None = None
        self._home = HomeSnapshot()
        self._device_types: dict[str, int] = {}
        self._states: dict[str, dict[str, object]] = {}
        self._state_store: StateStore | None = None
        self._cloud_generation = 0
        self._lan_generation = 0
        self._discover_task: asyncio.Task[None] | None = None
        self._notify_task: asyncio.Task[None] | None = None
        self._closed = False

    async def async_setup(self) -> None:
        """Authenticate, load initial state, and start managed gateway services."""

        try:
            await self.cloud_client.login()
        except CloudAuthenticationError as err:
            raise ConfigEntryAuthFailed("ORVIBO cloud authentication failed") from err
        except OrviboLanError as err:
            raise UpdateFailed("Unable to connect to the ORVIBO cloud") from err

        await self._refresh_devices_from_cloud()
        self.gateway_manager = self._gateway_manager_factory(
            dict(self._home.gateway_ips), self._on_status_update
        )
        await self._connect_all_gateways()
        self._discover_task = self.hass.async_create_background_task(
            self._gateway_discover_loop(),
            name=f"{DOMAIN}_gateway_discovery",
        )

    async def _async_update_data(self) -> dict[str, dict[str, object]]:
        """Refresh cloud snapshots and keep gateway endpoints current."""

        try:
            await self._refresh_devices_from_cloud()
            if self.gateway_manager is not None:
                await self.gateway_manager.async_update_cloud_gateways(
                    dict(self._home.gateway_ips)
                )
            await self._connect_all_gateways()
        except CloudAuthenticationError as err:
            raise ConfigEntryAuthFailed("ORVIBO cloud authentication expired") from err
        except OrviboLanError as err:
            raise UpdateFailed("Unable to update ORVIBO devices") from err
        return self._states

    async def _refresh_devices_from_cloud(self) -> None:
        """Fetch one cloud snapshot and merge it."""

        self.load_home(await self.cloud_client.fetch_home(), monotonic=time.monotonic())

    def load_home(self, home: HomeSnapshot, *, monotonic: float | None = None) -> None:
        """Replace the device catalogue and merge its cloud state as one generation.

        Devices missing from ``home`` are dropped. Cloud state never overwrites
        newer LAN fields (see ``StateStore``).
        """

        if len(home.devices) > _MAX_DEVICES:
            _LOGGER.warning(
                "Cloud returned %s devices; limiting the entry to %s",
                len(home.devices),
                _MAX_DEVICES,
            )
            home = home.limited(_MAX_DEVICES)
        self._home = home
        self._device_types = {
            device_id: normalize_device_type(device.get("deviceType"))
            for device_id, device in home.devices.items()
        }
        if not home.devices:
            self._state_store = None
            self._sync_public_states()
            return

        self._ensure_state_store(set(home.devices))
        store = self._state_store
        if store is None:
            raise UpdateFailed("ORVIBO cloud returned no supported devices")
        store.retain_devices(home.devices)

        timestamp = time.monotonic() if monotonic is None else monotonic
        self._cloud_generation += 1
        for device_id in home.devices:
            values = dict(home.statuses.get(device_id, {}))
            values.setdefault("deviceId", device_id)
            store.apply(
                StateUpdate(
                    device_id=device_id,
                    values=values,
                    source=StateSource.CLOUD,
                    monotonic=timestamp,
                    generation=self._cloud_generation,
                )
            )
        self._sync_public_states()

    def _ensure_state_store(self, device_ids: set[str]) -> None:
        """Create the store once and extend its device whitelist in place."""

        if not device_ids:
            return
        if self._state_store is None:
            self._state_store = StateStore(device_ids)
            return

        self._state_store.add_devices(device_ids)

    async def _connect_all_gateways(self) -> None:
        """Warm known connections without making one gateway block the entry."""

        manager = self.gateway_manager
        if manager is None:
            return
        results = await asyncio.gather(
            *(manager.ensure(uid) for uid in self._home.gateway_ips),
            return_exceptions=True,
        )
        for uid, result in zip(self._home.gateway_ips, results):
            if isinstance(result, BaseException):
                reason = (
                    result.reason
                    if isinstance(result, GatewayConnectionError)
                    else type(result).__name__
                )
                _LOGGER.debug(
                    "Gateway %s is not ready (reason=%s)",
                    self._masked_device_id(uid),
                    reason,
                )
            else:
                _LOGGER.debug(
                    "Gateway %s connection ready (connected=%s)",
                    self._masked_device_id(uid),
                    result.connected,
                )

    async def _gateway_discover_loop(self) -> None:
        """Periodically ask GatewayManager to validate discovery candidates."""

        try:
            while not self._closed:
                await asyncio.sleep(GATEWAY_DISCOVER_INTERVAL.total_seconds())
                manager = self.gateway_manager
                if manager is None:
                    continue
                try:
                    await manager.discover()
                except (OrviboLanError, OSError) as err:
                    if not self._closed:
                        _LOGGER.debug("Gateway discovery failed (%s)", type(err).__name__)
        except asyncio.CancelledError:
            raise

    async def _on_status_update(
        self,
        gateway_uid: str,
        payload: Mapping[str, object],
    ) -> None:
        """Merge one cmd=42 update received by the manager-owned reader."""

        store = self._state_store
        if store is None:
            return
        values = admit_lan_state(gateway_uid, payload, self._home.devices, store.device_ids)
        if values is None:
            return
        device_id = str(values["deviceId"])
        command = payload.get("cmd")
        fields = tuple(sorted(str(key) for key in payload if not str(key).startswith("__")))
        self._lan_generation += 1
        try:
            changed = store.apply(
                StateUpdate(
                    device_id=device_id,
                    values=values,
                    source=StateSource.LAN,
                    monotonic=time.monotonic(),
                    generation=self._lan_generation,
                )
            )
        except StateStoreError as err:
            _LOGGER.debug(
                "Rejected LAN state for device %s: %s",
                self._masked_device_id(device_id),
                err,
            )
            return
        if not changed:
            _LOGGER.debug(
                "LAN state unchanged for device %s (cmd=%r, fields=%s)",
                self._masked_device_id(device_id),
                command,
                fields,
            )
            return

        self._sync_public_states(notify=False)
        _LOGGER.debug(
            "Applied LAN state for device %s (cmd=%r, fields=%s)",
            self._masked_device_id(device_id),
            command,
            fields,
        )
        if self._notify_task is not None and not self._notify_task.done():
            self._notify_task.cancel()
        self._notify_task = self.hass.async_create_background_task(
            self._debounced_notify(),
            name=f"{DOMAIN}_state_notify",
        )

    @staticmethod
    def _masked_device_id(device_id: str) -> str:
        """Return a stable, privacy-safe identifier for diagnostics."""

        return mask_identifier(device_id)

    async def async_control_device(
        self,
        device_id: str,
        payload: Mapping[str, object],
    ) -> bool:
        """Send a command and raise HomeAssistantError for every failed control."""

        device = self._home.devices.get(device_id)
        if device is None:
            raise HomeAssistantError(f"Unknown ORVIBO device: {self._masked_device_id(device_id)}")
        if device.get("_orvibo_read_only") or device.get("_orvibo_status_only"):
            raise HomeAssistantError(
                f"ORVIBO device {self._masked_device_id(device_id)} is read-only"
            )
        uid_value = device.get("uid")
        if not isinstance(uid_value, str) or not uid_value:
            raise HomeAssistantError(
                f"ORVIBO device {self._masked_device_id(device_id)} has no gateway"
            )
        manager = self.gateway_manager
        if manager is None or self._closed:
            raise HomeAssistantError("ORVIBO gateway manager is unavailable")

        try:
            response = await manager.send(
                uid_value,
                payload,
                timeout=_CONTROL_TIMEOUT,
            )
        except (OrviboLanError, KeyError) as err:
            raise HomeAssistantError(
                f"Failed to control ORVIBO device {self._masked_device_id(device_id)}"
            ) from err
        status = response.get("status")
        if status != 0:
            status_text = (
                status if isinstance(status, int) and not isinstance(status, bool) else "invalid"
            )
            raise HomeAssistantError(
                "ORVIBO device "
                f"{self._masked_device_id(device_id)} rejected the command "
                f"(status={status_text})"
            )
        return True

    async def async_cleanup(self) -> None:
        """Cancel coordinator tasks before closing all manager-owned transports."""

        if self._closed:
            return
        self._closed = True
        tasks = (self._discover_task, self._notify_task)
        self._discover_task = None
        self._notify_task = None
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        for task in tasks:
            if task is not None:
                with suppress(asyncio.CancelledError, Exception):
                    await task
        manager, self.gateway_manager = self.gateway_manager, None
        try:
            if manager is not None:
                await manager.close()
        finally:
            self._state_store = None
        self._home = HomeSnapshot()
        self._device_types = {}
        self._states = {}

    @property
    def devices(self) -> Mapping[str, Mapping[str, object]]:
        """Catalogue devices by id, read-only."""

        return self._home.devices

    @property
    def gateway_uids(self) -> tuple[str, ...]:
        """MixPad gateways in the current home."""

        return tuple(self._home.gateway_ips)

    def device_type(self, device_id: str) -> int:
        """Return a device's normalized type code, or zero when unknown."""

        return self._device_types.get(device_id, 0)

    def get_device_state(self, device_id: str) -> dict[str, object] | None:
        """Return a detached copy of a device's merged, derived state."""

        state = self._states.get(device_id)
        return dict(state) if state is not None else None

    def is_device_available(self, device_id: str) -> bool:
        """Resolve availability from the transport that owns the device."""

        device = self._home.devices.get(device_id)
        if device is None:
            return False
        if device.get("_orvibo_read_only"):
            return bool(getattr(self, "last_update_success", True))
        uid = device.get("uid")
        manager = self.gateway_manager
        return bool(
            isinstance(uid, str) and uid and manager is not None and manager.is_connected(uid)
        )

    def get_room_name(self, device_id: str) -> str | None:
        """Return the cloud room name assigned to a device."""

        return self._home.room_name(device_id, self._states.get(device_id))

    def _sync_public_states(self, *, notify: bool = True) -> None:
        """Derive entity-facing state once per change; the store keeps wire fields only."""
        store = self._state_store
        if store is None:
            self._states = {}
            return
        states: dict[str, dict[str, object]] = {
            device_id: sensor_state(snapshot.values, self._home.devices.get(device_id, {}))
            for device_id, snapshot in store.snapshot_all().items()
        }
        self._states = states
        if notify:
            self.async_set_updated_data(states)

    async def _debounced_notify(self) -> None:
        try:
            await asyncio.sleep(0.2)
            self.async_set_updated_data(self._states)
            _LOGGER.debug(
                "Published LAN state update to Home Assistant (devices=%s)",
                len(self._states),
            )
        except asyncio.CancelledError:
            raise
