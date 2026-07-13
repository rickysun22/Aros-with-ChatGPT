"""Custom exception hierarchy for AROS.

All project-specific errors derive from :class:`AROSError` so callers can catch
them broadly while still distinguishing configuration, data, and database
failures.
"""

from __future__ import annotations


class AROSError(Exception):
    """Base class for all AROS-specific errors."""


class ConfigError(AROSError):
    """Raised when configuration is missing or invalid."""


class DataError(AROSError):
    """Raised when data ingestion or validation fails."""


class DatabaseError(AROSError):
    """Raised when a database operation fails."""
