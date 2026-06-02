from __future__ import annotations


class PlatformError(Exception):
    """Base exception for controlled platform errors."""


class DriverResolutionError(PlatformError):
    """Raised when a device cannot be mapped to a safe driver."""


class CapabilityError(PlatformError):
    """Raised when a requested operation is not supported by a device driver."""


class ApprovalRequiredError(PlatformError):
    """Raised when an operation tries to bypass the approval workflow."""


class SecretHandlingError(PlatformError):
    """Raised when a secret cannot be encrypted, decrypted, or masked safely."""


class SafetyError(PlatformError):
    """Raised when an execution request violates platform safety gates."""


class RealApplyDisabledError(SafetyError):
    """Raised when a runtime attempts real device interaction while real apply is disabled."""


class ConfigApplyNotAllowedError(SafetyError):
    """Raised when config-changing runtime operations are not allowed for a device decision."""


class NotFoundError(PlatformError):
    """Raised when a runtime object is not found."""


class ConflictError(PlatformError):
    """Raised when a requested state transition is not allowed."""
