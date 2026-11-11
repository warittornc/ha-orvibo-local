"""Cloud error family shared by transport and callers."""

from ..exceptions import OrviboLanError


class CloudClientError(OrviboLanError):
    """Base error for cloud API failures."""


class CloudTransportError(CloudClientError):
    """The cloud request could not be completed."""


class CloudHttpError(CloudClientError):
    """The cloud returned a non-success HTTP status."""

    def __init__(self, operation: str, status: int) -> None:
        super().__init__(f"{operation} returned HTTP {status}")
        self.operation = operation
        self.status = status


class CloudJsonError(CloudClientError):
    """The cloud response was not valid JSON."""


class CloudSchemaError(CloudClientError):
    """The cloud response did not match the expected schema."""


class CloudApiError(CloudClientError):
    """The cloud API reported an application-level error."""


class CloudAuthenticationError(CloudApiError):
    """Authentication failed or returned incomplete credentials."""
