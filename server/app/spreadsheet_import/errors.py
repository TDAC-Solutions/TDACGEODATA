"""User-facing errors shared by spreadsheet readers and import routes."""


class SpreadsheetImportError(Exception):
    """Base error whose message is safe to return to the frontend."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SpreadsheetFormatError(SpreadsheetImportError):
    """The upload is not a supported spreadsheet format."""


class SpreadsheetValidationError(SpreadsheetImportError):
    """Parsed data violates an import rule and must not reach the database."""
