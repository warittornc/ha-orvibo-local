"""Credential preparation and migration never retain or expose the original password."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.orvibo_lan.auth.credentials import ProtocolDigest, inline_digest
from custom_components.orvibo_lan.auth.exceptions import (
    CredentialError,
    CredentialSecretError,
    InvalidCredentialError,
)
from custom_components.orvibo_lan.auth.secrets import SECRET_KEY, async_resolve_digest
from custom_components.orvibo_lan.exceptions import OrviboLanError
from custom_components.orvibo_lan.runtime.lifecycle import async_migrate_entry, async_setup_entry

DIGEST = "5F4DCC3B5AA765D61D8327DEB882CF99"


def test_digest_is_derived_once_and_normalized():
    assert ProtocolDigest.from_password("password") == ProtocolDigest(DIGEST)
    assert ProtocolDigest(DIGEST.lower()).value == DIGEST


def test_digest_text_never_appears_in_repr_or_str():
    digest = ProtocolDigest(DIGEST)
    assert DIGEST not in repr(digest)
    assert DIGEST not in str(digest)
    assert DIGEST not in f"{digest}"


def test_inline_digest_prefers_stored_digest_over_plaintext():
    assert inline_digest({"password_hash": DIGEST.lower(), "password": "old"}).value == DIGEST
    assert inline_digest({"password": "password"}).value == DIGEST


@pytest.mark.parametrize("data", [{}, {"password": ""}, {"password_hash": "private-invalid-value"}])
def test_invalid_credentials_fail_without_exposing_values(data):
    with pytest.raises(InvalidCredentialError) as error:
        inline_digest(data)
    assert "private-invalid-value" not in str(error.value)


def test_credential_family_is_rooted_in_the_integration_error_tree():
    assert issubclass(CredentialError, OrviboLanError)
    assert issubclass(InvalidCredentialError, CredentialError)
    assert issubclass(CredentialSecretError, CredentialError)


@pytest.mark.asyncio
async def test_malformed_inline_credential_requests_reauthentication():
    entry = SimpleNamespace(data={"username": "account", "password_hash": "not-a-digest"})
    with pytest.raises(Exception) as error:
        await async_setup_entry(SimpleNamespace(), entry)
    assert type(error.value).__name__ == "FakeConfigEntryAuthFailed"


@pytest.mark.asyncio
async def test_version_three_entry_migrates_without_changing_identity_or_options(secret_hass):
    update = MagicMock()
    entry = SimpleNamespace(
        version=3,
        data={"username": "account", "password": "password", "family_id": "home"},
        options={"selected_device_ids": ["light"]},
        unique_id="existing-identity",
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    secret_hass(hass)
    assert await async_migrate_entry(hass, entry)
    kwargs = update.call_args.kwargs
    assert kwargs["version"] == 5
    assert "password_hash" not in kwargs["data"]
    assert SECRET_KEY in kwargs["data"]
    assert await async_resolve_digest(hass, kwargs["data"]) == ProtocolDigest(DIGEST)
    assert "password" not in kwargs["data"]
    assert kwargs["options"] == entry.options
    assert "unique_id" not in kwargs


@pytest.mark.asyncio
async def test_failed_secret_migration_does_not_remove_existing_credential():
    update = MagicMock()
    original = {"username": "account", "password_hash": DIGEST}
    entry = SimpleNamespace(version=4, data=original, options={}, entry_id="entry")
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    with patch(
        "custom_components.orvibo_lan.runtime.lifecycle.async_migrate_to_secret",
        new=AsyncMock(side_effect=CredentialSecretError("Unable to update secrets.yaml")),
    ):
        assert not await async_migrate_entry(hass, entry)
    update.assert_not_called()
    assert entry.data == original


@pytest.mark.asyncio
async def test_malformed_inline_credential_fails_migration_without_update():
    update = MagicMock()
    entry = SimpleNamespace(
        version=4, data={"password_hash": "bad"}, options={}, entry_id="entry"
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    assert not await async_migrate_entry(hass, entry)
    update.assert_not_called()
