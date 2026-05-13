"""Application-layer errors."""


class AppError(Exception):
    """Base class for application-layer errors."""


class AppValidationError(AppError):
    """Raised when application input is invalid."""


class AppExecutionError(AppError):
    """Raised when an underlying operation fails."""


class ResourceUnavailableError(AppError):
    """Raised when a required runtime resource is unavailable."""
