"""QR code generation for the Lab Data > Sample Register.

Server-side for two reasons. The browser would need a QR library in the
bundle, and the payload has to come from the same authoritative read as the
register itself -- if the client built it, a stale tab could print a code
for a sample that has since been deleted or had its location corrected.

The payload is a compact JSON document rather than a URL. A QR printed onto
a field sample label outlives any single deployment: the JSON survives a
domain change, a rename and a re-brand, and a scanner needs one line of code
to read it.

    {"v":1,"t":"sample","p":"<project>","l":"<loca>","s":"<sample>","k":"soil"}

`v` is a schema version. If the shape ever changes, bump it, so a scanner
that understands v1 can refuse a v2 code rather than mis-parse it.

Output is SVG, not PNG. It stays sharp at any print size, needs no Pillow or
other C extension (which matters on Termux), and the browser rasterises it
at the printer's real resolution.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Iterable

import segno

#: Quiet zone in QR modules. Small enough to keep a printed label compact
#: while leaving the standard margin most scanners need.
_BORDER = 2

#: Pixels per module. 6 produces roughly a 200 px SVG for a typical payload,
#: which prints cleanly at 25-30 mm on paper.
_SCALE = 6

#: Error correction. "m" (15%) tolerates the smudge, fold or toner void that
#: actually shows up on field-issued sample labels.
_ERROR = "m"

SCHEMA_VERSION = 1


def build_payload(project_id: str, sample: dict[str, Any]) -> str:
    """The exact string that goes inside the QR code.

    Kept in one place so what the user is shown and what a scanner reads are
    guaranteed identical -- building it twice is how the two drift apart.
    """

    return json.dumps(
        {
            "v": SCHEMA_VERSION,
            "t": "sample",
            "p": project_id,
            "l": sample["loca_id"],
            "s": sample["sample_id"],
            "k": sample["kind"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def generate_svg_data_url(payload: str) -> str:
    """One QR code as a data URI, ready to drop into an <img src>."""

    qr = segno.make(payload, error=_ERROR)
    return qr.svg_data_uri(
        scale=_SCALE,
        border=_BORDER,
        # No XML declaration, no trailing newline: the data URI stays a
        # single attribute-safe string with nothing to escape.
        xmldecl=False,
        svgns=True,
        nl=False,
    )


def _as_float(value: Any) -> float | None:
    """Depths arrive as Decimal from asyncpg and must stay JSON-encodable."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def attach_qr_codes(
    project_id: str, samples: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Stamp each sample with its payload and its QR data URI.

    Returns new dicts rather than mutating in place, so the register payload
    and the QR payload cannot leak fields into each other.
    """

    out: list[dict[str, Any]] = []
    for sample in samples:
        payload = build_payload(project_id, sample)
        out.append(
            {
                **sample,
                "depth_from": _as_float(sample.get("depth_from")),
                "depth_to": _as_float(sample.get("depth_to")),
                "payload": payload,
                "qr_svg_data_url": generate_svg_data_url(payload),
            }
        )
    return out