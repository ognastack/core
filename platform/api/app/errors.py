"""Domain errors; the HTTP layer maps each to a status code and error code."""


class PlatformError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(PlatformError):
    status_code = 404
    code = "not_found"


class Forbidden(PlatformError):
    status_code = 403
    code = "forbidden"


class QuotaExceeded(PlatformError):
    status_code = 403
    code = "quota_exceeded"


class Conflict(PlatformError):
    status_code = 409
    code = "conflict"


class InvalidRequest(PlatformError):
    status_code = 422
    code = "invalid_request"


class ProviderError(PlatformError):
    """The infrastructure provider rejected or failed a request."""

    status_code = 502
    code = "provider_error"

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class RepositoryError(PlatformError):
    """The data store (Hasura/Postgres) failed unexpectedly."""

    status_code = 503
    code = "repository_error"
