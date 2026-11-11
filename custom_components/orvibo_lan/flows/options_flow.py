"""Config, reauthentication, and options flows for ORVIBO LAN."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..auth.credentials import ProtocolDigest
from ..auth.exceptions import CredentialError
from ..auth.secrets import SECRET_KEY, async_resolve_digest, async_store_digest
from ..cloud.client import CloudClient
from ..cloud.exceptions import CloudAuthenticationError, CloudClientError
from ..const import (
    CONF_FAMILY_ID,
    CONF_PASSWORD,
    CONF_PASSWORD_HASH,
    CONF_SELECTED_DEVICE_IDS,
    CONF_USERNAME,
)
from ..devices.selection import selected_device_ids
from .selection import device_schema, validated_selection
from .validation import JsonObject, load_devices, validate_account


class OrviboLanOptionsFlow(config_entries.OptionsFlow):
    """Select exposed devices using fresh cloud metadata."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # Home Assistant exposes ``config_entry`` as a read-only property on
        # OptionsFlow. Keep the factory argument privately for compatibility
        # with HA versions that do not populate that property yet.
        self._config_entry = config_entry
        self._devices: list[JsonObject] = []

    async def async_step_init(
        self,
        user_input: JsonObject | None = None,
    ) -> FlowResult:
        """Show user-initiated account and device management actions."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["reauth", "devices", "secrets"],
        )

    async def async_step_reauth(
        self,
        user_input: JsonObject | None = None,
    ) -> FlowResult:
        """Update the password without replacing the config entry."""
        errors: dict[str, str] = {}
        config_entry = self._config_entry
        username = str(config_entry.data[CONF_USERNAME])

        if user_input is not None:
            password = str(user_input.get(CONF_PASSWORD) or "")
            if not password:
                errors["base"] = "empty_username_or_password"
            else:
                digest = ProtocolDigest.from_password(password)
                result = await validate_account(
                    async_get_clientsession(self.hass),
                    username,
                    digest,
                    str(config_entry.data.get(CONF_FAMILY_ID) or "") or None,
                )
                if result.error:
                    errors["base"] = result.error
                else:
                    try:
                        data = await async_store_digest(
                            self.hass,
                            config_entry.data,
                            identity=config_entry.entry_id,
                            digest=digest,
                        )
                    except CredentialError:
                        errors["base"] = "secret_error"
                    else:
                        if data == config_entry.data:
                            await self.hass.config_entries.async_reload(config_entry.entry_id)
                        else:
                            self.hass.config_entries.async_update_entry(config_entry, data=data)
                        return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"username": username},
        )

    async def async_step_secrets(self, user_input: JsonObject | None = None) -> FlowResult:
        """Switch to an existing native secret without copying its value into the entry."""
        entry = self._config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(entry.data)
            data[SECRET_KEY] = user_input.get(SECRET_KEY)
            data.pop(CONF_PASSWORD, None)
            data.pop(CONF_PASSWORD_HASH, None)
            try:
                digest = await async_resolve_digest(self.hass, data)
                result = await validate_account(
                    async_get_clientsession(self.hass),
                    str(data[CONF_USERNAME]),
                    digest,
                    str(data.get(CONF_FAMILY_ID) or "") or None,
                )
                if result.error:
                    errors["base"] = result.error
            except CredentialError:
                errors["base"] = "secret_error"
            except CloudAuthenticationError:
                errors["base"] = "auth_failed"
            except CloudClientError:
                errors["base"] = "cannot_connect"
            else:
                if not errors:
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    return self.async_abort(reason="secret_updated")
        return self.async_show_form(
            step_id="secrets",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(SECRET_KEY, default=str(entry.data.get(SECRET_KEY, ""))): str,
                }
            ),
        )

    async def async_step_devices(
        self,
        user_input: JsonObject | None = None,
    ) -> FlowResult:
        """Select exposed devices using fresh cloud metadata."""
        errors: dict[str, str] = {}
        config_entry = self._config_entry
        if not self._devices:
            try:
                digest = await async_resolve_digest(self.hass, config_entry.data)
            except CredentialError:
                return self.async_abort(reason="secret_error")
            client = CloudClient(
                async_get_clientsession(self.hass),
                str(config_entry.data[CONF_USERNAME]),
                digest,
                str(config_entry.data.get(CONF_FAMILY_ID) or "") or None,
            )
            try:
                await client.login()
                self._devices, _gateway_ips = await load_devices(client)
            except CloudAuthenticationError:
                errors["base"] = "auth_failed"
            except CloudClientError:
                errors["base"] = "cannot_connect"
        if not self._devices and not errors:
            return self.async_abort(reason="no_devices")
        if user_input is not None and CONF_SELECTED_DEVICE_IDS in user_input:
            selected = validated_selection(user_input[CONF_SELECTED_DEVICE_IDS], self._devices)
            if selected:
                return self.async_create_entry(
                    title="",
                    data={CONF_SELECTED_DEVICE_IDS: selected},
                )
            errors["base"] = "no_devices_selected"
        current = selected_device_ids(
            config_entry.options,
            (str(device["deviceId"]) for device in self._devices),
        )
        return self.async_show_form(
            step_id="devices",
            data_schema=device_schema(self._devices, sorted(current)),
            errors=errors,
        )
