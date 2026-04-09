"""HTTP-mappable domain errors (centralized; map via FastAPI exception handler)."""

from __future__ import annotations

from typing import Union

from app.core.error_codes import ErrorCode

ErrorCodeLike = Union[ErrorCode, str]


class AppError(Exception):
    """Base for API errors with stable ``code`` and ``status_code``."""

    def __init__(self, *, status_code: int, code: ErrorCodeLike, message: str) -> None:
        self.status_code = int(status_code)
        self.code = str(code)
        self.message = str(message)
        super().__init__(message)


class InvalidClientIdError(AppError):
    def __init__(self, message: str = "Invalid tenant identifier") -> None:
        super().__init__(status_code=400, code=ErrorCode.INVALID_CLIENT_ID, message=message)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(status_code=401, code=ErrorCode.UNAUTHORIZED, message=message)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", *, code: ErrorCodeLike = ErrorCode.NOT_FOUND) -> None:
        super().__init__(status_code=404, code=code, message=message)


class EntityTenantMismatchError(AppError):
    """Write path: entity.client_id does not match requested tenant (fail-fast)."""

    def __init__(self, message: str = "Resource does not belong to tenant") -> None:
        super().__init__(status_code=400, code=ErrorCode.ENTITY_TENANT_MISMATCH, message=message)


class InvalidOperationError(AppError):
    """Caller violated repository contract (e.g. save without persisted id)."""

    def __init__(self, message: str, code: ErrorCodeLike = ErrorCode.INVALID_OPERATION) -> None:
        super().__init__(status_code=400, code=code, message=message)


class InvalidCredentialsError(AppError):
    def __init__(self, message: str = "Invalid email or password") -> None:
        super().__init__(status_code=401, code=ErrorCode.INVALID_CREDENTIALS, message=message)


class EmailAlreadyRegisteredError(AppError):
    def __init__(self, message: str = "Email is already registered") -> None:
        super().__init__(status_code=400, code=ErrorCode.EMAIL_ALREADY_REGISTERED, message=message)


class ClientNameAlreadyExistsError(AppError):
    """Registration: workspace/company name is already used by another organization."""

    def __init__(
        self,
        message: str = "This workspace or company name is already taken. Choose a different name.",
    ) -> None:
        super().__init__(status_code=409, code=ErrorCode.CLIENT_NAME_ALREADY_TAKEN, message=message)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden", code: ErrorCodeLike = ErrorCode.FORBIDDEN) -> None:
        super().__init__(status_code=403, code=code, message=message)


class InternalMisuseError(AppError):
    """Reserved for programmer mistakes (e.g. missing _internal_call); must not be used for user input."""

    def __init__(self, message: str = "Internal configuration error") -> None:
        super().__init__(status_code=500, code=ErrorCode.INTERNAL_MISUSE, message=message)


class ValidationError(AppError):
    """Input / upload validation (CSV, payloads)."""

    def __init__(self, message: str, code: ErrorCodeLike = ErrorCode.VALIDATION_ERROR) -> None:
        super().__init__(status_code=400, code=code, message=message)
