"""Reusable spreadsheet import entry points.

The package owns file reading, profile parsing, and pre-commit validation.
HTTP routes and database writers stay outside this facade so future profiles
can reuse the same upload and safety layers without changing this contract.
"""

from app.spreadsheet_import.errors import SpreadsheetFormatError
from app.spreadsheet_import.field_parser import (
    parse_field_document,
    parse_field_input_spreadsheet,
)
from app.spreadsheet_import.file_reader import read_spreadsheet
from app.spreadsheet_import.validation import (
    validate_field_table,
    validate_field_workbook,
)

SPREADSHEET_PROFILE_FIELD = "field"


def parse_spreadsheet(
    data: bytes,
    filename: str | None = None,
    profile: str = SPREADSHEET_PROFILE_FIELD,
) -> dict:
    """Read, parse, and validate one normalized spreadsheet result."""
    if profile != SPREADSHEET_PROFILE_FIELD:
        raise SpreadsheetFormatError(
            f"Spreadsheet import profile {profile!r} is not available."
        )

    document = read_spreadsheet(data, filename)
    result = parse_field_document(document)

    if document.format.value == "csv":
        validate_field_table(result["dataset"], result["rows"])
        return {
            "source_format": document.format.value,
            "dataset": result["dataset"],
            "rows": result["rows"],
        }

    validate_field_workbook(result)
    return {
        "source_format": document.format.value,
        "dataset": "field_workbook",
        "workbook": result,
    }


__all__ = [
    "SPREADSHEET_PROFILE_FIELD",
    "parse_field_document",
    "parse_field_input_spreadsheet",
    "parse_spreadsheet",
    "validate_field_table",
    "validate_field_workbook",
]
