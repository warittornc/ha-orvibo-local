"""Orvibo LAN constants."""

from datetime import timedelta

from .devices.profiles import Platform

# ---- HA configuration keys ----
DOMAIN = "orvibo_lan"
MANUFACTURER = "ORVIBO"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PASSWORD_HASH = "password_hash"
CONF_FAMILY_ID = "family_id"
CONF_SELECTED_DEVICE_IDS = "selected_device_ids"

SERVICE_REFRESH_DEVICES = "refresh_devices"

# ---- Update intervals ----
UPDATE_INTERVAL = timedelta(minutes=1)  # Supplement cloud state for read-only attribute devices
GATEWAY_DISCOVER_INTERVAL = timedelta(minutes=5)  # Discover gateways via UDP

# Per-type facts, including which types are hidden, live in devices/profiles.py.
# Direct Wi-Fi devices (such as type 107/522 locks) are not hidden by type; normalization
# filters them by matching the device UID to a MixPad gateway UID.

# ---- Supported platforms ----
PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.COVER,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]
