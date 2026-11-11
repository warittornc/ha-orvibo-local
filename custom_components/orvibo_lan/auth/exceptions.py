"""Credential error family shared by credential preparation, secret storage, and callers.

Messages never include credential values, digests, or resolved secrets.
"""

from ..exceptions import OrviboLanError


class CredentialError(OrviboLanError, ValueError):
    """Base error for credentials that cannot be prepared, resolved, or stored."""


class InvalidCredentialError(CredentialError):
    """A password or protocol digest is missing or malformed."""


class CredentialSecretError(CredentialError):
    """A secret could not be resolved or safely persisted."""
