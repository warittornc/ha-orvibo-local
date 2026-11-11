"""Coordinator production-path tests with dependency fakes."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.orvibo_lan.auth.credentials import ProtocolDigest
from custom_components.orvibo_lan.devices.catalog import HomeSnapshot
from custom_components.orvibo_lan.gateway.exceptions import GatewayConnectionError
from custom_components.orvibo_lan.runtime.coordinator import OrviboLanCoordinator
from custom_components.orvibo_lan.state.models import StateSource

PASSWORD = ProtocolDigest.from_password("password")


class FakeHass:
    """Small Home Assistant task surface used by the coordinator."""

    def async_create_background_task(self, coroutine, name: str):
        del name
        import asyncio

        return asyncio.create_task(coroutine)


def home(
    *,
    status: dict[str, object] | None = None,
) -> HomeSnapshot:
    return HomeSnapshot(
        devices={"device-1": {"deviceId": "device-1", "deviceType": 1, "uid": "gateway-1"}},
        statuses={"device-1": status or {"deviceId": "device-1", "value1": 1}},
        gateway_ips={"gateway-1": "192.168.1.2"},
    )


class FakeCloud:
    """Cloud source returning queued home snapshots."""

    def __init__(self, *homes: HomeSnapshot) -> None:
        self.homes = list(homes) or [home()]

    async def login(self) -> None:
        return None

    async def fetch_home(self) -> HomeSnapshot:
        return self.homes.pop(0) if len(self.homes) > 1 else self.homes[0]


class FakeManager:
    """Gateway manager that records calls and delivers pushes through the real callback."""

    def __init__(self, gateway_ips, push_callback, *, connected=True, ensure=None, send=None):
        self.gateway_ips = dict(gateway_ips)
        self.push_callback = push_callback
        self.connected = connected
        self.ensure = ensure or AsyncMock(return_value=SimpleNamespace(connected=True))
        self.send = send or AsyncMock(return_value={"status": 0})
        self.close = AsyncMock()
        self.discover = AsyncMock(return_value={})
        self.async_update_cloud_gateways = AsyncMock()

    def is_connected(self, uid: str) -> bool:
        return self.connected and uid in self.gateway_ips

    async def push(self, gateway_uid: str, payload: dict[str, object]) -> None:
        await self.push_callback(gateway_uid, payload)


def make_coordinator(*homes: HomeSnapshot, **manager_options):
    """Build a coordinator wired to fakes; returns it with a handle to the fake manager."""
    managers: list[FakeManager] = []

    def factory(gateway_ips, push_callback):
        managers.append(FakeManager(gateway_ips, push_callback, **manager_options))
        return managers[-1]

    coordinator = OrviboLanCoordinator(
        FakeHass(),
        MagicMock(),
        "user",
        PASSWORD,
        cloud=FakeCloud(*homes),
        gateway_manager_factory=factory,
    )
    return coordinator, managers


async def started(*homes: HomeSnapshot, **manager_options):
    coordinator, managers = make_coordinator(*homes, **manager_options)
    await coordinator.async_setup()
    return coordinator, managers[0]


async def settle(coordinator: OrviboLanCoordinator) -> None:
    if coordinator._notify_task is not None:
        await coordinator._notify_task


@pytest.mark.asyncio
async def test_gateway_failure_logs_reason_without_exception_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway_uid = "private-gateway-12345678"
    secret = "private-handshake-detail"
    caplog.set_level(
        logging.DEBUG,
        logger="custom_components.orvibo_lan.runtime.coordinator",
    )
    snapshot = HomeSnapshot(gateway_ips={gateway_uid: "192.168.1.2"})
    coordinator, _manager = await started(
        snapshot,
        ensure=AsyncMock(side_effect=GatewayConnectionError(secret, reason="hello_uid_mismatch")),
    )

    assert "reason=hello_uid_mismatch" in caplog.text
    assert "***5678" in caplog.text
    assert gateway_uid not in caplog.text
    assert secret not in caplog.text
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_setup_hands_cloud_gateways_to_the_manager_and_connects_them() -> None:
    coordinator, manager = await started()

    assert manager.gateway_ips == {"gateway-1": "192.168.1.2"}
    manager.ensure.assert_awaited_once_with("gateway-1")
    assert coordinator.gateway_uids == ("gateway-1",)
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_cloud_and_lan_updates_share_state_store() -> None:
    coordinator, manager = await started()

    await manager.push(
        "gateway-1",
        {
            "cmd": 42,
            "deviceId": "device-1",
            "uid": "gateway-1",
            "userName": "private-user",
            "value1": 0,
            "properties": {"level": 5},
        },
    )
    await settle(coordinator)

    state = coordinator.get_device_state("device-1")
    assert state is not None
    assert state["value1"] == 0
    assert state["properties"] == {"level": 5}
    assert "uid" not in state
    assert "userName" not in state
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_cloud_snapshot_removes_missing_device() -> None:
    coordinator, _manager = await started(home(), HomeSnapshot())

    await coordinator._async_update_data()  # what DataUpdateCoordinator calls on refresh

    assert coordinator.devices == {}
    assert coordinator.get_device_state("device-1") is None
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_lan_push_notifies_listeners_once_after_debounce() -> None:
    coordinator, manager = await started()
    notifications = 0

    def listener() -> None:
        nonlocal notifications
        notifications += 1

    coordinator.async_add_listener(listener)
    await manager.push("gateway-1", {"cmd": 42, "deviceId": "device-1", "value1": 0})
    await settle(coordinator)

    assert notifications == 1
    await coordinator.async_cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("id_field", ["deviceId", "deviceID", "device_id"])
async def test_lan_push_normalizes_firmware_device_id_variants(id_field: str) -> None:
    coordinator, manager = await started()

    await manager.push("gateway-1", {"cmd": "42", id_field: " device-1 ", "value1": 0})
    await settle(coordinator)

    state = coordinator.get_device_state("device-1")
    assert state is not None
    assert state["deviceId"] == "device-1"
    assert state["value1"] == 0
    assert "deviceID" not in state
    assert "device_id" not in state
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_lan_push_without_supported_device_id_is_ignored() -> None:
    coordinator, manager = await started()

    await manager.push("gateway-1", {"cmd": 42, "device": "device-1", "value1": 0})

    assert coordinator._notify_task is None
    state = coordinator.get_device_state("device-1")
    assert state is not None
    assert state["value1"] == 1
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_older_cloud_snapshot_does_not_roll_back_lan() -> None:
    coordinator, manager = await started(
        home(), home(status={"deviceId": "device-1", "value1": 1})
    )
    await manager.push("gateway-1", {"cmd": 42, "deviceId": "device-1", "value1": 0})
    await settle(coordinator)

    await coordinator._async_update_data()  # what DataUpdateCoordinator calls on refresh

    state = coordinator.get_device_state("device-1")
    assert state is not None
    assert state["value1"] == 0
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_lan_battery_outside_range_does_not_keep_stale_cloud_battery() -> None:
    sensor = {"deviceId": "sensor", "deviceType": 26, "uid": "gateway-1"}
    snapshot = HomeSnapshot(
        devices={"sensor": sensor},
        statuses={"sensor": {"value4": 80}},
        gateway_ips={"gateway-1": "192.168.1.2"},
    )
    coordinator, manager = await started(snapshot)
    assert coordinator.get_device_state("sensor")["battery"] == 80

    await manager.push("gateway-1", {"cmd": 42, "deviceId": "sensor", "value4": 255})
    await settle(coordinator)

    state = coordinator.get_device_state("sensor")
    assert state["value4"] == 255
    assert "battery" not in state
    await coordinator.async_cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway_uid", "payload"),
    [
        ("wrong-gateway", {"cmd": 42, "deviceId": "device-1", "value1": 0}),
        ("gateway-1", {"cmd": True, "deviceId": "device-1", "value1": 0}),
        ("gateway-1", {"cmd": 42, "deviceId": "device-1", "value1": {"bad": 1}}),
        ("gateway-1", {"cmd": 42, "deviceId": "device-1", "properties": []}),
        ("gateway-1", {"cmd": 42, "deviceId": "device-1", "door_state": True}),
        (
            "gateway-1",
            {"cmd": 42, "deviceId": "device-1", "uid": "wrong-gateway", "value1": 0},
        ),
    ],
)
async def test_lan_push_rejects_untrusted_source_or_malformed_state(
    gateway_uid: str,
    payload: dict[str, object],
) -> None:
    coordinator, manager = await started()

    await manager.push(gateway_uid, payload)

    assert coordinator._notify_task is None
    state = coordinator.get_device_state("device-1")
    assert state is not None
    assert state["value1"] == 1
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_validated_compatibility_command_preserves_firmware_support() -> None:
    coordinator, manager = await started()

    await manager.push("gateway-1", {"cmd": 99, "deviceId": "device-1", "value1": 0})
    await settle(coordinator)

    state = coordinator.get_device_state("device-1")
    assert state is not None
    assert state["value1"] == 0
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_control_sends_through_the_device_gateway() -> None:
    coordinator, manager = await started()

    assert await coordinator.async_control_device("device-1", {"cmd": 15})
    manager.send.assert_awaited_once()
    assert manager.send.await_args.args[:2] == ("gateway-1", {"cmd": 15})
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_control_rejection_raises_home_assistant_error() -> None:
    coordinator, _manager = await started(send=AsyncMock(return_value={"status": 7}))

    with pytest.raises(Exception, match="rejected"):
        await coordinator.async_control_device("device-1", {"cmd": 15})
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_control_of_read_only_device_is_refused() -> None:
    lock = {"deviceId": "lock", "uid": "", "_orvibo_read_only": True}
    coordinator, manager = await started(HomeSnapshot(devices={"lock": lock}))

    with pytest.raises(Exception, match="read-only"):
        await coordinator.async_control_device("lock", {"cmd": 15})
    manager.send.assert_not_awaited()
    await coordinator.async_cleanup()


@pytest.mark.asyncio
async def test_cleanup_closes_manager_once_and_clears_state() -> None:
    coordinator, manager = await started()

    await coordinator.async_cleanup()
    await coordinator.async_cleanup()

    manager.close.assert_awaited_once()
    assert coordinator.gateway_manager is None
    assert coordinator.devices == {}


def test_profile_source_marks_lan_state() -> None:
    """Keep the state source contract explicit for integration tests."""

    assert StateSource.LAN.value == "lan"


@pytest.mark.asyncio
async def test_availability_uses_gateway_for_lan_and_cloud_for_read_only() -> None:
    snapshot = HomeSnapshot(
        devices={
            "lan": {"deviceId": "lan", "uid": "gateway-1", "_orvibo_read_only": False},
            "cloud": {"deviceId": "cloud", "uid": "", "_orvibo_read_only": True},
        },
        statuses={"lan": {"online": False}, "cloud": {"online": True}},
        gateway_ips={"gateway-1": "192.168.1.2"},
    )
    coordinator, manager = await started(snapshot)
    coordinator.last_update_success = True

    assert coordinator.is_device_available("lan")
    assert coordinator.is_device_available("cloud")
    coordinator.last_update_success = False
    assert not coordinator.is_device_available("cloud")
    assert coordinator.is_device_available("lan")
    manager.connected = False
    assert not coordinator.is_device_available("lan")
    await coordinator.async_cleanup()


def test_runtime_cloud_client_uses_global_service_by_default():
    coordinator = OrviboLanCoordinator(FakeHass(), MagicMock(), "user", PASSWORD)
    assert coordinator.cloud_client.api_host == "homemate.orvibo.com"
