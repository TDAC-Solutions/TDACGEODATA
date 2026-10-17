"""AGS 4.2 value rules — THE single source of truth for server/.

One table drives every check, every coercion, and the future DB type
mapping: adding a new AGS type code means adding ONE dict entry here.
The engine (engine.py) never changes and never hardcodes a type.

Keep the regexes and message strings character-for-character identical
to the AGSValidator twin (../AGSValidator/backend/services/ags_validate.py)
— server/ and AGSValidator are two readers of one rulebook, and the
golden-case test suites on both sides pin that parity.

Rules (AGS 4.2 type policy, same as build_ags42_postgresql.py):
  I            integer
  U / nDP/nSF/nSCI   finite number (DP/SF/SCI are precision hints)
  DT           ISO date/time, full or partial (spec §3.3)
  T            elapsed time hh:mm or hh:mm:ss
  YN           Y/N/YES/NO/TRUE/FALSE (case-insensitive)
  XN           text OR number — anything non-empty
  X ID PA PT PU DMS RL   free text
"""
from __future__ import annotations

import re
from typing import Optional, TypedDict

NUMERIC_SUFFIX = re.compile(r"^\d+(DP|SF|SCI)$")

# AGS 4.2 DT — "yyyy-mm-ddThh:mm:ss.sssZ(+hh:mm) or yyyy-mm-dd or
# hh:mm:ss or yyyy. This format may be used in full or part" (spec §3.3).
# The spec's own examples include second-less timestamps (2009-04-01T10:45),
# so every time component below seconds is optional. VERBATIM from the twin.
DT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?(Z|[+-]\d{2}:?\d{2})?)?"
    r"|\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?"
    r"|\d{4})$"
)

# AGS T — elapsed time (verbatim from the twin).
T_RE = re.compile(r"^\d{1,3}:\d{2}(:\d{2})?$")

# AGS YN — boolean, case-insensitive (verbatim from the twin).
YN_RE = re.compile(r"^(Y|N|YES|NO|TRUE|FALSE)$", re.IGNORECASE)

# Text-like codes: no format constraint beyond non-blank.
TEXT_CODES = frozenset({"X", "ID", "PA", "PT", "PU", "DMS", "RL"})


class Rule(TypedDict, total=False):
    kind: str                      # "integer" | "number" | "regex" | "any"
    pattern: Optional[re.Pattern[str]]
    message: str                   # {v} = the offending value
    coerce: str                    # "int" | "float" | "bool" | "text"
    pg_type: str                   # PostgreSQL column type for future mapping


RULES: dict[str, Rule] = {
    "I": Rule(
        kind="integer",
        message='expected integer, got "{v}"',
        coerce="int",
        pg_type="INTEGER",
    ),
    "U": Rule(
        kind="number",
        message='expected number, got "{v}"',
        coerce="float",
        pg_type="NUMERIC",
    ),
    "DT": Rule(
        kind="regex",
        pattern=DT_RE,
        message=(
            "expected date/time (yyyy-mm-ddThh:mm:ss.sssZ, yyyy-mm-dd, "
            'hh:mm:ss or yyyy), got "{v}"'
        ),
        coerce="text",
        pg_type="TIMESTAMPTZ",
    ),
    "T": Rule(
        kind="regex",
        pattern=T_RE,
        message='expected elapsed time (hh:mm or hh:mm:ss), got "{v}"',
        coerce="text",
        pg_type="INTERVAL",
    ),
    "YN": Rule(
        kind="regex",
        pattern=YN_RE,
        message='expected Y/N, got "{v}"',
        coerce="bool",
        pg_type="BOOLEAN",
    ),
    "XN": Rule(kind="any", message="", coerce="text", pg_type="TEXT"),
}
for _code in TEXT_CODES:
    RULES[_code] = Rule(kind="any", message="", coerce="text", pg_type="TEXT")


def resolve_code(ags_type_code: str) -> tuple[str, Rule]:
    """Resolve a raw TYPE cell to (canonical_code, rule).

    Handles case/whitespace and the numeric suffixes (2DP, 4SF, 3SCI, ...)
    which share U's rule. Unknown codes resolve to ("", {}) — the engine
    turns that into the loud unknown-code error, never a silent pass.
    """
    code = (ags_type_code or "").strip().upper()
    if code in RULES:
        return code, RULES[code]
    if NUMERIC_SUFFIX.match(code):
        return "U", RULES["U"]
    return "", {}
