"""Validation gates for parsed field-input workbooks.

These checks run before any database service is called. The database still
owns final identity and relationship checks, but malformed or duplicated
source rows never reach it.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from app.spreadsheet_import.datasets import FIELD_DATASETS, get_dataset
from app.spreadsheet_import.errors import SpreadsheetValidationError


def _identity(row: Dict[str, Any], columns: tuple[str, ...]) -> tuple:
    return tuple(_canonical_key(row.get(column)) for column in columns)


def _canonical_key(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, bool):
        return f"bool:{value}"
    if isinstance(value, (int, float)):
        try:
            return str(Decimal(str(value)).normalize())
        except InvalidOperation:
            return str(value)
    return str(value)


def _decimal(value: Any, field: str, label: str, index: int) -> Decimal:
    if isinstance(value, bool):
        raise SpreadsheetValidationError(
            f"{label} row {index} has a non-numeric {field}."
        )
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SpreadsheetValidationError(
            f"{label} row {index} has an invalid {field}."
        ) from None
    if not result.is_finite():
        raise SpreadsheetValidationError(
            f"{label} row {index} has a non-finite {field}."
        )
    return result


def _reject_duplicates(
    rows: list[Dict[str, Any]],
    key_columns: tuple[str, ...],
    label: str,
) -> None:
    # Database uniqueness is keyed by location and depth, not by the
    # descriptive payload. Reject a repeated key even when the other cells
    # differ, otherwise the first database write would fail halfway through
    # a batch that should have been rejected during validation.
    identities = Counter(_identity(row, key_columns) for row in rows)
    duplicate = next((identity for identity, count in identities.items() if count > 1), None)
    if duplicate is not None:
        raise SpreadsheetValidationError(
            f"Duplicate {label} rows were found in the spreadsheet. "
            "Keep one source row for each key and try again."
        )


def _validate_intervals(rows: list[Dict[str, Any]], label: str) -> None:
    for index, row in enumerate(rows, start=1):
        depth_from = _decimal(row.get("depth_from"), "depth_from", label, index)
        depth_to = _decimal(row.get("depth_to"), "depth_to", label, index)
        if depth_to <= depth_from:
            raise SpreadsheetValidationError(
                f"{label} row {index} must have depth_to greater than depth_from."
            )


def _validate_spt(rows: list[Dict[str, Any]]) -> None:
    for index, row in enumerate(rows, start=1):
        depth = _decimal(row.get("spt_depth"), "spt_depth", "SPT", index)
        if depth < 0:
            raise SpreadsheetValidationError(
                f"SPT row {index} has a negative depth."
            )


def _validate_shape(spec, rows: list[Dict[str, Any]]) -> None:
    if spec.kind == "interval":
        _validate_intervals(rows, spec.label)
    else:
        _validate_spt(rows)


def validate_field_workbook(workbook: Dict[str, Any]) -> None:
    """Reject invalid or duplicate source rows before the first write."""
    for spec in FIELD_DATASETS.values():
        _validate_shape(spec, workbook.get(spec.name, []))
    for spec in FIELD_DATASETS.values():
        _reject_duplicates(
            workbook.get(spec.name, []), spec.key_columns, spec.label
        )


def validate_field_table(dataset: str, rows: list[Dict[str, Any]]) -> None:
    """Validate one normalized CSV dataset before any append commit."""
    if not rows:
        raise SpreadsheetValidationError(
            f"No data rows were supplied for the {dataset} table."
        )
    spec = get_dataset(dataset)
    _validate_shape(spec, rows)
    _reject_duplicates(rows, spec.key_columns, spec.label)
