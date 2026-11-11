"""One home's device catalogue, built once from the cloud readtable.

The cloud client, the setup flows, the coordinator, and the cloud probe all
consume a ``HomeSnapshot`` instead of re-running normalization, room lookup,
gateway mapping, and hidden-type filtering themselves.

Like ``profiles.py``, this module must stay free of Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .capabilities import normalize_device_type, normalize_readtable_devices, state_properties
from .profiles import MIXPAD_GATEWAY_TYPE, is_hidden_type

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class SnapshotCounts:
    """Raw table sizes, for discovery diagnostics."""

    cloud_devices: int = 0
    cloud_states: int = 0
    cloud_gateways: int = 0
    rooms: int = 0
    normalized_devices: int = 0
    hidden_devices: int = 0


@dataclass(frozen=True, slots=True)
class HomeSnapshot:
    """Selectable devices, their cloud state, rooms, and MixPad endpoints.

    devices:     normalized devices by id, in cloud order; hidden types removed.
    statuses:    raw cloud state by device id.
    room_names:  room name by room id.
    gateway_ips: MixPad gateway uid -> LAN host.
    """

    devices: Mapping[str, JsonObject] = field(default_factory=dict)
    statuses: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    room_names: Mapping[str, str] = field(default_factory=dict)
    gateway_ips: Mapping[str, str] = field(default_factory=dict)
    counts: SnapshotCounts = SnapshotCounts()

    def room_name(self, device_id: str, state: Mapping[str, Any] | None = None) -> str | None:
        """Resolve a device's room: its roomId, then the state descriptor, then roomName."""
        device = self.devices.get(device_id)
        if device is None:
            return None
        room_id = device.get("roomId")
        if room_id not in (None, ""):
            room_name = self.room_names.get(str(room_id))
            if room_name:
                return room_name
        descriptor = state_properties(state).get("Descriptor")
        if isinstance(descriptor, Mapping):
            state_room_id = descriptor.get("roomId")
            if state_room_id not in (None, ""):
                return self.room_names.get(str(state_room_id))
        device_room_name = device.get("roomName")
        return str(device_room_name) if device_room_name not in (None, "") else None

    def limited(self, max_devices: int) -> HomeSnapshot:
        """Return a snapshot keeping only the first ``max_devices`` devices."""
        if len(self.devices) <= max_devices:
            return self
        kept = dict(list(self.devices.items())[:max_devices])
        return HomeSnapshot(
            devices=MappingProxyType(kept),
            statuses=self.statuses,
            room_names=self.room_names,
            gateway_ips=self.gateway_ips,
            counts=self.counts,
        )


def gateway_ip_map(
    gateways: Sequence[Mapping[str, Any]],
    devices: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Map MixPad gateway uids to LAN hosts, ignoring non-MixPad gateways."""
    mixpad_uids = {
        uid
        for device in devices
        if normalize_device_type(device.get("deviceType")) == MIXPAD_GATEWAY_TYPE
        and isinstance((uid := device.get("uid")), str)
        and uid
    }
    result: dict[str, str] = {}
    for gateway in gateways:
        uid = gateway.get("uid")
        raw_ip = gateway.get("localStaticIP") or gateway.get("ip")
        if isinstance(uid, str) and uid in mixpad_uids and isinstance(raw_ip, str) and raw_ip:
            result[uid] = raw_ip.split(":", maxsplit=1)[0]
    return result


def build_home_snapshot(
    devices: Sequence[Mapping[str, Any]],
    statuses: Mapping[str, Mapping[str, Any]],
    gateways: Sequence[Mapping[str, Any]],
    rooms: Sequence[Mapping[str, Any]],
) -> HomeSnapshot:
    """Normalize one readtable into the catalogue every consumer shares."""
    gateway_ips = gateway_ip_map(gateways, devices)
    normalized = normalize_readtable_devices(list(devices), statuses, set(gateway_ips))
    visible: dict[str, JsonObject] = {}
    hidden = 0
    for device in normalized:
        if is_hidden_type(device.get("deviceType")):
            hidden += 1
            continue
        visible[str(device["deviceId"])] = device
    room_names = {
        str(room["roomId"]): str(room.get("roomName") or "")
        for room in rooms
        if room.get("roomId") not in (None, "")
    }
    return HomeSnapshot(
        devices=MappingProxyType(visible),
        statuses=MappingProxyType(dict(statuses)),
        room_names=MappingProxyType(room_names),
        gateway_ips=MappingProxyType(gateway_ips),
        counts=SnapshotCounts(
            cloud_devices=len(devices),
            cloud_states=len(statuses),
            cloud_gateways=len(gateways),
            rooms=len(rooms),
            normalized_devices=len(normalized),
            hidden_devices=hidden,
        ),
    )
