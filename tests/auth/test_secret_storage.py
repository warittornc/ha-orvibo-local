"""Secret-file persistence keeps reusable credentials out of config-entry data."""

import json
from types import SimpleNamespace

import pytest
import yaml

from custom_components.orvibo_lan.auth import secrets as storage
from custom_components.orvibo_lan.auth.credentials import ProtocolDigest
from custom_components.orvibo_lan.auth.exceptions import CredentialSecretError

DIGEST = "5F4DCC3B5AA765D61D8327DEB882CF99"
NEXT_DIGEST = "0" * 32


@pytest.fixture
def yaml_adapter(monkeypatch):
    # Use a real YAML parser locally; production uses Home Assistant's YAML loader.
    monkeypatch.setattr(storage, "_yaml_values", lambda p: yaml.safe_load(p.read_text()) or {})
    monkeypatch.setattr(
        storage, "_secret_value", lambda p, key: storage._yaml_values(p / "secrets.yaml")[key]
    )


@pytest.mark.asyncio
async def test_store_returns_only_reference_and_resolves_on_startup(tmp_path, yaml_adapter):
    async def executor(fn, *args):
        return fn(*args)

    hass = SimpleNamespace(
        config=SimpleNamespace(config_dir=str(tmp_path)), async_add_executor_job=executor
    )
    path = tmp_path / "secrets.yaml"
    path.write_text('# Preserve this comment\nother_password: "unchanged"\n')
    original = {"username": "account", "password_hash": DIGEST, "family_id": "home"}
    result = await storage.async_migrate_to_secret(hass, original, identity="entry")
    assert "password" not in result and "password_hash" not in result
    assert result["username"] == "account" and result["family_id"] == "home"
    assert DIGEST not in json.dumps(result)
    assert path.read_text().startswith('# Preserve this comment\nother_password: "unchanged"\n')
    assert path.stat().st_mode & 0o777 == 0o600
    assert await storage.async_resolve_digest(hass, result) == ProtocolDigest(DIGEST)
    assert original["password_hash"] == DIGEST
    # Restart/idempotent migration does not append a duplicate key.
    before = path.read_bytes()
    assert await storage.async_migrate_to_secret(hass, result, identity="entry") == result
    assert path.read_bytes() == before
    rotated = await storage.async_store_digest(
        hass, result, identity="entry", digest=ProtocolDigest(NEXT_DIGEST)
    )
    assert rotated == result
    assert await storage.async_resolve_digest(hass, rotated) == ProtocolDigest(NEXT_DIGEST)
    assert DIGEST not in path.read_text()


def test_writer_refuses_to_overwrite_unmanaged_secret(tmp_path, yaml_adapter):
    path = tmp_path / "secrets.yaml"
    path.write_text(f'custom_key: "{DIGEST}"\n')
    before = path.read_bytes()
    with pytest.raises(CredentialSecretError):
        storage._write_secret(tmp_path, "custom_key", NEXT_DIGEST)
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_missing_secret_never_falls_back_to_embedded_digest(tmp_path, yaml_adapter):
    async def executor(fn, *args):
        return fn(*args)

    hass = SimpleNamespace(
        config=SimpleNamespace(config_dir=str(tmp_path)), async_add_executor_job=executor
    )
    (tmp_path / "secrets.yaml").write_text("{}\n")
    with pytest.raises(CredentialSecretError):
        await storage.async_resolve_digest(
            hass, {"password_hash_secret": "missing", "password_hash": DIGEST}
        )


def test_invalid_yaml_does_not_leak_file_contents_or_replace_file(tmp_path, yaml_adapter):
    path = tmp_path / "secrets.yaml"
    path.write_text("sensitive: [PRIVATE-PASSWORD\n")
    before = path.read_bytes()
    with pytest.raises(CredentialSecretError) as error:
        storage._write_secret(tmp_path, "orvibo_test", DIGEST)
    assert "PRIVATE-PASSWORD" not in str(error.value)
    assert path.read_bytes() == before


def test_concurrent_migrations_preserve_both_secrets(tmp_path, yaml_adapter):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(storage._write_secret, tmp_path, key, DIGEST) for key in ("one", "two")
        ]
        for future in futures:
            future.result()
    assert storage._yaml_values(tmp_path / "secrets.yaml") == {"one": DIGEST, "two": DIGEST}


def test_symlinked_secrets_file_is_not_replaced(tmp_path, yaml_adapter):
    target = tmp_path / "external.yaml"
    target.write_text('other: "unchanged"\n')
    (tmp_path / "secrets.yaml").symlink_to(target)
    with pytest.raises(CredentialSecretError):
        storage._write_secret(tmp_path, "key", DIGEST)
    assert target.read_text() == 'other: "unchanged"\n'


def test_atomic_replace_failure_preserves_file_and_cleans_temporary(
    tmp_path, yaml_adapter, monkeypatch
):
    path = tmp_path / "secrets.yaml"
    path.write_text('other: "unchanged"\n')
    before = path.read_bytes()

    def fail(*args):
        raise OSError("not writable")

    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(CredentialSecretError):
        storage._write_secret(tmp_path, "key", DIGEST)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".orvibo-secret-*"))
