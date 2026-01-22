"""
Custom exception classes for Quality Audit application.
"""


class QualityAuditError(Exception):
    """Base exception for all Quality Audit errors."""

    pass


class ValidationError(QualityAuditError):
    """Raised when validation fails."""

    pass


class FileProcessingError(QualityAuditError):
    """Raised when file processing fails."""

    pass


class SecurityError(QualityAuditError):
    """Raised when security checks fail."""

    pass


class ConfigurationError(QualityAuditError):
    """Raised when configuration is invalid or missing."""

    pass


class DataFormatError(QualityAuditError):
    """Raised when data format is invalid or unexpected."""

    pass
