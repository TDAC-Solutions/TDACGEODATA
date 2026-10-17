"""server/app/validator — the ONE AGS 4.2 value validator for server/.

Define rules ONCE in rules.py; reuse everywhere via this package:

    from app.validator import check_value, coerce_value

    ok, msg = check_value("I", "42")          # (True, None)
    ok, msg = check_value("YN", "maybe")      # (False, 'expected Y/N, got "maybe"')
    n = coerce_value("2DP", "1.25")           # 1.25  (float)
    validate_or_raise("DT", "15/03/2024")     # raises AGSValidationError
    problems = validate_record(fields, row, required=["LOCA_ID"])

Adding a new AGS type code = adding ONE entry to RULES in rules.py.
The engine is generic and never needs touching.
"""
from .engine import (
    AGSValidationError,
    check_value,
    coerce_value,
    is_blank,
    validate_or_raise,
    validate_record,
)
from .rules import RULES, Rule, resolve_code

__all__ = [
    "AGSValidationError",
    "RULES",
    "Rule",
    "check_value",
    "coerce_value",
    "is_blank",
    "resolve_code",
    "validate_or_raise",
    "validate_record",
]
