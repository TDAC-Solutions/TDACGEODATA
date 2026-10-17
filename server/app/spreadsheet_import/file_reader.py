"""Format-neutral workbook reading for spreadsheet import profiles.

A reader returns all sheets in one in-memory document. Parsing profiles then
choose the sheet they understand. This keeps file format handling separate
from business mapping and prevents a future CSV parser from duplicating the
upload path.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from enum import Enum
from typing import List

from openpyxl import load_workbook

from app.spreadsheet_import.errors import SpreadsheetFormatError


class SpreadsheetFormat(str, Enum):
    XLSX = "xlsx"
    XLSM = "xlsm"
    CSV = "csv"


MAX_ROWS = 2000
MAX_COLS = 64


@dataclass(frozen=True)
class SpreadsheetSheet:
    name: str
    rows: List[List[object]]


@dataclass(frozen=True)
class SpreadsheetDocument:
    format: SpreadsheetFormat
    filename: str
    sheets: List[SpreadsheetSheet]


def _extension(filename: str | None) -> str:
    """Extension without the dot, lowercased. Empty when there is none.

    A leading dot in a bare name (".hidden") is not an extension, so the
    dot must appear somewhere after the first character.
    """
    if not filename:
        return ""
    name = filename.rsplit("/", 1)[-1]
    if "." not in name[1:]:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def _read_csv(data: bytes, filename: str | None) -> SpreadsheetDocument:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            raise SpreadsheetFormatError(
                "This CSV file is not valid UTF-8 or Windows text. "
                "Save it as UTF-8 CSV and try again."
            ) from None

    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS:
                raise SpreadsheetFormatError(
                    f"This CSV has more than {MAX_ROWS} rows. Split it and "
                    "import the parts separately, rather than having rows "
                    "dropped silently."
                )
            if len(row) > MAX_COLS:
                raise SpreadsheetFormatError(
                    f"This CSV has a row with more than {MAX_COLS} columns. "
                    "Remove the extra columns and try again."
                )
            rows.append(list(row))
    except csv.Error:
        raise SpreadsheetFormatError("This CSV file could not be read.") from None

    if not rows:
        raise SpreadsheetFormatError("This CSV file is empty.")

    return SpreadsheetDocument(
        format=SpreadsheetFormat.CSV,
        filename=filename or "upload.csv",
        sheets=[SpreadsheetSheet(name="CSV", rows=rows)],
    )


def _read_xlsx(
    data: bytes,
    filename: str | None,
    fmt: SpreadsheetFormat = SpreadsheetFormat.XLSX,
) -> SpreadsheetDocument:
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise SpreadsheetFormatError(
            "This file could not be opened as an Excel workbook. "
            "Save it as .xlsx and try again."
        ) from None

    sheets = []
    for worksheet in workbook.worksheets:
        # Refuse rather than silently clip. min() would have quietly dropped
        # everything past the cap and still reported success, which is data
        # loss the field crew would not notice until the report was wrong.
        if worksheet.max_row and worksheet.max_row > MAX_ROWS:
            workbook.close()
            raise SpreadsheetFormatError(
                f"Sheet '{worksheet.title}' has {worksheet.max_row} rows, "
                f"more than the {MAX_ROWS}-row limit. Split the workbook and "
                "import the parts separately."
            )
        if worksheet.max_column and worksheet.max_column > MAX_COLS:
            workbook.close()
            raise SpreadsheetFormatError(
                f"Sheet '{worksheet.title}' has {worksheet.max_column} "
                f"columns, more than the {MAX_COLS}-column limit. Remove the "
                "extra columns and try again."
            )
        rows = [
            list(row)
            for row in worksheet.iter_rows(
                min_row=1,
                max_row=worksheet.max_row,
                max_col=worksheet.max_column,
                values_only=True,
            )
        ]
        sheets.append(SpreadsheetSheet(name=worksheet.title, rows=rows))

    workbook.close()
    return SpreadsheetDocument(
        format=fmt,
        filename=filename or "upload.xlsx",
        sheets=sheets,
    )


def read_spreadsheet(data: bytes, filename: str | None = None) -> SpreadsheetDocument:
    """Read an uploaded .xlsx or .csv document into shared sheet objects."""
    if not data:
        raise SpreadsheetFormatError("The uploaded file is empty.")

    extension = _extension(filename)
    if not extension:
        # Backward-compatible byte-only entry points use .xlsx workbooks.
        # The HTTP route always has a filename, so real uploads remain
        # explicit and CSV is never guessed from arbitrary content.
        if data[:2] == b"PK":
            return _read_xlsx(data, filename)
        raise SpreadsheetFormatError(
            "The spreadsheet filename is missing or has no supported extension."
        )
    if extension == "csv":
        return _read_csv(data, filename)
    if extension in {"xlsx", "xlsm"}:
        # The bytes are identical; only the declared format differs, so the
        # reader stamps the enum directly instead of rebuilding the document.
        return _read_xlsx(
            data,
            filename,
            SpreadsheetFormat.XLSM if extension == "xlsm" else SpreadsheetFormat.XLSX,
        )
    if extension == "xls":
        raise SpreadsheetFormatError(
            "The .xls format is no longer read directly. "
            "Convert the file to .xlsx or .csv and try again."
        )

    raise SpreadsheetFormatError(
        "Only .xlsx, .xlsm, and .csv spreadsheet files are supported."
    )
