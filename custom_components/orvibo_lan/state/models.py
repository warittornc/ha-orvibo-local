"""Immutable state reconciliation records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class StateSource(str, Enum):
    """Origin of a device-state update."""

    CLOUD = "cloud"
    LAN = "lan"


@dataclass(frozen=True, slots=True)
class StateUpdate:
    """A versioned partial state update for one whitelisted device."""

    device_id: str
    values: Mapping[str, Any]
    source: StateSource
    monotonic: float
    generation: int


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """Immutable public view of one device's merged state."""

    device_id: str
    values: Mapping[str, Any]
