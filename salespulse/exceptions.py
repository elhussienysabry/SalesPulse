"""Domain exceptions for SalesPulse.

The CLI converts these into concise error messages and non-zero exit codes so
users never see a raw traceback for expected data problems.
"""


class SalesPulseError(Exception):
    """Base class for all expected SalesPulse errors."""


class ConfigurationError(SalesPulseError):
    """Invalid or missing application configuration."""


class SchemaError(SalesPulseError):
    """A source file does not match the expected dataset schema."""


class InputFileError(SalesPulseError):
    """A source file is missing, empty, too large, or otherwise unreadable."""


class ValidationError(SalesPulseError):
    """Business validation failed outside the row-rejection workflow."""


class ImportExecutionError(SalesPulseError):
    """An import failed and was rolled back."""


class DatabaseNotInitializedError(SalesPulseError):
    """The database is missing the SalesPulse schema."""


class ReportError(SalesPulseError):
    """An analytical report could not be produced."""
