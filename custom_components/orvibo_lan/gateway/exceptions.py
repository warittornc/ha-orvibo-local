"""Gateway error family shared by transport and callers."""

from ..exceptions import OrviboLanError


class GatewayConnectionError(OrviboLanError):
    """Raised when a gateway connection cannot complete an operation."""

    def __init__(self, message: str, *, reason: str = "connection_error") -> None:
        super().__init__(message)
        self.reason = reason


class GatewayDisconnectedError(GatewayConnectionError):
    """Raised when an operation loses its transport."""


class GatewayRequestTimeoutError(GatewayConnectionError, TimeoutError):
    """Raised when a complete request exceeds its deadline."""


class GatewayLoginRejectedError(GatewayConnectionError):
    """Raised when the gateway explicitly rejects the login credentials."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
