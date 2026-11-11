"""The protocol digest: the one credential value the integration passes around.

The digest is a reusable login secret, not a safe-to-publish password verifier.
Build it once at the edge (from a typed password or from storage) and pass the
value; downstream modules never re-normalize or guess which form they hold.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .exceptions import InvalidCredentialError

_DIGEST = re.compile(r"[A-Fa-f0-9]{32}\Z")


@dataclass(frozen=True, slots=True)
class ProtocolDigest:
    """A validated Orvibo protocol digest whose text never appears in ``repr`` or ``str``."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _DIGEST.fullmatch(self.value):
            raise InvalidCredentialError("Invalid protocol credential format")
        object.__setattr__(self, "value", self.value.upper())

    @classmethod
    def from_password(cls, password: str) -> ProtocolDigest:
        """Derive the digest from a plaintext password without retaining it."""
        if not isinstance(password, str):
            raise InvalidCredentialError("Missing protocol credentials")
        return cls(hashlib.md5(password.encode("utf-8")).hexdigest())  # noqa: S324

    def __str__(self) -> str:
        return "ProtocolDigest(***)"


def inline_digest(data: Mapping[str, Any]) -> ProtocolDigest:
    """Read the digest from a legacy config record that stores it inline.

    Prefers ``password_hash``; falls back to deriving it from a plaintext ``password``.
    """
    if "password_hash" in data:
        return ProtocolDigest(data["password_hash"])
    plaintext = data.get("password")
    if not isinstance(plaintext, str) or not plaintext:
        raise InvalidCredentialError("Missing protocol credentials")
    return ProtocolDigest.from_password(plaintext)
