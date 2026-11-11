"""State-store error family for rejected snapshot updates."""

from ..exceptions import OrviboLanError


class StateStoreError(OrviboLanError, ValueError):
    """Base exception for invalid state-store operations."""


class UnknownDeviceError(StateStoreError, KeyError):
    """Raised when an update targets a device outside the whitelist."""


class StaleGenerationError(StateStoreError):
    """Raised when an update uses an older source generation."""
