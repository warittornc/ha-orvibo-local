"""Config, reauthentication, and options flows for ORVIBO LAN."""

from __future__ import annotations

from collections.abc import Mapping

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..auth.credentials import ProtocolDigest
from ..auth.exceptions import CredentialError
from ..auth.secrets import async_store_digest
from ..cloud.client import CloudClient
from ..cloud.exceptions import CloudAuthenticationError, CloudClientError
from ..const import (
    CONF_FAMILY_ID,
    CONF_PASSWORD,
    CONF_SELECTED_DEVICE_IDS,
    CONF_USERNAME,
    DOMAIN,
)
from ..devices.selection import config_entry_unique_id
from .options_flow import OrviboLanOptionsFlow
from .selection import device_schema, validated_selection
from .validation import load_devices, probe_gateway_credentials, validate_account

JsonObject = dict[str, object]


class OrviboLanConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Create and reauthenticate an ORVIBO LAN config entry."""

    VERSION = 5

    def __init__(self) -> None:

        self._username = ""
        self._digest: ProtocolDigest | None = None
        self._family_list: list[JsonObject] = []
        self._family_name = ""
        self._selected_family_id: str | None = None
        self._user_id = ""
        self._devices: list[JsonObject] = []
        self._gateway_auth_checked = False
        self._client: CloudClient | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OrviboLanOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: JsonObject | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = str(user_input.get(CONF_USERNAME) or "").strip()
            password = str(user_input.get(CONF_PASSWORD) or "")
            if not username or not password:
                errors["base"] = "empty_username_or_password"
            else:
                digest = ProtocolDigest.from_password(password)
                result = await validate_account(
                    async_get_clientsession(self.hass),
                    username,
                    digest,
                )
                if result.error:
                    errors["base"] = result.error
                else:
                    client = result.client
                    self._username = username
                    self._digest = digest
                    self._client = client
                    self._family_list = client.family_list
                    self._family_name = client.family_name
                    self._user_id = client.user_id or username
                    self._gateway_auth_checked = True
                    if len(self._family_list) > 1:
                        return await self.async_step_select_family()
                    self._selected_family_id = client.family_id
                    return await self.async_step_devices()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_select_family(
        self,
        user_input: JsonObject | None = None,
    ) -> FlowResult:
        if user_input is not None:
            selected = str(user_input.get(CONF_FAMILY_ID) or "")
            if selected:
                self._selected_family_id = selected
                if self._client is not None:
                    self._client.family_id = selected
                for family in self._family_list:
                    if family.get("familyId") == selected:
                        self._family_name = str(family.get("familyName") or "")
                        break
                return await self.async_step_devices()
        choices = {
            str(family["familyId"]): str(family.get("familyName") or family["familyId"])
            for family in self._family_list
        }
        return self.async_show_form(
            step_id="select_family",
            data_schema=vol.Schema({vol.Required(CONF_FAMILY_ID): vol.In(choices)}),
        )

    async def async_step_devices(
        self,
        user_input: JsonObject | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if not self._devices and self._client is not None:
            try:
                self._devices, gateway_ips = await load_devices(self._client)
            except CloudAuthenticationError:
                errors["base"] = "auth_failed"
            except CloudClientError:
                errors["base"] = "cannot_connect"
            else:
                if self._devices and not self._gateway_auth_checked:
                    self._gateway_auth_checked = True
                    if not await self._probe_gateway_login(gateway_ips):
                        return self.async_abort(reason="gateway_auth_failed")
        if not self._devices and not errors:
            # Abort when the home has no eligible devices.
            return self.async_abort(reason="no_devices")
        if user_input is not None and CONF_SELECTED_DEVICE_IDS in user_input:
            selected = validated_selection(user_input[CONF_SELECTED_DEVICE_IDS], self._devices)
            if selected:
                return await self._create_entry(selected)
            errors["base"] = "no_devices_selected"
        return self.async_show_form(
            step_id="devices",
            data_schema=device_schema(self._devices),
            errors=errors,
        )

    async def _create_entry(self, selected: list[str]) -> FlowResult:
        family_id = self._selected_family_id
        if family_id is None and self._family_list:
            family_id = str(self._family_list[0]["familyId"])
        await self.async_set_unique_id(config_entry_unique_id(self._user_id, family_id))
        self._abort_if_unique_id_configured()
        try:
            data = await async_store_digest(
                self.hass,
                {CONF_USERNAME: self._username, CONF_FAMILY_ID: family_id},
                identity=config_entry_unique_id(self._user_id, family_id),
                digest=self._require_digest(),
            )
        except CredentialError:
            return self.async_show_form(
                step_id="devices",
                data_schema=device_schema(self._devices),
                errors={"base": "secret_error"},
            )
        return self.async_create_entry(
            title=f"{self._username} - {self._family_name}",
            data=data,
            options={CONF_SELECTED_DEVICE_IDS: selected},
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, object],
    ) -> FlowResult:
        self._username = str(entry_data.get(CONF_USERNAME) or "")

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: JsonObject | None = None,
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            password = str(user_input.get(CONF_PASSWORD) or "")
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            if entry is None:
                return self.async_abort(reason="reauth_entry_missing")
            digest = ProtocolDigest.from_password(password)
            result = await validate_account(
                async_get_clientsession(self.hass),
                self._username,
                digest,
                str(entry.data.get(CONF_FAMILY_ID) or "") or None,
            )
            if result.error:
                errors["base"] = result.error
            else:
                try:
                    data = await async_store_digest(
                        self.hass,
                        entry.data,
                        identity=entry.entry_id,
                        digest=digest,
                    )
                except CredentialError:
                    errors["base"] = "secret_error"
                else:
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def _probe_gateway_login(
        self,
        gateway_ips: Mapping[str, str],
    ) -> bool:
        """Probe one LAN gateway login to validate the password.

        Cloud discovery and LAN login are separate protocol operations.
        This checks whether the gateway accepts the same credentials locally.
        Only an explicit gateway rejection is treated as an auth failure;
        network or timeout errors do not block the configuration flow.
        """
        return await probe_gateway_credentials(
            self._username,
            self._require_digest(),
            gateway_ips,
        )

    def _require_digest(self) -> ProtocolDigest:
        # The user step stores the digest before any later step can run.
        if self._digest is None:
            raise RuntimeError("Credentials were not validated before this step")
        return self._digest
