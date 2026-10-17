"""Golden-case suite for the server/ validator.

These cases ARE the parity contract with the AGSValidator twin: every
case has a known verdict on both sides (the twins share regexes and
messages verbatim). If someone edits rules.py or engine.py and a case
goes red, the twins have drifted — fix the rule, not the test.

Run:  python3 -m pytest server/tests/test_validator.py -q
(from the tdac-new-app repo root)
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.validator import (  # noqa: E402
    AGSValidationError,
    RULES,
    check_value,
    coerce_value,
    is_blank,
    resolve_code,
    validate_or_raise,
    validate_record,
)

# (code, value, ok, coerced-or-None) — mirrors frontend checkValue tests.
CHECK_CASES: list[tuple[str, object, bool, object]] = [
    # I — integer
    ("I", "5", True, 5),
    ("I", "5.0", True, 5),
    ("I", "-42", True, -42),
    ("I", "5.5", False, None),
    ("I", "abc", False, None),
    ("I", "", True, None),            # blank is type-OK
    ("I", None, True, None),
    ("I", "  7  ", True, 7),          # surrounding whitespace trimmed
    # U and numeric suffixes — one rule, many codes
    ("U", "3.14", True, 3.14),
    ("U", "-2", True, -2.0),
    ("U", "abc", False, None),
    # U must reject non-finite spellings: float() happily parses them
    # but no AGS field ever holds inf/nan, and Number.isFinite already
    # rejects them on the TS side. Pinned so the twins stay in lockstep.
    ("U", "Infinity", False, None),
    ("U", "-Infinity", False, None),
    ("U", "inf", False, None),
    ("U", "nan", False, None),
    ("U", "NaN", False, None),
    ("2DP", "1.25", True, 1.25),
    ("4SF", "1234", True, 1234.0),
    ("3SCI", "0.001", True, 0.001),
    ("2dp", "9.9", True, 9.9),        # case-insensitive
    # DT — full and partial timestamps (spec §3.3)
    ("DT", "2024-03-15T10:45:30.123Z", True, "2024-03-15T10:45:30.123Z"),
    ("DT", "2024-03-15T10:45", True, None),           # spec's own example
    ("DT", "2024-03-15", True, None),
    ("DT", "10:45:30", True, None),
    ("DT", "2024", True, None),
    ("DT", "15/03/2024", False, None),
    ("DT", "not a date", False, None),
    # T — elapsed time
    ("T", "04:30", True, None),
    ("T", "04:30:15", True, None),
    ("T", "100:00", True, None),
    ("T", "4h30", False, None),
    ("T", "-1:00", False, None),
    # YN — case-insensitive booleans
    ("YN", "Y", True, True),
    ("YN", "n", True, False),
    ("YN", "yes", True, True),
    ("YN", "FALSE", True, False),
    ("YN", "TRUE", True, True),
    ("YN", "maybe", False, None),
    ("YN", "1", False, None),
    # XN — text or number, anything non-empty
    ("XN", "BH-01", True, "BH-01"),
    ("XN", "42", True, "42"),
    # text codes
    ("X", "anything at all", True, "anything at all"),
    ("ID", "LOCA-007", True, "LOCA-007"),
    ("PA", "silty CLAY", True, "silty CLAY"),
    ("PT", "note", True, "note"),
    ("PU", "m", True, "m"),
    ("DMS", "51°30'26\"", True, "51°30'26\""),
    ("RL", "102.5", True, "102.5"),
    # unknown codes — loud, never silent
    ("QQ", "x", False, None),
    ("", "x", False, None),
    ("INTEGER", "5", False, None),    # full words are not AGS codes
]

REQUIRED_ROW_FIELDS = {"LOCA_ID": "ID", "LOCA_TYPE": "YN", "depth": "U"}


class TestCheckValue:
    @pytest.mark.parametrize(
        "code,value,ok,coerced", CHECK_CASES, ids=[c[0] + ":" + repr(c[1]) for c in CHECK_CASES]
    )
    def test_case(self, code, value, ok, coerced):
        got_ok, msg = check_value(code, value)
        assert got_ok is ok, f"{code}({value!r}): unexpected verdict, msg={msg!r}"
        if ok:
            got = coerce_value(code, value)
            if coerced is not None:
                assert got == coerced, f"{code}({value!r}) coerced to {got!r}, want {coerced!r}"
            else:
                assert got is not None or value in (None, ""), "valid non-blank coerced to None"

    def test_blank_is_always_type_ok(self):
        for code in RULES:
            ok, msg = check_value(code, "   ")
            assert ok, f"blank failed for {code}: {msg}"

    def test_unknown_code_message(self):
        ok, msg = check_value("QQ", "x")
        assert not ok
        assert msg == 'unknown AGS type code "QQ"'


class TestMessages:
    """Error strings must match the AGSValidator twin verbatim."""

    def test_integer_message(self):
        ok, msg = check_value("I", "abc")
        assert msg == 'expected integer, got "abc"'

    def test_number_message(self):
        ok, msg = check_value("U", "abc")
        assert msg == 'expected number, got "abc"'

    def test_dt_message(self):
        ok, msg = check_value("DT", "15/03/2024")
        assert msg == (
            "expected date/time (yyyy-mm-ddThh:mm:ss.sssZ, yyyy-mm-dd, "
            'hh:mm:ss or yyyy), got "15/03/2024"'
        )

    def test_t_message(self):
        ok, msg = check_value("T", "4h30")
        assert msg == 'expected elapsed time (hh:mm or hh:mm:ss), got "4h30"'

    def test_yn_message(self):
        ok, msg = check_value("YN", "maybe")
        assert msg == 'expected Y/N, got "maybe"'


class TestResolveCode:
    def test_suffixes_share_u(self):
        for suffix in ("2DP", "4SF", "3SCI"):
            code, rule = resolve_code(suffix)
            assert code == "U" and rule["kind"] == "number"

    def test_unknown_resolves_empty(self):
        code, rule = resolve_code("QQ")
        assert code == "" and rule == {}


class TestCoerce:
    def test_int_via_float(self):
        assert coerce_value("I", "5.0") == 5
        assert isinstance(coerce_value("I", "5.0"), int)

    def test_bool_true_set(self):
        for v in ("Y", "YES", "TRUE", "true"):
            assert coerce_value("YN", v) is True
        for v in ("N", "NO", "FALSE", "false"):
            assert coerce_value("YN", v) is False

    def test_blank_to_none(self):
        assert coerce_value("I", "") is None
        assert coerce_value("U", None) is None


class TestValidateOrRaise:
    def test_passes_silently(self):
        validate_or_raise("I", "42")

    def test_raises_with_context(self):
        with pytest.raises(AGSValidationError) as exc:
            validate_or_raise("YN", "maybe")
        assert exc.value.code == "YN"
        assert exc.value.value == "maybe"
        assert 'expected Y/N, got "maybe"' in str(exc.value)


class TestValidateRecord:
    def test_all_problems_reported(self):
        row = {"LOCA_ID": "", "LOCA_TYPE": "maybe", "depth": "abc"}
        problems = validate_record(REQUIRED_ROW_FIELDS, row, required=["LOCA_ID"])
        kinds = sorted(p["kind"] for p in problems)
        assert kinds == ["required", "type", "type"]
        by_field = {p["field"]: p for p in problems}
        assert "Rule 10b" in by_field["LOCA_ID"]["message"]
        assert 'expected Y/N, got "maybe"' in by_field["LOCA_TYPE"]["message"]
        assert "expected number" in by_field["depth"]["message"]

    def test_clean_row_has_no_problems(self):
        row = {"LOCA_ID": "BH-01", "LOCA_TYPE": "Y", "depth": "2.5"}
        assert validate_record(REQUIRED_ROW_FIELDS, row, required=["LOCA_ID"]) == []

    def test_optional_blank_is_fine(self):
        row = {"LOCA_ID": "BH-01", "LOCA_TYPE": "N", "depth": ""}
        assert validate_record(REQUIRED_ROW_FIELDS, row, required=["LOCA_ID"]) == []


class TestIsBlank:
    def test_cases(self):
        assert is_blank(None)
        assert is_blank("")
        assert is_blank("   ")
        assert not is_blank("x")
        assert not is_blank(0)
        assert not is_blank(False)
