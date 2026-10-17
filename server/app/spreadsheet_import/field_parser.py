"""Field-input spreadsheet parser.

Single reusable reader for the TDAC field input workbook (see
Input_sheet_V8_AGS_mapped.xlsx). Produces plain JSON-ready dicts that both
import flows reuse:

  - "Add New Project"  -> PROJ + first LOCA + GEOL + CORE + ISPT rows
  - "Overview / import" -> one extra LOCA + its GEOL + CORE + ISPT rows

Design constraints:
  - No new database columns anywhere; every value lands in an existing
    AGS column (see schemas/field_data.py for the fixed mapping).
  - Sheets are located by header tokens, not by name or position, so any
    renamed/reordered workbook variant still imports.
  - Parsing is capped by row limits and stops at the first blank data row,
    keeping memory and CPU proportional to real data instead of sheet
    dimensions (the example SPT sheet pads 20+ empty styled rows).
  - The in-sheet "AGS Equivalent" mapping legend column is documentation,
    never data; header-token matching ignores it naturally.
  - Depths travel as exact Decimal values: Excel stores numbers as binary
    floats (5.8 reads back as 5.7999999999999998...), and NUMERIC columns
    keep whatever they are handed, so converting via the shortest decimal
    repr keeps 5.8 as 5.8 and makes re-imports hit the same unique-
    constraint identity.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.spreadsheet_import.errors import (
    SpreadsheetFormatError,
    SpreadsheetImportError,
)
from app.spreadsheet_import.file_reader import MAX_ROWS, read_spreadsheet

# The reader caps rows while loading, but SpreadsheetDocument is a public
# dataclass that a caller can build directly, so the slice below stays as the
# parser's own guard. It reuses the reader's constant so the two cannot drift.
# Column width is bounded in file_reader; this parser never needs its own.

# Header tokens that identify each data sheet. A header row must contain
# ALL tokens of one group for the sheet to be treated as that data sheet.
_BORELOG_TOKENS = ("depth from", "depth to", "soil description")
_ROCK_TOKENS = ("depth from", "depth to", "rock description")
_SPT_TOKENS = ("spt depth", "n-value")

# Full column sets the row readers extract after a sheet is identified.
_BORELOG_COLS = _BORELOG_TOKENS + ("sand/ clay",)
_ROCK_COLS = _ROCK_TOKENS + ("recovery", "rqd", "remark")

# Every optional interval column, and the subset coerced as numbers. The
# interval reader walks this once instead of repeating the same tuple per
# row, so the two datasets cannot drift apart. Membership in the active
# data_tokens is still checked at read time, which is what keeps a borelog
# row from gaining rock-only keys.
_OPTIONAL_INTERVAL_COLS = (
    ("soil_description", "soil description"),
    ("sand_clay", "sand/ clay"),
    ("rock_description", "rock description"),
    ("recovery", "recovery"),
    ("rqd", "rqd"),
    ("remark", "remark"),
)
_NUMERIC_INTERVAL_COLS = frozenset({"recovery", "rqd"})

# ProjectInfo is a label/value block with no header row, so it is detected
# by its labels in column A. AGS_Mapping_Remarks mentions the same labels
# but in column D, so the column-A restriction keeps detection unambiguous.
_PROJECT_INFO_LABELS = ("client name", "borehole number")

# Excel serial dates or dd.mm.yyyy text both appear in the wild; accept the
# common Indian-format variants plus ISO.
_DATE_FORMATS = ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")


class ExcelImportError(SpreadsheetFormatError):
    """Backward-compatible field parser error name."""


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------

def _norm(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return " ".join(text.split()).strip().lower()


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _num(value: Any, field: str, row_no: int, required: bool = True) -> Optional[Decimal]:
    """Cell -> exact Decimal.

    Excel numbers arrive as binary floats (5.8 reads back as
    5.7999999999999998...), and NUMERIC columns store whatever they are
    given: passing the float through would freeze that artifact into the
    database. Converting via repr() keeps the shortest decimal string the
    user actually typed, so 5.8 stays 5.8 and re-imports land on the same
    unique-constraint identity. Decimal(text) rejects Infinity/NaN/empty
    exponent forms on its own; the is_finite check is belt and braces.
    """
    if _is_blank(value):
        if required:
            raise ExcelImportError(
                f"{field} is empty on the sheet (row {row_no})."
            )
        return None
    if isinstance(value, bool):
        raise ExcelImportError(
            f"{field} must be a number, not TRUE/FALSE (row {row_no})."
        )
    try:
        result = Decimal(repr(value)) if isinstance(value, (int, float)) else Decimal(str(value).replace(",", "."))
    except Exception:
        raise ExcelImportError(
            f"{field} is not a valid number: {value!r} (row {row_no})."
        ) from None
    if not result.is_finite():
        raise ExcelImportError(
            f"{field} is not a finite number (row {row_no})."
        )
    # 10-decimal ceiling, same contract as before: repr() already gives the
    # shortest round-trip float text, but a literal like 2.1999999999999997
    # typed into a cell IS its own shortest form, so the quantize is what
    # snaps it back to the 2.2 the sheet meant. The strip afterwards drops
    # the zero padding round() adds (2.2000000000 -> 2.2): NUMERIC keeps
    # the scale it is handed, so padded zeros would land in the database
    # and every psql SELECT would display them.
    result = round(result, 10)
    if result == result.to_integral_value():
        return result.to_integral_value()
    return result.normalize()


def _text(value: Any) -> Optional[str]:
    if _is_blank(value):
        return None
    return str(value).strip()


def _date(value: Any, field: str) -> Optional[date]:
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ExcelImportError(f"{field} is not a valid date: {raw!r}") from None


# ---------------------------------------------------------------------------
# Sheet helpers
# ---------------------------------------------------------------------------

def _find_header(rows: List[List[Any]], tokens) -> int:
    """Index of the first row whose cells contain every token, else -1."""
    for i, row in enumerate(rows):
        cells = [_norm(c) for c in row]
        if all(any(tok in cell for cell in cells) for tok in tokens):
            return i
    return -1


def _header_map(header_row: List[Any], tokens) -> Dict[str, int]:
    """Token -> first column index whose header cell contains the token.

    Leftmost wins, which keeps data columns ahead of the in-sheet legend
    column even when a legend cell repeats a data header word.
    """
    cells = [_norm(c) for c in header_row]
    found: Dict[str, int] = {}
    for tok in tokens:
        for idx, cell in enumerate(cells):
            if tok in cell:
                found[tok] = idx
                break
    return found


def _cell(row: List[Any], idx: int) -> Any:
    return row[idx] if idx < len(row) else None


def _is_project_info(rows: List[List[Any]]) -> bool:
    labels = [_norm(r[0]) for r in rows if len(r) > 0]
    return all(
        any(label.startswith(tok) for label in labels if label)
        for tok in _PROJECT_INFO_LABELS
    )


# ---------------------------------------------------------------------------
# Sheet readers
# ---------------------------------------------------------------------------

def _read_project_info(rows: List[List[Any]]) -> Dict[str, Any]:
    labels: Dict[str, Any] = {}
    for row in rows:
        if len(row) < 2:
            continue
        label = _norm(row[0])
        if not label or _is_blank(row[1]):
            continue
        labels[label] = row[1]

    def find(*keywords: str) -> Any:
        for label, value in labels.items():
            if all(kw in label for kw in keywords):
                return value
        return None

    return {
        "project_type": _text(find("project type")),
        "project_location": _text(find("project location")),
        "client_name": _text(find("client name")),
        "borehole_number": _text(find("borehole number")),
        "start_date": _date(find("drilling", "start"), "Drilling start date"),
        "end_date": _date(find("drilling", "completion"), "Drilling completion date"),
        "final_depth": _num(find("termination"), "Termination depth", 0)
        if find("termination") is not None
        else None,
    }


def _read_interval_rows(
    rows: List[List[Any]],
    header_idx: int,
    data_tokens,
) -> List[Dict[str, Any]]:
    """Borelog / Rock profile rows: keyed by depth-from and depth-to columns.

    data_tokens covers every extractable column, not just the tokens that
    identified the sheet, so optional columns (Sand/Clay, Recovery, RQD,
    Remark) are located too.
    """
    cols = _header_map(rows[header_idx], data_tokens)
    records: List[Dict[str, Any]] = []

    for offset, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        depth_from_cell = _cell(row, cols["depth from"])
        depth_to_cell = _cell(row, cols["depth to"])

        if _is_blank(depth_from_cell) and _is_blank(depth_to_cell):
            # First fully empty depth pair marks the end of the data block;
            # styled-but-empty padding and footer blocks after it are ignored.
            break

        record: Dict[str, Any] = {
            "depth_from": _num(depth_from_cell, "Depth From", offset),
            "depth_to": _num(depth_to_cell, "Depth To", offset),
        }
        # One pass over the optional columns. Every column this dataset
        # declares stays present in the normalized contract even when the
        # source omits it, so consumers never need a second "missing key"
        # branch per field. A column the dataset does not declare is skipped
        # entirely: _BORELOG_COLS carries no "rock description" and
        # _ROCK_COLS carries no "sand/ clay", and that gate is what keeps the
        # two datasets' keys from leaking into each other.
        for key, tok in _OPTIONAL_INTERVAL_COLS:
            if tok not in data_tokens:
                continue
            index = cols.get(tok)
            if index is None:
                record[key] = None
                continue
            cell = _cell(row, index)
            if key in _NUMERIC_INTERVAL_COLS:
                record[key] = _num(cell, key, offset, required=False)
            else:
                record[key] = _text(cell)
        if record["depth_to"] <= record["depth_from"]:
            raise ExcelImportError(
                f"Depth To must be greater than Depth From at row {offset}."
            )
        records.append(record)

    return records


def _optional_num(
    row: List[Any],
    cols: Dict[str, int],
    token: str,
    field: str,
    offset: int,
) -> Optional[Decimal]:
    """Read one optional SPT column, or None when the sheet lacks it.

    Module scope on purpose: a closure built inside the row loop captured
    that loop's row and offset, so any later edit that hoisted the loop body
    would silently keep reading the last row. Index -1 is likewise never
    passed to _cell(), which would index the last source column and copy the
    N-value into all three blow fields on a CSV without blow columns.
    """
    index = cols.get(token)
    if index is None:
        return None
    return _num(_cell(row, index), field, offset, required=False)


def _read_spt_rows(rows: List[List[Any]], header_idx: int) -> List[Dict[str, Any]]:
    cols = _header_map(
        rows[header_idx],
        ("spt depth", "blows @15cm", "blows @30cm", "blows @45cm", "n-value"),
    )
    records: List[Dict[str, Any]] = []

    for offset, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        depth_cell = _cell(row, cols["spt depth"])
        if _is_blank(depth_cell):
            # The SPT sheet pads with empty rows and ends with a derived
            # "Layer 1..9" summary block that holds no ISPT data.
            break

        # Missing optional columns must stay missing; _optional_num returns
        # None when the token was not found in the header.
        records.append(
            {
                "spt_depth": _num(depth_cell, "SPT Depth", offset),
                "blows_15": _optional_num(
                    row, cols, "blows @15cm", "Blows @15cm", offset
                ),
                "blows_30": _optional_num(
                    row, cols, "blows @30cm", "Blows @30cm", offset
                ),
                "blows_45": _optional_num(
                    row, cols, "blows @45cm", "Blows @45cm", offset
                ),
                "n_value": _optional_num(
                    row, cols, "n-value", "SPT N-value", offset
                ),
            }
        )

    return records


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_document(document) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "project_info": {},
        "borelog": [],
        "rock_profile": [],
        "spt": [],
    }

    saw_data_sheet = False

    for sheet in document.sheets:
        rows = sheet.rows[:MAX_ROWS]
        if not rows:
            continue

        if _is_project_info(rows):
            # Merge, do not overwrite: a workbook may split ProjectInfo
            # across sheets. Later sheets fill only keys the earlier ones
            # left unset, so a second sheet cannot blank the first.
            for key, value in _read_project_info(rows).items():
                if value is not None and result["project_info"].get(key) is None:
                    result["project_info"][key] = value
            saw_data_sheet = True
            continue

        header_idx = _find_header(rows, _BORELOG_TOKENS)
        if header_idx >= 0:
            # Extend, do not assign. A workbook with one Borelog sheet per
            # borehole used to keep only the last sheet and silently
            # discard every earlier layer.
            result["borelog"].extend(
                _read_interval_rows(rows, header_idx, _BORELOG_COLS)
            )
            saw_data_sheet = True
            continue

        header_idx = _find_header(rows, _ROCK_TOKENS)
        if header_idx >= 0:
            result["rock_profile"].extend(
                _read_interval_rows(rows, header_idx, _ROCK_COLS)
            )
            saw_data_sheet = True
            continue

        header_idx = _find_header(rows, _SPT_TOKENS)
        if header_idx >= 0:
            result["spt"].extend(_read_spt_rows(rows, header_idx))
            saw_data_sheet = True

    if not saw_data_sheet:
        raise ExcelImportError(
            "No recognizable data sheets were found. Expected sheets: "
            "ProjectInfo, Borelog, Rock profile, SPT_Data."
        )

    return result


def _parse_csv_document(document) -> Dict[str, Any]:
    """Parse one CSV table as one field dataset, never as a fake workbook."""
    if len(document.sheets) != 1:
        raise ExcelImportError(
            "This CSV file did not contain a readable table."
        )

    rows = document.sheets[0].rows
    if len(rows) < 2:
        raise ExcelImportError(
            "This CSV file has no data rows after the header."
        )

    def result(dataset: str, data_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not data_rows:
            raise ExcelImportError(
                "This CSV file has no data rows after the header."
            )
        return {"dataset": dataset, "rows": data_rows}

    header_idx = _find_header(rows, _BORELOG_TOKENS)
    if header_idx >= 0:
        return result(
            "borelog",
            _read_interval_rows(rows, header_idx, _BORELOG_COLS),
        )

    header_idx = _find_header(rows, _ROCK_TOKENS)
    if header_idx >= 0:
        return result(
            "rock_profile",
            _read_interval_rows(rows, header_idx, _ROCK_COLS),
        )

    header_idx = _find_header(rows, _SPT_TOKENS)
    if header_idx >= 0:
        return result("spt", _read_spt_rows(rows, header_idx))

    raise ExcelImportError(
        "This CSV table is not a recognized Borelog, Rock profile, "
        "or SPT dataset."
    )


def parse_field_document(document) -> Dict[str, Any]:
    """Parse an already-read field document into a normalized result."""
    if document.format.value == "csv":
        return _parse_csv_document(document)
    return _parse_document(document)


def parse_field_input_spreadsheet(
    data: bytes, filename: str | None = None
) -> Dict[str, Any]:
    """Parse an Excel workbook or one CSV field dataset."""
    try:
        document = read_spreadsheet(data, filename)
        return parse_field_document(document)
    except SpreadsheetImportError as error:
        if isinstance(error, ExcelImportError):
            raise
        # Preserve the field parser's historical exception type for callers
        # that only import the field profile.
        raise ExcelImportError(error.message) from None


def parse_input_sheet(data: bytes) -> Dict[str, Any]:
    """Workbook bytes -> project info + borelog + rock profile + SPT rows.

    Raises ExcelImportError with a user-safe message on any structural
    problem (unknown file, missing sheet, unparseable cell).
    """
    return parse_field_input_spreadsheet(data, "upload.xlsx")
