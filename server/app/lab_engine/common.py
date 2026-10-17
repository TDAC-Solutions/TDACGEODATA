"""Shared validation, regression and PDF helpers for TDAC lab modules."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


class InputError(ValueError):
    """Raw observations cannot be calculated safely; suitable for the UI."""


def number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise InputError(f"{label} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{label} must be numeric") from exc
    if not math.isfinite(x) or (positive and x <= 0):
        suffix = " and positive" if positive else ""
        raise InputError(f"{label} must be finite{suffix}")
    return x


def nonnegative(value: Any, label: str) -> float:
    x = number(value, label)
    if x < 0:
        raise InputError(f"{label} cannot be negative")
    return x


def require_metadata(metadata: dict) -> None:
    for field in ("PROJ_ID", "LOCA_ID", "SAMP_REF", "SPEC_REF", "SAMP_TOP"):
        if metadata.get(field) in (None, ""):
            raise InputError(f"metadata.{field} is required")
    top = number(metadata["SAMP_TOP"], "metadata.SAMP_TOP")
    if metadata.get("SAMP_BASE") is not None:
        base = number(metadata["SAMP_BASE"], "metadata.SAMP_BASE")
        if base < top:
            raise InputError("SAMP_BASE must not be above SAMP_TOP")


def water_content(row: dict, label: str) -> dict:
    """Water content from container/tin masses, referenced to dry soil."""
    tare = number(row.get("TDAC_CONTAINER_G"), f"{label} container mass")
    wet = number(row.get("TDAC_CONTAINER_WET_G"), f"{label} container + wet soil")
    dry = number(row.get("TDAC_CONTAINER_DRY_G"), f"{label} container + dry soil")
    if tare < 0 or dry <= tare or wet < dry:
        raise InputError(f"{label} masses must satisfy wet >= dry > container >= 0")
    water = wet - dry
    dry_soil = dry - tare
    return {
        "container_g": tare,
        "container_wet_g": wet,
        "container_dry_g": dry,
        "water_mass_g": water,
        "dry_soil_mass_g": dry_soil,
        "water_content_pct": 100.0 * water / dry_soil,
    }


def linear_regression(xs: list[float], ys: list[float]) -> dict:
    if len(xs) != len(ys) or len(xs) < 2:
        raise InputError("Regression requires at least two paired observations")
    xbar, ybar = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - xbar) ** 2 for x in xs)
    if sxx <= 0:
        raise InputError("Regression control values must not all be equal")
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / sxx
    intercept = ybar - slope * xbar
    fitted = [intercept + slope * x for x in xs]
    sse = sum((y - f) ** 2 for y, f in zip(ys, fitted))
    sst = sum((y - ybar) ** 2 for y in ys)
    r2 = 1.0 if sst <= 1e-15 and sse <= 1e-15 else (0.0 if sst <= 1e-15 else 1.0 - sse / sst)
    return {"slope": slope, "intercept": intercept, "r_squared": r2, "fitted": fitted}


def mean(values: list[float]) -> float:
    if not values:
        raise InputError("At least one value is required")
    return sum(values) / len(values)


def fmt(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "ND"
    if isinstance(value, str):
        return value
    return f"{value:,.{decimals}f}"


def safe(value: Any) -> str:
    return escape("" if value is None else str(value))


def pdf_components():
    try:
        import os
        import tempfile
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "tdac_mpl_cache"))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError("PDF generation requires reportlab and matplotlib") from exc
    return locals()


def styled_table(data: list[list], widths: list[float], colors, *, header: bool = False, font_size: float = 7):
    from reportlab.platypus import Table, TableStyle
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    rules = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, -1), (-1, -1), 0.3, colors.HexColor("#b4c3ce")),
    ]
    if header:
        rules += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3edf3")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f9fa")]),
        ]
    table.setStyle(TableStyle(rules))
    return table


def metadata_table(metadata: dict, standard: str, method: str, colors):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph
    styles = getSampleStyleSheet()
    styles["Normal"].fontSize = 7
    styles["Normal"].leading = 8.5
    wrap = lambda value: Paragraph(safe(value), styles["Normal"])
    depth = f"{metadata.get('SAMP_TOP')} to {metadata.get('SAMP_BASE') or '-'}"
    rows = [
        ["Project", wrap(metadata.get("PROJ_ID")), "Borehole", wrap(metadata.get("LOCA_ID"))],
        ["Sample", wrap(metadata.get("SAMP_REF")), "Specimen", wrap(metadata.get("SPEC_REF"))],
        ["Depth (m)", wrap(depth), "Test date", wrap(metadata.get("TEST_DATE") or "-")],
        ["Standard", wrap(standard), "Method", wrap(method.replace("_", " "))],
    ]
    return styled_table(rows, [72, 187, 78, 175], colors)
