"""Device-family adapters: read merged state and build control payloads.

Each family owns both directions of one device family's wire format, so the
reading and the command for a type can never disagree silently. Entities only
translate between these adapters and Home Assistant.

Like ``profiles.py``, this module must stay free of Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from .capabilities import light_color_mode, normalize_device_type, verified_profile_name
from .control import climate as climate_control
from .control import light as light_control
from .control import numeric as numeric_control
from .profiles import LightMode, profile_for

State = Mapping[str, Any]
Payload = dict[str, Any]
HvacMode = Literal["off", "cool", "heat", "dry", "fan_only"]
FanMode = Literal["auto", "low", "medium", "high"]


def wire_int(value: object) -> int | None:
    """Parse one wire integer; malformed values read as missing instead of raising."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _properties(state: State) -> Mapping[str, Any]:
    properties = state.get("properties")
    return properties if isinstance(properties, Mapping) else {}


def _nested(state: State, key: str, field: str) -> Any:
    value = _properties(state).get(key)
    return value.get(field) if isinstance(value, Mapping) else None


class _Family:
    """Command target shared by every family: device, gateway, and account."""

    def __init__(self, device: Mapping[str, Any], username: str) -> None:
        self.device_id = str(device.get("deviceId", ""))
        self.uid = str(device.get("uid") or "")
        self.device_type = normalize_device_type(device.get("deviceType"))
        self.profile = profile_for(self.device_type)
        self.username = username


class LightFamily(_Family):
    """Legacy (value1-3) and ThingModel (properties) lights."""

    min_kelvin: Final = light_control.MIN_KELVIN
    max_kelvin: Final = light_control.MAX_KELVIN

    def __init__(self, device: Mapping[str, Any], username: str) -> None:
        super().__init__(device, username)
        self.color_mode: LightMode = light_color_mode(device)
        self._power_only = verified_profile_name(device) == "power_only_light"

    def is_on(self, state: State) -> bool:
        if self.profile.thing_model:
            return _nested(state, "onoff", "status") == "on"
        # Legacy: value1=0 on, value1=1 off
        return wire_int(state.get("value1")) == 0

    def brightness(self, state: State) -> int | None:
        """Brightness 0-255 while on."""
        if not self.is_on(state):
            return None
        if self.profile.thing_model:
            percent = wire_int(_nested(state, "brightness", "percent"))
            return percent * 255 // 100 if percent is not None else None
        value2 = wire_int(state.get("value2"))
        return max(0, min(value2, 255)) if value2 is not None else None

    def color_temp_kelvin(self, state: State) -> int | None:
        if not self.is_on(state):
            return None
        if self.profile.thing_model and self.profile.light_wire.color_temp == "property":
            kelvin = wire_int(_nested(state, "colorTemp", "value"))
            return kelvin or None
        # Legacy: value3 = colour temperature in mireds
        mired = wire_int(state.get("value3"))
        if mired is not None and 150 <= mired <= 400:
            return 1000000 // mired
        return None

    def turn_on(
        self,
        state: State,
        *,
        brightness: int | None = None,
        kelvin: int | None = None,
    ) -> Payload:
        if self._power_only:
            return light_control.power_only_light(self.device_id, self.uid, True, self.username)
        if brightness is not None and kelvin is not None:
            return light_control.light_on_off(
                self.device_id,
                self.uid,
                self.device_type,
                True,
                brightness=brightness,
                color_temp_k=kelvin,
                username=self.username,
            )
        if brightness is not None:
            return light_control.light_brightness(
                self.device_id, self.uid, self.device_type, brightness, self.username
            )
        if kelvin is not None:
            return light_control.light_colortemp(
                self.device_id,
                self.uid,
                self.device_type,
                kelvin,
                brightness=self.brightness(state) or 255,
                username=self.username,
            )
        return light_control.light_on(self.device_id, self.uid, self.device_type, self.username)

    def turn_off(self) -> Payload:
        if self._power_only:
            return light_control.power_only_light(self.device_id, self.uid, False, self.username)
        return light_control.light_off(self.device_id, self.uid, self.device_type, self.username)


class PlugFamily(_Family):
    """Plugs speak the legacy light on/off protocol (value1: 0 on, 1 off)."""

    def is_on(self, state: State) -> bool:
        return wire_int(state.get("value1")) == 0

    def turn_on(self) -> Payload:
        return light_control.light_on(self.device_id, self.uid, self.device_type, self.username)

    def turn_off(self) -> Payload:
        return light_control.light_off(self.device_id, self.uid, self.device_type, self.username)


class CoverFamily(_Family):
    """Curtains and roller blinds: value1 is 0 closed to 100 open."""

    @property
    def shutter(self) -> bool:
        return self.profile.cover_class == "shutter"

    def position(self, state: State) -> int | None:
        value1 = wire_int(state.get("value1"))
        return max(0, min(value1, 100)) if value1 is not None else None

    def is_closed(self, state: State) -> bool | None:
        position = self.position(state)
        return position <= 5 if position is not None else None

    def open(self) -> Payload:
        return numeric_control.cover_open(self.device_id, self.uid, self.username)

    def close(self) -> Payload:
        return numeric_control.cover_close(self.device_id, self.uid, self.username)

    def stop(self) -> Payload:
        return numeric_control.cover_stop(self.device_id, self.uid, self.username)

    def set_position(self, position: int) -> Payload:
        return numeric_control.cover_position(self.device_id, self.uid, position, self.username)


# Ventilation value1 presets: 0=slow, 50=stop, 100=fast.
_VENTILATION_PERCENT: Final = {50: 0, 0: 33, 100: 100}


class FanFamily(_Family):
    """Ventilation (type 516) and stepped (value2 0-3) fans."""

    def is_on(self, state: State) -> bool:
        if self.profile.fan_reading == "ventilation":
            status = _nested(state, "onoff", "status")
            if status is not None:
                return bool(status == "on")
            value1 = wire_int(state.get("value1"))
            return value1 is not None and value1 != 50
        value2 = wire_int(state.get("value2"))
        return value2 is not None and value2 > 0

    def percentage(self, state: State) -> int | None:
        if self.profile.fan_reading == "ventilation":
            speed = wire_int(_nested(state, "fanSpeed", "value"))
            if speed is not None:
                return speed
            value1 = wire_int(state.get("value1"))
            return _VENTILATION_PERCENT.get(value1) if value1 is not None else None
        # Stepped: value2 = 0 (off) / 1 (low) / 2 (mid) / 3 (high)
        value2 = wire_int(state.get("value2"))
        if value2 is None:
            return None
        return 0 if value2 == 0 else int(value2 * 100 / 3)

    # Commands always use the ventilation presets; see the type-81 profile note.
    def turn_on(self) -> Payload:
        return numeric_control.fan_on(self.device_id, self.uid, self.device_type, self.username)

    def turn_off(self) -> Payload:
        return numeric_control.fan_off(self.device_id, self.uid, self.device_type, self.username)

    def set_percentage(self, percentage: int) -> Payload:
        return numeric_control.fan_set_speed(
            self.device_id, self.uid, self.device_type, percentage, self.username
        )


_HVAC_BY_WIRE: Final[Mapping[int, HvacMode]] = {2: "dry", 3: "cool", 4: "heat", 7: "fan_only"}
_WIRE_BY_HVAC: Final[Mapping[str, int]] = {mode: wire for wire, mode in _HVAC_BY_WIRE.items()}
_FAN_MODES: Final[tuple[FanMode, ...]] = ("auto", "low", "medium", "high")
_DEFAULT_TEMPERATURE: Final = 25.0


class ClimateFamily(_Family):
    """Air conditioners.

    value1: 0=on / 1=off · value2: 2=dry / 3=cool / 4=heat / 7=fan
    value3: fan speed 1-3 · value4: high 16 bits target x100, low 16 bits current x100
    """

    hvac_modes: Final[tuple[HvacMode, ...]] = ("off", "cool", "heat", "fan_only", "dry")
    fan_modes: Final = _FAN_MODES

    def hvac_mode(self, state: State) -> HvacMode:
        if wire_int(state.get("value1")) != 0:
            return "off"
        mode = wire_int(state.get("value2"))
        return _HVAC_BY_WIRE.get(mode, "cool") if mode is not None else "cool"

    def target_temperature(self, state: State) -> float:
        value4 = wire_int(state.get("value4"))
        return (value4 >> 16) / 100.0 if value4 is not None else _DEFAULT_TEMPERATURE

    def current_temperature(self, state: State) -> float:
        value4 = wire_int(state.get("value4"))
        return (value4 & 0xFFFF) / 100.0 if value4 is not None else _DEFAULT_TEMPERATURE

    def fan_mode(self, state: State) -> FanMode:
        speed = wire_int(state.get("value3"))
        return _FAN_MODES[speed] if speed is not None and 1 <= speed <= 3 else "auto"

    def set_hvac_mode(self, mode: str, state: State) -> Payload:
        if mode == "off":
            return climate_control.ac_off(self.device_id, self.uid, username=self.username)
        return climate_control.ac_on_with_mode(
            self.device_id,
            self.uid,
            _WIRE_BY_HVAC.get(mode, 3),
            username=self.username,
            current_state=dict(state),
        )

    def set_temperature(self, temperature: float, state: State) -> Payload:
        return climate_control.ac_set_temp(
            self.device_id,
            self.uid,
            int(temperature),
            username=self.username,
            current_state=dict(state),
        )

    def set_fan_mode(self, mode: str, state: State) -> Payload:
        speed = {"low": 1, "medium": 2, "high": 3}.get(mode.lower(), 1)
        return climate_control.ac_wind(
            self.device_id, self.uid, speed, username=self.username, current_state=dict(state)
        )
