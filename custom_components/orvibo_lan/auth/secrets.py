"""Resolve native Home Assistant secrets and maintain isolated digest entries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .credentials import ProtocolDigest, inline_digest
from .exceptions import CredentialSecretError

SECRET_KEY = "password_hash_secret"
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,127}\Z")
_WRITE_LOCK = threading.Lock()


def managed_secret_key(identity: str) -> str:
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return f"orvibo_lan_{suffix}_password_hash"


def _validate_key(key: object) -> str:
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise CredentialSecretError("Invalid credential secret key")
    return key


def _yaml_values(path: Path) -> Mapping[str, Any]:
    from homeassistant.util.yaml import load_yaml_dict

    return load_yaml_dict(str(path))


def _secret_value(config_dir: Path, key: str) -> object:
    from homeassistant.util.yaml import Secrets

    # A fresh resolver sees manual edits on every entry reload.
    return Secrets(config_dir).get(str(config_dir / "configuration.yaml"), key)


def _read_secret(config_dir: Path, key: str) -> ProtocolDigest:
    try:
        return ProtocolDigest(_secret_value(config_dir, _validate_key(key)))  # type: ignore[arg-type]
    except Exception:
        raise CredentialSecretError("Credential secret is missing or invalid") from None


def _write_secret(config_dir: Path, key: str, digest: str) -> None:
    """Preserve unrelated YAML bytes and only rotate our own marked entry."""
    key = _validate_key(key)
    digest = ProtocolDigest(digest).value
    path = config_dir / "secrets.yaml"
    temporary: str | None = None
    with _WRITE_LOCK:
        try:
            if path.is_symlink():
                raise CredentialSecretError("Update the linked secrets file manually")
            original = path.read_bytes() if path.exists() else b""
            text = original.decode("utf-8")
            values = _yaml_values(path) if path.exists() else {}
            begin = f"# BEGIN orvibo_lan {key}\n"
            end = f"# END orvibo_lan {key}\n"
            block = f"{begin}{key}: {json.dumps(digest)}\n{end}"
            if key in values:
                if values[key] == digest:
                    return
                old_block = f"{begin}{key}: {json.dumps(values[key])}\n{end}"
                if text.count(old_block) != 1:
                    raise CredentialSecretError("Update the existing secret manually")
                updated = text.replace(old_block, block, 1)
            else:
                # An empty flow mapping cannot be followed by block mapping entries.
                if not values:
                    text = re.sub(r"(?m)^\s*\{\}[ \t]*(?:#.*)?$", "", text)
                updated = text + ("\n" if text and not text.endswith("\n") else "") + block
            fd, temporary = tempfile.mkstemp(prefix=".orvibo-secret-", dir=config_dir)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(updated.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            # Validate the entire candidate before replacing the user's file.
            checked = _yaml_values(Path(temporary))
            if checked.get(key) != digest:
                raise CredentialSecretError("Credential secret could not be verified")
            if (path.read_bytes() if path.exists() else b"") != original:
                raise CredentialSecretError("Secrets file changed during the update; retry")
            os.replace(temporary, path)
            temporary = None
        except CredentialSecretError:
            raise
        except Exception:
            raise CredentialSecretError("Unable to safely update secrets.yaml") from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


def _reference_only(data: Mapping[str, Any], key: str) -> dict[str, Any]:
    result = dict(data)
    result[SECRET_KEY] = key
    result.pop("password", None)
    result.pop("password_hash", None)
    return result


async def async_resolve_digest(hass: Any, data: Mapping[str, Any]) -> ProtocolDigest:
    """Resolve the entry's digest without adding it to config-entry data.

    Raises :class:`CredentialError` for every failure: a missing or invalid secret
    reference, or a malformed inline credential on an entry that predates secrets.
    """
    if SECRET_KEY in data:
        key = _validate_key(data[SECRET_KEY])
        return await hass.async_add_executor_job(_read_secret, Path(hass.config.config_dir), key)
    return inline_digest(data)


async def async_store_digest(
    hass: Any, data: Mapping[str, Any], *, identity: str, digest: ProtocolDigest
) -> dict[str, Any]:
    """Write a new or rotated digest, verify it resolves, and return a reference-only record.

    Uses the entry's existing secret key when it has one, otherwise a managed key
    derived from ``identity``. A manually managed key is only accepted if it
    already holds ``digest``; it is never rewritten.
    """
    key = _validate_key(data.get(SECRET_KEY, managed_secret_key(identity)))
    config_dir = Path(hass.config.config_dir)
    await hass.async_add_executor_job(_write_secret, config_dir, key, digest.value)
    # Confirm native !secret lookup resolves the exact digest before dropping the inline copy.
    if await hass.async_add_executor_job(_read_secret, config_dir, key) != digest:
        raise CredentialSecretError("Credential secret verification failed")
    return _reference_only(data, key)


async def async_migrate_to_secret(
    hass: Any, data: Mapping[str, Any], *, identity: str
) -> dict[str, Any]:
    """Move an inline digest into secrets.yaml; idempotent for entries already migrated.

    An entry that already references a secret is only checked to still resolve.
    """
    if SECRET_KEY in data:
        await async_resolve_digest(hass, data)
        return _reference_only(data, data[SECRET_KEY])
    return await async_store_digest(hass, data, identity=identity, digest=inline_digest(data))

