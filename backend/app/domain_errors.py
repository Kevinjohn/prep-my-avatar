"""Explicit exceptions whose messages are safe to return to API clients."""


class PublicDomainError(Exception):
    """Base for an expected, client-actionable service failure."""

    status_code = 400
    error_code = 'domain_error'

    def __init__(self, message: str, *, error_code: str | None = None):
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class DomainValidationError(PublicDomainError, ValueError):
    """The caller supplied invalid data or requested an invalid operation."""

    status_code = 400
    error_code = 'validation_error'


class DomainConflictError(PublicDomainError, RuntimeError):
    """The request conflicts with current durable or runtime state."""

    status_code = 409
    error_code = 'conflict'
