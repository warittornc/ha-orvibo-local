"""Production-path tests for configuration and family selection flows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.orvibo_lan.auth.credentials import ProtocolDigest
from custom_components.orvibo_lan.auth.secrets import SECRET_KEY, async_resolve_digest
from custom_components.orvibo_lan.const import (
    CONF_FAMILY_ID,
    CONF_PASSWORD,
    CONF_PASSWORD_HASH,
    CONF_SELECTED_DEVICE_IDS,
    CONF_USERNAME,
)
from custom_components.orvibo_lan.devices.catalog import build_home_snapshot
from custom_components.orvibo_lan.flows import config_flow, options_flow, selection, validation


class FakeCloudClient:
    def __init__(self) -> None:
        self.family_list = [
            {"familyId": "family-1", "familyName": "Home"},
            {"familyId": "family-2", "familyName": "Office"},
        ]
        self.family_name = "Home"
        self.family_id = "family-1"
        self.user_id = "user-1"

    async def login(self) -> None:
        return None

    async def fetch_home(self):
        return build_home_snapshot(
            [
                {"deviceId": "mixpad", "deviceType": 114, "uid": "gateway-1"},
                {
                    "deviceId": "device-1",
                    "deviceType": 1,
                    "uid": "gateway-1",
                    "deviceName": "Desk light",
                    "roomId": "room-1",
                },
            ],
            {"device-1": {"deviceId": "device-1", "value1": 0}},
            [{"uid": "gateway-1", "localStaticIP": "192.168.1.2"}],
            [{"roomId": "room-1", "roomName": "Office"}],
        )


def test_selection_helpers_use_actual_production_functions(secret_hass) -> None:
    devices = [
        {"deviceId": "one", "deviceName": "Light", "roomName": "Office"},
        {"deviceId": "two", "deviceName": "Sensor", "roomName": ""},
    ]

    assert selection.device_label("one", "Light", "Office") == "Light [Office]"
    assert selection.validated_selection(["two", "missing"], devices) == ["two"]
    assert selection.validated_selection("one", devices) == []


def test_options_flow_keeps_config_entry_without_setting_read_only_property(secret_hass) -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "account",
            CONF_PASSWORD: "password",
            CONF_FAMILY_ID: "family-1",
        },
        options={CONF_SELECTED_DEVICE_IDS: ["device-1"]},
    )

    flow = config_flow.OrviboLanConfigFlow.async_get_options_flow(entry)

    assert flow._config_entry is entry


@pytest.mark.asyncio
async def test_options_flow_menu_exposes_reauth_and_devices(secret_hass) -> None:
    entry = SimpleNamespace(entry_id="entry-1", data={}, options={})
    flow = options_flow.OrviboLanOptionsFlow(entry)

    result = await flow.async_step_init()

    assert result["type"] == "menu"
    assert result["menu_options"] == ["reauth", "devices", "secrets"]


@pytest.mark.asyncio
async def test_options_reauth_updates_same_entry_and_preserves_options(secret_hass) -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "account",
            CONF_PASSWORD: "old-password",
            CONF_FAMILY_ID: "family-1",
            "unrelated": "preserve-me",
        },
        options={CONF_SELECTED_DEVICE_IDS: ["device-1"]},
    )
    update_entry = MagicMock()
    flow = options_flow.OrviboLanOptionsFlow(entry)
    flow.hass = secret_hass(
        SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
    )
    original_options = dict(entry.options)

    with (
        patch.object(validation, "CloudClient", return_value=FakeCloudClient()),
        patch.object(options_flow, "async_get_clientsession", return_value=object()),
        patch.object(
            validation,
            "load_devices",
            new=AsyncMock(return_value=([], {"gateway-1": "192.168.1.2"})),
        ),
        patch.object(
            validation,
            "probe_gateway_credentials",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await flow.async_step_reauth({CONF_PASSWORD: "new-password"})

    assert result == {"type": "abort", "reason": "reauth_successful"}
    update_entry.assert_called_once()
    assert update_entry.call_args.args[0] is entry
    updated_data = update_entry.call_args.kwargs["data"]
    assert CONF_PASSWORD not in updated_data
    assert CONF_PASSWORD_HASH not in updated_data
    assert await async_resolve_digest(flow.hass, updated_data) == ProtocolDigest.from_password(
        "new-password"
    )
    assert updated_data[CONF_FAMILY_ID] == "family-1"
    assert updated_data["unrelated"] == "preserve-me"
    assert entry.options == original_options


@pytest.mark.asyncio
async def test_options_reauth_rejection_does_not_modify_entry(secret_hass) -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "account",
            CONF_PASSWORD: "old-password",
            CONF_FAMILY_ID: "family-1",
        },
        options={CONF_SELECTED_DEVICE_IDS: ["device-1"]},
    )
    update_entry = MagicMock()
    flow = options_flow.OrviboLanOptionsFlow(entry)
    flow.hass = secret_hass(
        SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
    )

    with (
        patch.object(validation, "CloudClient", return_value=FakeCloudClient()),
        patch.object(options_flow, "async_get_clientsession", return_value=object()),
        patch.object(
            validation,
            "load_devices",
            new=AsyncMock(return_value=([], {"gateway-1": "192.168.1.2"})),
        ),
        patch.object(
            validation,
            "probe_gateway_credentials",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await flow.async_step_reauth({CONF_PASSWORD: "wrong"})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "gateway_auth_failed"}
    update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_user_flow_selects_family_devices_and_scopes_unique_id(secret_hass) -> None:
    client = FakeCloudClient()
    flow = config_flow.OrviboLanConfigFlow()
    flow.hass = secret_hass(SimpleNamespace())

    with (
        patch.object(validation, "CloudClient", return_value=client),
        patch.object(config_flow, "async_get_clientsession", return_value=object()),
        patch.object(
            validation,
            "probe_gateway_credentials",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await flow.async_step_user({CONF_USERNAME: "account", CONF_PASSWORD: "password"})
        assert result["step_id"] == "select_family"

        result = await flow.async_step_select_family({CONF_FAMILY_ID: "family-2"})
        assert result["step_id"] == "devices"

        result = await flow.async_step_devices({CONF_SELECTED_DEVICE_IDS: ["device-1"]})

    assert result["type"] == "create_entry"
    assert result["title"] == "account - Office"
    assert result["data"][CONF_FAMILY_ID] == "family-2"
    assert CONF_PASSWORD not in result["data"]
    assert CONF_PASSWORD_HASH not in result["data"]
    assert SECRET_KEY in result["data"]
    assert await async_resolve_digest(flow.hass, result["data"]) == ProtocolDigest.from_password("password")
    assert result["options"] == {CONF_SELECTED_DEVICE_IDS: ["device-1"]}
    assert "cloud_region" not in result["data"]
    assert flow.unique_id == "global:user-1:family-2"


@pytest.mark.asyncio
async def test_user_flow_rejects_empty_credentials(secret_hass) -> None:
    flow = config_flow.OrviboLanConfigFlow()
    flow.hass = secret_hass(SimpleNamespace())

    result = await flow.async_step_user({CONF_USERNAME: "", CONF_PASSWORD: ""})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "empty_username_or_password"}


@pytest.mark.asyncio
async def test_options_device_refresh_has_no_region_configuration(secret_hass):
    data = {CONF_USERNAME: "account", CONF_PASSWORD: "password", CONF_FAMILY_ID: "family-1"}
    entry = SimpleNamespace(entry_id="entry-1", data=data, options={})
    flow = options_flow.OrviboLanOptionsFlow(entry)
    flow.hass = secret_hass(SimpleNamespace())
    with (
        patch.object(options_flow, "CloudClient", return_value=FakeCloudClient()) as factory,
        patch.object(options_flow, "async_get_clientsession", return_value=object()),
    ):
        result = await flow.async_step_devices()
    assert result["step_id"] == "devices"
    assert "cloud_region" not in factory.call_args.kwargs


@pytest.mark.asyncio
async def test_cloud_success_and_gateway_rejection_have_distinct_error(secret_hass):
    client = FakeCloudClient()
    client.family_list = client.family_list[:1]
    flow = config_flow.OrviboLanConfigFlow()
    flow.hass = secret_hass(SimpleNamespace())
    with (
        patch.object(validation, "CloudClient", return_value=client),
        patch.object(config_flow, "async_get_clientsession", return_value=object()),
        patch.object(validation, "probe_gateway_credentials", new=AsyncMock(return_value=False)),
    ):
        result = await flow.async_step_user({CONF_USERNAME: "account", CONF_PASSWORD: "password"})
    assert result["errors"] == {"base": "gateway_auth_failed"}


@pytest.mark.asyncio
async def test_secret_backed_reauth_rotates_file_and_reloads_without_storing_digest(secret_hass):
    from custom_components.orvibo_lan.auth.secrets import async_store_digest

    update = MagicMock()
    reload_entry = AsyncMock()
    hass = secret_hass(
        SimpleNamespace(
            config_entries=SimpleNamespace(
                async_update_entry=update,
                async_reload=reload_entry,
            )
        )
    )
    data = await async_store_digest(
        hass, {CONF_USERNAME: "account"}, identity="entry", digest=ProtocolDigest.from_password("old")
    )
    entry = SimpleNamespace(entry_id="entry", data=data, options={})
    flow = options_flow.OrviboLanOptionsFlow(entry)
    flow.hass = hass
    with (
        patch.object(validation, "CloudClient", return_value=FakeCloudClient()),
        patch.object(options_flow, "async_get_clientsession", return_value=object()),
        patch.object(validation, "load_devices", new=AsyncMock(return_value=([], {}))),
        patch.object(validation, "probe_gateway_credentials", new=AsyncMock(return_value=True)),
    ):
        result = await flow.async_step_reauth({CONF_PASSWORD: "new"})
    assert result["reason"] == "reauth_successful"
    assert await async_resolve_digest(hass, entry.data) == ProtocolDigest.from_password("new")
    assert CONF_PASSWORD not in entry.data and CONF_PASSWORD_HASH not in entry.data
    update.assert_not_called()
    reload_entry.assert_awaited_once_with("entry")


@pytest.mark.asyncio
async def test_config_reauth_persists_reference_and_explicitly_reloads(secret_hass):
    from custom_components.orvibo_lan.auth.secrets import async_store_digest

    update = MagicMock()
    reload_entry = AsyncMock()
    hass = secret_hass(
        SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update, async_reload=reload_entry)
        )
    )
    data = await async_store_digest(
        hass,
        {CONF_USERNAME: "account", CONF_FAMILY_ID: "family-1"},
        identity="entry",
        digest=ProtocolDigest.from_password("old"),
    )
    entry = SimpleNamespace(
        entry_id="entry", data=data, options={CONF_SELECTED_DEVICE_IDS: ["device-1"]}
    )
    hass.config_entries.async_get_entry = lambda entry_id: entry
    flow = config_flow.OrviboLanConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": "entry"}
    await flow.async_step_reauth(entry.data)
    with (
        patch.object(validation, "CloudClient", return_value=FakeCloudClient()),
        patch.object(validation, "probe_gateway_credentials", new=AsyncMock(return_value=True)),
        patch.object(config_flow, "async_get_clientsession", return_value=object()),
    ):
        result = await flow.async_step_reauth_confirm({CONF_PASSWORD: "new"})
    assert result["reason"] == "reauth_successful"
    updated = update.call_args.kwargs["data"]
    assert updated[SECRET_KEY] == data[SECRET_KEY]
    assert CONF_PASSWORD not in updated and CONF_PASSWORD_HASH not in updated
    assert await async_resolve_digest(hass, updated) == ProtocolDigest.from_password("new")
    assert entry.options == {CONF_SELECTED_DEVICE_IDS: ["device-1"]}
    reload_entry.assert_awaited_once_with("entry")


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_secret_selection_validates_before_changing_reference(secret_hass, accepted):
    from custom_components.orvibo_lan.auth.secrets import async_store_digest

    update = MagicMock()
    hass = secret_hass(SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update)))
    original = await async_store_digest(
        hass, {CONF_USERNAME: "account"}, identity="old", digest=ProtocolDigest.from_password("old")
    )
    replacement = await async_store_digest(
        hass, {CONF_USERNAME: "account"}, identity="new", digest=ProtocolDigest.from_password("new")
    )
    entry = SimpleNamespace(entry_id="entry", data=original, options={})
    flow = options_flow.OrviboLanOptionsFlow(entry)
    flow.hass = hass
    with (
        patch.object(validation, "CloudClient", return_value=FakeCloudClient()),
        patch.object(validation, "probe_gateway_credentials", new=AsyncMock(return_value=accepted)),
        patch.object(options_flow, "async_get_clientsession", return_value=object()),
    ):
        result = await flow.async_step_secrets({SECRET_KEY: replacement[SECRET_KEY]})
    if accepted:
        assert result["reason"] == "secret_updated"
        updated = update.call_args.kwargs["data"]
        assert updated[SECRET_KEY] == replacement[SECRET_KEY]
        assert CONF_PASSWORD not in updated and CONF_PASSWORD_HASH not in updated
    else:
        assert result["errors"] == {"base": "gateway_auth_failed"}
        update.assert_not_called()
    assert entry.data == original
