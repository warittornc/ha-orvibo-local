"""Every per-device-type fact the integration knows, in one table.

Callers ask a profile (``profile_for(device_type)``) instead of comparing raw
Orvibo type codes. Adding or correcting a device type is a one-row change here.

This module must stay free of Home Assistant imports: ``dev/probe_cloud.py`` and
the protocol tests load ``devices/`` on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal


class Platform(StrEnum):
    """Entity platforms; values match ``homeassistant.const.Platform``."""

    BINARY_SENSOR = "binary_sensor"
    CLIMATE = "climate"
    COVER = "cover"
    FAN = "fan"
    LIGHT = "light"
    SENSOR = "sensor"
    SWITCH = "switch"


LightMode = Literal["onoff", "brightness", "color_temp"]
ReadingKind = Literal["flag", "number"]
FanReading = Literal["ventilation", "stepped"]
CoverClass = Literal["curtain", "shutter"]

MIXPAD_GATEWAY_TYPE: Final = 114


@dataclass(frozen=True, slots=True)
class Reading:
    """One normalized state key decoded from a legacy ``valueN`` wire field.

    ``flag`` readings are true when the wire value is 1; ``number`` readings are floats.
    """

    state_key: str
    wire_field: str
    kind: ReadingKind


@dataclass(frozen=True, slots=True)
class LightWire:
    """Which command and reading format a light type uses for each capability.

    dimming:    brightness command: legacy ``order=on`` + value2, ZCL ``move to level``,
                or ThingModel ``brightness.percent``.
    color_temp: colour temperature command and reading: legacy ``fast color temperature``
                with mireds in value3, or ThingModel ``colorTemp.value`` in kelvin.
    combined:   power + brightness (+ colour temperature) in one command: legacy
                ``order=on/off`` or ThingModel ``set property``.
    """

    dimming: Literal["legacy", "level", "property"] = "legacy"
    color_temp: Literal["legacy", "property"] = "legacy"
    combined: Literal["legacy", "property"] = "legacy"


_LEGACY_LIGHT: Final = LightWire()


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Capabilities and wire conventions for one Orvibo device type.

    platforms:   entity platforms the type is exposed on.
    status_only: reports state but must never receive control commands (locks).
    hidden:      gateway or infrastructure device; never exposed or registered.
    thing_model: controlled and read via ThingModel ``properties`` ("set property")
                 rather than the legacy ``valueN`` fields.
    light_mode:  colour capability for light types; ``None`` for non-lights.
    readings:    legacy ``valueN`` fields decoded into named state keys.
    light_wire:  per-capability light command formats (see ``LightWire``).
    fan_reading: ``ventilation`` (onoff/fanSpeed properties, value1 presets) or
                 ``stepped`` (value2 0-3).
    cover_class: how a cover is presented: curtain or roller shutter.
    battery_cells: separately reported lock batteries (``dry``, ``lithium``).
    property_measurements: temperature/humidity may arrive as ThingModel properties.
    """

    platforms: frozenset[Platform] = frozenset()
    status_only: bool = False
    hidden: bool = False
    thing_model: bool = False
    light_mode: LightMode | None = None
    readings: tuple[Reading, ...] = ()
    light_wire: LightWire = _LEGACY_LIGHT
    fan_reading: FanReading = "stepped"
    cover_class: CoverClass = "curtain"
    battery_cells: tuple[Literal["dry", "lithium"], ...] = ()
    property_measurements: bool = False


def _profile(*platforms: Platform, **facts: object) -> DeviceProfile:
    return DeviceProfile(frozenset(platforms), **facts)  # type: ignore[arg-type]


def _flag(state_key: str, wire_field: str = "value1") -> tuple[Reading, ...]:
    return (Reading(state_key, wire_field, "flag"),)


_ENVIRONMENT = (
    Reading("temperature", "value1", "number"),
    Reading("humidity", "value2", "number"),
)
_HIDDEN = DeviceProfile(hidden=True)
_HIDDEN_THING_MODEL = DeviceProfile(hidden=True, thing_model=True)

_UNKNOWN: Final = DeviceProfile()

DEVICE_PROFILES: Final[Mapping[int, DeviceProfile]] = MappingProxyType(
    {
        # ---- Lights ----
        0: _profile(Platform.LIGHT, light_mode="brightness"),  # dimmer
        # Sub-type "1" is a relay, "2" an on/off light, "12" a plug exposed as a switch
        # (sub-type rules live in devices/capabilities.py).
        1: _profile(Platform.LIGHT, light_mode="color_temp"),
        38: _profile(  # tunable
            Platform.LIGHT, light_mode="color_temp", light_wire=LightWire(dimming="level")
        ),
        # Relay. UNVERIFIED: its combined power+brightness command uses ThingModel
        # "set property" although every other 102 command and reading is legacy.
        # Kept as captured until protocol evidence settles it.
        102: _profile(
            Platform.LIGHT, light_mode="onoff", light_wire=LightWire(combined="property")
        ),
        501: _profile(Platform.LIGHT, thing_model=True, light_mode="onoff"),
        502: _profile(
            Platform.LIGHT,
            thing_model=True,
            light_mode="brightness",
            light_wire=LightWire(dimming="property", combined="property"),
        ),
        503: _profile(
            Platform.LIGHT,
            thing_model=True,
            light_mode="color_temp",
            light_wire=LightWire(dimming="property", color_temp="property", combined="property"),
        ),
        # ---- Sensors ----
        22: _profile(Platform.SENSOR, readings=_ENVIRONMENT),  # temperature/humidity
        23: _profile(Platform.SENSOR, readings=_ENVIRONMENT),  # temperature/humidity
        25: _profile(Platform.SENSOR, Platform.BINARY_SENSOR, readings=_flag("gas_detected")),
        26: _profile(
            Platform.SENSOR, Platform.BINARY_SENSOR, readings=_flag("motion_detected", "value3")
        ),
        27: _profile(Platform.SENSOR, Platform.BINARY_SENSOR, readings=_flag("smoke_detected")),
        46: _profile(Platform.SENSOR, Platform.BINARY_SENSOR, readings=_flag("door_state")),
        54: _profile(
            Platform.SENSOR, Platform.BINARY_SENSOR, readings=_flag("water_leak_detected")
        ),
        56: _profile(Platform.SENSOR, Platform.BINARY_SENSOR, readings=_flag("emergency_state")),
        # ---- Locks: state only ----
        107: _profile(Platform.SENSOR, status_only=True, battery_cells=("dry", "lithium")),
        300: _profile(Platform.SENSOR, status_only=True, property_measurements=True),
        522: _profile(Platform.SENSOR, status_only=True, battery_cells=("dry", "lithium")),
        # ---- Covers ----
        34: _profile(Platform.COVER),  # curtain
        35: _profile(Platform.COVER, cover_class="shutter"),  # roller blind
        # ---- Climate and ventilation ----
        # Air conditioner. Its commands use legacy valueN fields despite thing_model.
        36: _profile(Platform.CLIMATE, thing_model=True),
        # UNVERIFIED: state reads value2 0-3, but fan commands send the ventilation
        # value1 presets (0/50/100) that type 516 uses. Kept as captured until
        # protocol evidence settles it.
        81: _profile(Platform.CLIMATE, Platform.FAN),
        516: _profile(Platform.FAN, fan_reading="ventilation"),
        # ---- ThingModel types without an entity platform ----
        2: DeviceProfile(thing_model=True),
        554: DeviceProfile(thing_model=True),
        # ---- Hidden: MixPad, switch bases, IR remotes, cameras, music hosts, RF ----
        MIXPAD_GATEWAY_TYPE: _HIDDEN,
        14: _HIDDEN,
        115: _HIDDEN,
        128: _HIDDEN,
        135: _HIDDEN_THING_MODEL,
        136: _HIDDEN_THING_MODEL,
        137: _HIDDEN_THING_MODEL,
        143: _HIDDEN_THING_MODEL,
        150: _HIDDEN,
        155: _HIDDEN,
        511: _HIDDEN,
        518: _HIDDEN,
    }
)


def profile_for(device_type: object) -> DeviceProfile:
    """Return the profile for a device type; unknown or invalid types get an empty profile."""

    if isinstance(device_type, bool) or not isinstance(device_type, int):
        return _UNKNOWN
    return DEVICE_PROFILES.get(device_type, _UNKNOWN)


def platforms_for_type(device_type: int) -> frozenset[Platform]:
    """Return the declared platforms for one normalized device type."""

    return profile_for(device_type).platforms


def is_status_only_type(device_type: int) -> bool:
    """Return whether a device type only reports state and cannot be controlled.

    Locks (107/300/522) support state reads and pushes only; even when reachable via
    a MixPad gateway, they must not receive control commands.
    """

    return profile_for(device_type).status_only


def is_hidden_type(device_type: object) -> bool:
    """Return whether a device type is infrastructure that is never exposed."""

    return profile_for(device_type).hidden


def uses_thing_model(device_type: int) -> bool:
    """Return whether a device type is controlled through ThingModel properties."""

    return profile_for(device_type).thing_model
