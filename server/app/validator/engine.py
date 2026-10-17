"""The generic AGS value engine — reads rules.py, never edits it.

check_value / coerce_value mirror the AGSValidator twin exactly
(../AGSValidator/backend/services/ags_validate.py), including its
contract: coerce_value MUST only be called after check_value passed.
Blank (None or whitespace-only) is always type-OK; REQUIRED-ness
(Rule 10b) is the caller's concern — use is_blank() per value, or
validate_record(required=...) for whole rows.

No Excel-serial handling here, by design: the server receives JSON,
never raw xlsx cells — serial-to-ISO conversion is the browser's job
(frontend coerceForDb), exactly like the AGSValidator twin.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .rules import resolve_code


class AGSValidationError(ValueError):
    """Raised by validate_or_raise; carries the AGS code and value."""

    def __init__(self, code: str, value: Any, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.value = value
        self.message = message


def is_blank(value: Any) -> bool:
    """AGS blank: None or whitespace-only. Blankness is NOT a type error."""
    return value is None or str(value).strip() == ""


def _raw(value: Any) -> str:
    return "" if value is None else str(value).strip()


def check_value(ags_type_code: str, value: Any) -> tuple[bool, str | None]:
    """Validate ONE value against its AGS type code.

    Returns (ok, message); message is None when ok. Blank is type-OK —
    whether blank is ALLOWED is the caller's Rule 10b decision.
    """
    if is_blank(value):
        return True, None
    code, rule = resolve_code(ags_type_code)
    if not rule:
        return False, f'unknown AGS type code "{(ags_type_code or "").strip().upper()}"'
    raw = _raw(value)
    kind = rule["kind"]
    if kind == "integer":
        try:
            n = float(raw)
        except ValueError:
            return False, rule["message"].format(v=raw)
        if not n.is_integer():
            return False, rule["message"].format(v=raw)
        return True, None
    if kind == "number":
        try:
            n = float(raw)
        except ValueError:
            return False, rule["message"].format(v=raw)
        # float("Infinity") / float("NaN") parse fine but are not real
        # AGS numbers; the TS twin already rejects them via
        # Number.isFinite, so this keeps the two validators in lockstep.
        if not math.isfinite(n):
            return False, rule["message"].format(v=raw)
        return True, None
    if kind == "regex":
        assert rule["pattern"] is not None  # regex rules always carry one
        if rule["pattern"].match(raw):
            return True, None
        return False, rule["message"].format(v=raw)
    return True, None  # kind == "any"


def coerce_value(ags_type_code: str, value: Any) -> Any:
    """Convert a value to the shape PostgreSQL expects.

    I -> int, U/DP/SF/SCI -> float, YN -> bool, text stays text (trimmed),
    blank -> None. Callers MUST run check_value first; this assumes valid
    input (same contract as the AGSValidator twin).
    """
    if is_blank(value):
        return None
    code, rule = resolve_code(ags_type_code)
    if not rule:
        return _raw(value)
    raw = _raw(value)
    coerce = rule.get("coerce", "text")
    if coerce == "int":
        return int(float(raw))  # via float so "5.0" still coerces to 5
    if coerce == "float":
        return float(raw)
    if coerce == "bool":
        return raw.upper() in ("Y", "YES", "TRUE")
    return raw


def validate_or_raise(ags_type_code: str, value: Any) -> None:
    """check_value that raises AGSValidationError — for endpoint code that
    wants `try/except` or a one-line 422, not tuple unpacking."""
    ok, msg = check_value(ags_type_code, value)
    if not ok:
        raise AGSValidationError(
            (ags_type_code or "").strip().upper(), value, msg or "invalid value"
        )


def validate_record(
    fields: Mapping[str, str],
    record: Mapping[str, Any],
    required: Iterable[str] = (),
) -> list[dict[str, str]]:
    """Validate a whole record (one AGS row) — returns ALL problems.

    fields:   column name -> AGS type code
    record:   column name -> raw value
    required: columns that must not be blank (Rule 10b)

    Each problem: {"field", "value", "message", "kind"} where kind is
    "type" or "required". All problems are reported, not fail-fast —
    same semantics as the frontend's per-sheet validation.
    """
    problems: list[dict[str, str]] = []
    required_set = set(required)
    for field, ags_code in fields.items():
        value = record.get(field)
        if is_blank(value):
            if field in required_set:
                problems.append(
                    {
                        "field": field,
                        "value": "",
                        "message": (
                            f"{field} is a required field (Rule 10b) and "
                            "cannot be blank."
                        ),
                        "kind": "required",
                    }
                )
            continue
        ok, msg = check_value(ags_code, value)
        if not ok:
            problems.append(
                {
                    "field": field,
                    "value": _raw(value),
                    "message": f"{field}: {msg}",
                    "kind": "type",
                }
            )
    return problems
