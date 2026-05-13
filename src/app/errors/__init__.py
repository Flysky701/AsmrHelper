"""Application-layer errors."""


class AppError(Exception):
    """Base class for application-layer errors."""


class AppValidationError(AppError):
    """Raised when application input is invalid."""


class AppExecutionError(AppError):
    """Raised when an underlying operation fails."""


class ResourceUnavailableError(AppError):
    """Raised when a required runtime resource is unavailable."""


class ResourceValidationError(AppError):
    """Raised when required runtime resources or workspace paths are invalid."""
