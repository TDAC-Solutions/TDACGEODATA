#!/usr/bin/env python3
"""TDAC grain-size calculation and reporting reference module, v0.1.0.

Input/output contract: JSON; all masses in g, apertures in mm, time in min.
This is an integration reference, not a claim of independently certified
ISO/IS conformity. See README.md for method verification and release gates.

CLI: python tdac_grain_size.py input.json --output-dir output
API: process_test(test_dict), render_test_pdf(result_dict, path),
     build_borehole_summary(results, loca_id), render_summary_pdf(summary, path).
PDF functions require reportlab and matplotlib. Calculation functions use only
the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

VERSION = "0.1.0"
PROFILES = {
    "IS_2720_4_1985": {
        "standard": "IS 2720 (Part 4):1985",
        "split_mm": 0.075,
        "gravel_boundary_mm": 4.75,
        "fine_boundary_mm": 0.075,
    },
    "ISO_17892_4_2016": {
        "standard": "ISO 17892-4:2016",
        "split_mm": 0.063,
        "gravel_boundary_mm": 2.0,
        "fine_boundary_mm": 0.063,
    },
}
EPS = 1e-9


class InputError(ValueError):
    """Input cannot be safely calculated; suitable for displaying in the UI."""


def number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise InputError(f"{label} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{label} must be numeric") from exc
    if not math.isfinite(x) or (positive and x <= 0):
        raise InputError(f"{label} must be finite" + (" and positive" if positive else ""))
    return x


def require_nonnegative(value: Any, label: str) -> float:
    x = number(value, label)
    if x < 0:
        raise InputError(f"{label} cannot be negative")
    return x


def interpolate_log_diameter(points: list[dict], target_pct: float) -> float | None:
    """Size at percent finer, interpolating log10(size) versus linear percent.

    Returns None outside the *measured* passing range; never extrapolates.
    """
    ordered = sorted(points, key=lambda p: p["size_mm"])
    for p in ordered:
        if abs(p["passing_pct"] - target_pct) < EPS:
            return p["size_mm"]
    for a, b in zip(ordered, ordered[1:]):
        lo, hi = a["passing_pct"], b["passing_pct"]
        if min(lo, hi) < target_pct < max(lo, hi) and abs(hi - lo) > EPS:
            fraction = (target_pct - lo) / (hi - lo)
            return 10 ** (math.log10(a["size_mm"]) + fraction *
                          (math.log10(b["size_mm"]) - math.log10(a["size_mm"])))
    return None


def interpolate_passing(points: list[dict], size_mm: float) -> tuple[float | None, str]:
    ordered = sorted(points, key=lambda p: p["size_mm"])
    for p in ordered:
        if abs(p["size_mm"] - size_mm) <= max(EPS, size_mm * 1e-8):
            return p["passing_pct"], "measured"
    for a, b in zip(ordered, ordered[1:]):
        if a["size_mm"] < size_mm < b["size_mm"]:
            f = math.log10(size_mm / a["size_mm"]) / math.log10(b["size_mm"] / a["size_mm"])
            return a["passing_pct"] + f * (b["passing_pct"] - a["passing_pct"]), "log-interpolated"
    return None, "outside measured range"


def calculate_sieve(sieve: dict, profile: dict, method: str) -> dict:
    if method not in {"dry_sieving", "wet_sieving", "unconfirmed"}:
        raise InputError("sieve_method must be dry_sieving, wet_sieving or unconfirmed")
    mass = number(sieve.get("TDAC_DRY_MASS_G"), "TDAC_DRY_MASS_G", positive=True)
    pan = require_nonnegative(sieve.get("TDAC_PAN_MASS_G"), "TDAC_PAN_MASS_G")
    wash = require_nonnegative(sieve.get("TDAC_WASH_LOSS_G", 0), "TDAC_WASH_LOSS_G")
    if wash > 0 and method == "dry_sieving":
        raise InputError("Wash loss is incompatible with dry_sieving")
    rows = sieve.get("TDAC_SIEVE_ROWS")
    if not isinstance(rows, list) or not rows:
        raise InputError("TDAC_SIEVE_ROWS must contain sieve readings")
    sizes = []
    for i, row in enumerate(rows):
        sizes.append(number(row.get("GRAT_SIZE"), f"sieve row {i+1} GRAT_SIZE", positive=True))
    if any(sizes[i] <= sizes[i+1] for i in range(len(sizes)-1)):
        raise InputError("Sieve openings must be strictly decreasing and unique")
    retained = [require_nonnegative(r.get("TDAC_RETAINED_G"),
                                    f"sieve row {i+1} TDAC_RETAINED_G")
                for i, r in enumerate(rows)]
    recovered = sum(retained) + pan + wash
    diff = recovered - mass
    qa = sieve.get("TDAC_MASS_TOLERANCE_PCT")
    if qa is None:
        raise InputError("TDAC_MASS_TOLERANCE_PCT requires a documented lab QA value")
    tolerance_pct = require_nonnegative(qa, "TDAC_MASS_TOLERANCE_PCT")
    if abs(diff) > mass * tolerance_pct / 100 + EPS:
        raise InputError(f"Dry mass does not reconcile: {diff:+.5f} g exceeds {tolerance_pct}% tolerance")
    cumulative = 0.0
    out_rows = []
    for size, value in zip(sizes, retained):
        cumulative += value
        passing = 100 * (mass - cumulative) / mass
        if passing < -EPS or passing > 100 + EPS:
            raise InputError("Invalid percent passing; inspect dry mass and retained readings")
        out_rows.append({"size_mm": size, "retained_g": value,
                         "cumulative_retained_g": cumulative,
                         "retained_pct": 100 * value / mass,
                         "cumulative_retained_pct": 100 * cumulative / mass,
                         "passing_pct": max(0.0, min(100.0, passing)),
                         "source": "sieve"})
    points = [{"size_mm": r["size_mm"], "passing_pct": r["passing_pct"],
               "source": "sieve"} for r in out_rows]
    split_pct, split_basis = interpolate_passing(points, profile["split_mm"])
    return {"dry_mass_g": mass, "pan_mass_g": pan, "wash_loss_g": wash,
            "recovered_mass_g": recovered, "mass_difference_g": diff,
            "mass_difference_pct": 100 * diff / mass, "mass_tolerance_pct": tolerance_pct,
            "method": method, "rows": out_rows, "points": points,
            "split_passing_pct": split_pct, "split_basis": split_basis}


def calculate_hydrometer(hydro: dict, sieve_result: dict, profile: dict) -> dict:
    """Calibrated hydrometer concentration and Stokes equivalent diameter.

    The lab supplies signed reading corrections, its instrument's reading to
    concentration factor, effective depths, and temperature-specific fluid
    properties. The app does not assume hydrometer model or calibration table.
    """
    split = sieve_result["split_passing_pct"]
    if split is None or sieve_result["split_basis"] != "measured":
        raise InputError(f"Hydrometer requires an observed {profile['split_mm']} mm sieve passing value")
    fine_mass = number(hydro.get("TDAC_FINE_TEST_DRY_MASS_G"),
                       "TDAC_FINE_TEST_DRY_MASS_G", positive=True)
    volume = number(hydro.get("TDAC_SUSPENSION_VOLUME_L"),
                    "TDAC_SUSPENSION_VOLUME_L", positive=True)
    particle_density = number(hydro.get("TDAC_PARTICLE_DENSITY_KG_M3"),
                              "TDAC_PARTICLE_DENSITY_KG_M3", positive=True)
    cal = hydro.get("TDAC_CALIBRATION", {})
    if not cal.get("instrument_id") or not cal.get("calibration_reference"):
        raise InputError("Hydrometer instrument_id and calibration_reference are required")
    slope = number(cal.get("g_per_l_per_reading"), "calibration g_per_l_per_reading", positive=True)
    offset = number(cal.get("offset_g_per_l"), "calibration offset_g_per_l")
    readings = hydro.get("TDAC_READINGS")
    if not isinstance(readings, list) or not readings:
        raise InputError("Hydrometer requires timed raw readings")
    out = []
    last_t = 0.0
    for i, row in enumerate(readings):
        tag = f"hydrometer row {i+1}"
        t = number(row.get("TDAC_ELAPSED_MIN"), tag + " elapsed min", positive=True)
        if t <= last_t:
            raise InputError("Hydrometer times must increase strictly")
        last_t = t
        raw = number(row.get("TDAC_RAW_READING"), tag + " raw reading")
        blank = number(row.get("TDAC_BLANK_READING"), tag + " blank reading")
        meniscus = number(row.get("TDAC_MENISCUS_CORRECTION"), tag + " meniscus correction")
        temp_corr = number(row.get("TDAC_TEMPERATURE_CORRECTION_G_L"), tag + " temperature correction")
        dispersant_corr = number(row.get("TDAC_DISPERSANT_CORRECTION_G_L"), tag + " dispersant correction")
        temp = number(row.get("TDAC_TEMPERATURE_C"), tag + " temperature")
        depth_mm = number(row.get("TDAC_EFFECTIVE_DEPTH_MM"), tag + " effective depth", positive=True)
        viscosity = number(row.get("TDAC_DYNAMIC_VISCOSITY_PA_S"), tag + " dynamic viscosity", positive=True)
        rho_w = number(row.get("TDAC_WATER_DENSITY_KG_M3"), tag + " water density", positive=True)
        if particle_density <= rho_w:
            raise InputError("Particle density must exceed water density")
        corrected_reading = raw + meniscus - blank
        concentration = slope * corrected_reading + offset + temp_corr + dispersant_corr
        if concentration < -EPS or concentration * volume > fine_mass * (1 + 1e-8):
            raise InputError(f"{tag}: calibrated concentration exceeds valid 0-100% fine-subset range")
        concentration = max(0.0, concentration)
        subset_pct = 100 * concentration * volume / fine_mass
        whole_pct = split * subset_pct / 100
        diameter_m = math.sqrt(18 * viscosity * depth_mm / 1000 /
                               (9.80665 * (particle_density - rho_w) * t * 60))
        size_mm = diameter_m * 1000
        if size_mm >= profile["split_mm"]:
            raise InputError(f"{tag}: sedimentation diameter must fall below the measured split sieve")
        out.append({"elapsed_min": t, "raw_reading": raw, "blank_reading": blank,
                    "meniscus_correction": meniscus, "corrected_reading": corrected_reading,
                    "temperature_correction_g_l": temp_corr,
                    "dispersant_correction_g_l": dispersant_corr,
                    "temperature_c": temp, "effective_depth_mm": depth_mm,
                    "viscosity_pa_s": viscosity, "water_density_kg_m3": rho_w,
                    "concentration_g_l": concentration, "fine_subset_passing_pct": subset_pct,
                    "size_mm": size_mm, "passing_pct": whole_pct, "source": "hydrometer"})
    for a, b in zip(out, out[1:]):
        if b["size_mm"] >= a["size_mm"] or b["passing_pct"] > a["passing_pct"] + 1e-6:
            raise InputError("Hydrometer points must reduce in diameter and percent finer over time")
    return {"fine_test_dry_mass_g": fine_mass, "suspension_volume_l": volume,
            "particle_density_kg_m3": particle_density,
            "calibration": cal, "rows": out,
            "points": [{"size_mm": r["size_mm"], "passing_pct": r["passing_pct"],
                        "source": "hydrometer"} for r in out]}


def fractions(points: list[dict], profile: dict) -> dict:
    g, gb = interpolate_passing(points, profile["gravel_boundary_mm"])
    f, fb = interpolate_passing(points, profile["fine_boundary_mm"])
    silt_clay, sb = interpolate_passing(points, 0.002)
    out = {"gravel_pct": None if g is None else 100 - g,
           "sand_pct": None if g is None or f is None else g - f,
           "fines_pct": f, "gravel_boundary_basis": gb, "fine_boundary_basis": fb}
    if silt_clay is not None and f is not None:
        out.update({"silt_pct": f - silt_clay, "clay_pct": silt_clay,
                    "clay_boundary_basis": sb})
    else:
        out.update({"silt_pct": None, "clay_pct": None,
                    "clay_boundary_basis": "outside measured range"})
    return out


def process_test(test: dict) -> dict:
    metadata = test.get("metadata", {})
    required = ["PROJ_ID", "LOCA_ID", "SAMP_REF", "SPEC_REF", "SAMP_TOP"]
    for field in required:
        if metadata.get(field) is None or metadata.get(field) == "":
            raise InputError(f"metadata.{field} is required")
    number(metadata["SAMP_TOP"], "metadata.SAMP_TOP")
    if metadata.get("SAMP_BASE") is not None:
        if number(metadata["SAMP_BASE"], "metadata.SAMP_BASE") < float(metadata["SAMP_TOP"]):
            raise InputError("SAMP_BASE must not be above SAMP_TOP")
    profile_id = test.get("standard_profile")
    if profile_id not in PROFILES:
        raise InputError(f"standard_profile must be one of: {', '.join(PROFILES)}")
    profile = PROFILES[profile_id]
    sieve = calculate_sieve(test.get("sieve", {}), profile, test.get("sieve_method", "unconfirmed"))
    hydro = calculate_hydrometer(test["hydrometer"], sieve, profile) if test.get("hydrometer") else None
    points = sieve["points"] + (hydro["points"] if hydro else [])
    points = sorted(points, key=lambda p: p["size_mm"])
    for a, b in zip(points, points[1:]):
        if b["passing_pct"] + 1e-6 < a["passing_pct"]:
            raise InputError("Combined curve is not monotonic; inspect sieve/hydrometer linkage")
    d = {f"D{x}_mm": interpolate_log_diameter(points, float(x)) for x in (10, 30, 60)}
    cu = d["D60_mm"] / d["D10_mm"] if d["D10_mm"] and d["D60_mm"] else None
    cc = d["D30_mm"] ** 2 / (d["D10_mm"] * d["D60_mm"]) if all(d.values()) else None
    frac = fractions(points, profile)
    ags_frac = fractions(points, {"gravel_boundary_mm": 2.0, "fine_boundary_mm": 0.063})
    warnings = []
    if sieve["method"] == "unconfirmed":
        warnings.append("Sieving procedure not confirmed from source record")
    if not metadata.get("method_verified", False):
        warnings.append("Laboratory has not verified procedure against its controlled copy of the cited standard")
    if hydro and not metadata.get("hydrometer_calibration_verified", False):
        warnings.append("Hydrometer calibration/correction procedure is not verified for issue")
    for x in (10, 30, 60):
        if d[f"D{x}_mm"] is None:
            warnings.append(f"D{x} is outside measured particle-size range; not determined")
    if frac["fines_pct"] is None:
        warnings.append("Selected profile's fine boundary is not supported by measured points")
    issue_eligible = (metadata.get("method_verified") is True and
                      sieve["method"] != "unconfirmed" and
                      (not hydro or metadata.get("hydrometer_calibration_verified") is True) and
                      frac["fines_pct"] is not None)
    # Approval is a separate lab workflow. The module cannot self-certify a test.
    result = {"test_type": "grain_size", "engine_version": VERSION,
              "standard_profile": profile_id,
              "standard": profile["standard"], "split_mm": profile["split_mm"],
              "metadata": metadata, "sieve": sieve, "hydrometer": hydro,
              "curve_points": points, "d_values": d, "Cu": cu, "Cc": cc,
              "fractions_profile": frac, "fractions_ags_boundaries": ags_frac,
              "warnings": warnings, "issue_eligible": issue_eligible,
              "report_status": "DRAFT / FOR REVIEW"}
    result["ags_candidate"] = candidate_ags(result)
    return result


def candidate_ags(result: dict) -> dict:
    """Named AGS result headings; a complete AGS exchange needs its own exporter."""
    m = result["metadata"]
    keys = {k: m.get(k) for k in
            ("LOCA_ID", "SAMP_TOP", "SAMP_REF", "SAMP_TYPE", "SAMP_ID", "SPEC_REF", "SPEC_DPTH")}
    ags_f = result["fractions_ags_boundaries"]
    grag = {**keys, "GRAG_METH": result["standard"],
            "GRAG_GRAV": ags_f["gravel_pct"], "GRAG_SAND": ags_f["sand_pct"],
            "GRAG_FINE": ags_f["fines_pct"], "GRAG_SILT": ags_f["silt_pct"],
            "GRAG_CLAY": ags_f["clay_pct"], "GRAG_UC": result["Cu"]}
    sieve_type = {"dry_sieving": "DS", "wet_sieving": "WS", "unconfirmed": None}[result["sieve"]["method"]]
    grat = []
    for row in result["curve_points"]:
        grat.append({**keys, "GRAT_SIZE": row["size_mm"],
                     "GRAT_PERP": row["passing_pct"],
                     "GRAT_TYPE": "HY" if row["source"] == "hydrometer" else sieve_type})
    return {"GRAG": grag, "GRAT": grat,
            "export_note": "Candidate mapping only. Validate mandatory headings, units, precision, method codes and full AGS file against chosen AGS dictionary."}


def build_borehole_summary(results: list[dict], loca_id: str) -> dict:
    selected = [r for r in results if r["metadata"]["LOCA_ID"] == loca_id]
    if not selected:
        raise InputError(f"No results for borehole {loca_id}")
    rows = []
    for r in sorted(selected, key=lambda x: float(x["metadata"]["SAMP_TOP"])):
        m, f = r["metadata"], r["fractions_profile"]
        rows.append({"LOCA_ID": loca_id, "SAMP_TOP": m["SAMP_TOP"],
                     "SAMP_BASE": m.get("SAMP_BASE"), "SAMP_REF": m["SAMP_REF"],
                     "SPEC_REF": m["SPEC_REF"], "standard_profile": r["standard_profile"],
                     "gravel_pct": f["gravel_pct"], "sand_pct": f["sand_pct"],
                     "fines_pct": f["fines_pct"], "D10_mm": r["d_values"]["D10_mm"],
                     "D30_mm": r["d_values"]["D30_mm"], "D60_mm": r["d_values"]["D60_mm"],
                     "Cu": r["Cu"], "Cc": r["Cc"],
                     "classification_reported": m.get("classification_reported"),
                     "test_report_key": f"{loca_id}/{m['SAMP_REF']}/{m['SPEC_REF']}",
                     "status": r["report_status"]})
    return {"LOCA_ID": loca_id, "rows": rows,
            "note": "Fractions use each row's named profile boundaries; compare unlike profiles with care. Reported classification is externally supplied, not recalculated."}


def _fmt(value: Any, decimals: int = 2) -> str:
    return "ND" if value is None else f"{value:,.{decimals}f}" if isinstance(value, (int, float)) else str(value)


def _pdf_components():
    try:
        import os
        import tempfile
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "tdac_mpl_cache"))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, PageBreak
        from reportlab.lib.pagesizes import A4, landscape
    except ImportError as exc:
        raise RuntimeError("PDF generation needs reportlab and matplotlib; calculation/JSON work without them") from exc
    return locals()


def render_test_pdf(result: dict, path: str | Path) -> None:
    from io import BytesIO
    c = _pdf_components()
    plt, colors, Paragraph, Table, TableStyle = (c[x] for x in
                                                  ("plt", "colors", "Paragraph", "Table", "TableStyle"))
    styles = c["getSampleStyleSheet"]()
    styles["Title"].fontSize = 15
    styles["Title"].leading = 19
    styles["Normal"].fontSize = 8.5
    styles["Normal"].leading = 11
    doc = c["SimpleDocTemplate"](str(path), pagesize=c["A4"],
                                   leftMargin=40, rightMargin=40, topMargin=34, bottomMargin=34)
    story = [Paragraph("TDAC | PARTICLE SIZE DISTRIBUTION", styles["Title"]),
             Paragraph("DRAFT / FOR REVIEW - laboratory approval required", styles["Normal"]), c["Spacer"](1, 10)]
    m = result["metadata"]
    detail = [["Project", str(m.get("PROJ_ID")), "Borehole", str(m.get("LOCA_ID"))],
              ["Sample", str(m.get("SAMP_REF")), "Specimen", str(m.get("SPEC_REF"))],
              ["Depth (m)", f"{m.get('SAMP_TOP')} to {m.get('SAMP_BASE') or '-'}", "Test date", str(m.get("TEST_DATE") or "-")],
              ["Standard", result["standard"], "Sieve procedure", result["sieve"]["method"].replace("_", " ")]]
    story.append(_styled_table(detail, [72, 187, 78, 175], colors))
    if m.get("source_note"):
        story.append(Paragraph("Source: " + _safe(str(m["source_note"])), styles["Normal"]))
    story += [c["Spacer"](1, 9), Paragraph("SIEVE OBSERVATIONS AND CALCULATIONS", styles["Heading3"])]
    s = result["sieve"]
    story.append(Paragraph(f"Declared dry mass {_fmt(s['dry_mass_g'], 4)} g | recovered {_fmt(s['recovered_mass_g'], 4)} g | "
                           f"difference {_fmt(s['mass_difference_g'], 4)} g | pan {_fmt(s['pan_mass_g'], 4)} g | "
                           f"wash loss {_fmt(s['wash_loss_g'], 4)} g", styles["Normal"]))
    sieve_table = [["Opening mm", "Retained g", "Cum. retained g", "Cum. retained %", "Passing %"]]
    for r in s["rows"]:
        sieve_table.append([_fmt(r["size_mm"], 3), _fmt(r["retained_g"], 3),
                            _fmt(r["cumulative_retained_g"], 3),
                            _fmt(r["cumulative_retained_pct"], 2), _fmt(r["passing_pct"], 2)])
    sieve_table.append(["PAN", _fmt(s["pan_mass_g"], 3), "", "", ""])
    if s["wash_loss_g"]:
        sieve_table.append(["WASH LOSS", _fmt(s["wash_loss_g"], 3), "", "", ""])
    story.append(_styled_table(sieve_table, [96, 90, 106, 111, 109], colors, header=True))
    if result["hydrometer"]:
        story += [c["Spacer"](1, 8), Paragraph("HYDROMETER CALCULATIONS", styles["Heading3"])]
        h = result["hydrometer"]
        story.append(Paragraph(f"Fine specimen {_fmt(h['fine_test_dry_mass_g'], 3)} g | "
                               f"volume {_fmt(h['suspension_volume_l'], 3)} L | "
                               f"particle density {_fmt(h['particle_density_kg_m3'], 1)} kg/m3 | "
                               f"instrument {h['calibration']['instrument_id']}", styles["Normal"]))
        hydro_table = [["t min", "Raw", "Blank", "Corr. rdg", "Depth mm", "Temp C", "Conc. g/L", "Size mm", "Whole %"]]
        for r in h["rows"]:
            hydro_table.append([_fmt(r["elapsed_min"], 1), _fmt(r["raw_reading"], 2),
                                _fmt(r["blank_reading"], 2), _fmt(r["corrected_reading"], 2),
                                _fmt(r["effective_depth_mm"], 1), _fmt(r["temperature_c"], 1),
                                _fmt(r["concentration_g_l"], 2), _fmt(r["size_mm"], 4),
                                _fmt(r["passing_pct"], 2)])
        story.append(_styled_table(hydro_table, [48, 48, 49, 63, 61, 48, 66, 62, 67], colors, header=True))
        story += [c["PageBreak"](), Paragraph("HYDROMETER CORRECTIONS AND GRADATION CURVE", styles["Heading2"])]
        correction_table = [["t min", "Meniscus", "Temp g/L", "Disp. g/L", "Viscosity Pa s", "Water kg/m3", "Fine subset %"]]
        for r in h["rows"]:
            correction_table.append([_fmt(r["elapsed_min"], 1), _fmt(r["meniscus_correction"], 2),
                                     _fmt(r["temperature_correction_g_l"], 2),
                                     _fmt(r["dispersant_correction_g_l"], 2),
                                     _fmt(r["viscosity_pa_s"], 6),
                                     _fmt(r["water_density_kg_m3"], 1),
                                     _fmt(r["fine_subset_passing_pct"], 2)])
        story.append(_styled_table(correction_table, [58, 65, 65, 65, 93, 80, 86], colors, header=True))
        story.append(Paragraph("Instrument calibration: " + _safe(str(h["calibration"]["calibration_reference"])) +
                               f" | reading factor {_fmt(h['calibration']['g_per_l_per_reading'], 4)} g/L per unit" +
                               f" | offset {_fmt(h['calibration']['offset_g_per_l'], 4)} g/L", styles["Normal"]))
    fig, ax = plt.subplots(figsize=(7.1, 2.7), dpi=180)
    all_pts = sorted(result["curve_points"], key=lambda p: p["size_mm"])
    ax.semilogx([p["size_mm"] for p in all_pts], [p["passing_pct"] for p in all_pts],
                lw=1.25, color="#1f5e82", zorder=1)
    for source, color, marker in [("sieve", "#1f5e82", "o"), ("hydrometer", "#d47d3c", "s")]:
        pts = sorted((p for p in result["curve_points"] if p["source"] == source), key=lambda p:p["size_mm"])
        if pts:
            ax.semilogx([p["size_mm"] for p in pts], [p["passing_pct"] for p in pts],
                        linestyle="none", marker=marker, markersize=3.5,
                        label=source.capitalize(), color=color, zorder=2)
    ax.set_ylim(0, 100)
    xs = [p["size_mm"] for p in result["curve_points"]]
    ax.set_xlim(max(0.0005, min(xs) / 1.6), max(xs) * 1.5)
    ax.set_xlabel("Particle size (mm) - logarithmic")
    ax.set_ylabel("Percentage finer (% of whole dry specimen)")
    ax.grid(which="both", alpha=.25)
    ax.legend(loc="lower right", fontsize=7)
    fig.tight_layout()
    stream = BytesIO()
    fig.savefig(stream, format="png", dpi=180)
    plt.close(fig)
    stream.seek(0)
    story += [c["Spacer"](1, 4), c["Image"](stream, width=500, height=178)]
    d, f = result["d_values"], result["fractions_profile"]
    story += [Paragraph("CALCULATED RESULTS", styles["Heading3"])]
    result_table = [["D10 (mm)", "D30 (mm)", "D60 (mm)", "Cu", "Cc", "Gravel %", "Sand %", "Fines %"],
                    [_fmt(d["D10_mm"], 4), _fmt(d["D30_mm"], 4), _fmt(d["D60_mm"], 4),
                     _fmt(result["Cu"], 2), _fmt(result["Cc"], 2), _fmt(f["gravel_pct"], 1),
                     _fmt(f["sand_pct"], 1), _fmt(f["fines_pct"], 1)]]
    story.append(_styled_table(result_table, [64]*8, colors, header=True))
    fine_detail = [["Silt %", "Clay % (<0.002 mm)", "0.002 mm basis", "Curve points"],
                   [_fmt(f["silt_pct"], 1), _fmt(f["clay_pct"], 1),
                    f["clay_boundary_basis"], str(len(result["curve_points"]))]]
    story.append(_styled_table(fine_detail, [90, 122, 178, 122], colors, header=True))
    story.append(Paragraph(f"Profile boundaries: gravel > {PROFILES[result['standard_profile']]['gravel_boundary_mm']} mm; "
                           f"fines < {PROFILES[result['standard_profile']]['fine_boundary_mm']} mm. "
                           "ND = not determined from the measured range. Values within the range are interpolated on the logarithmic size axis.", styles["Normal"]))
    if result["warnings"]:
        story += [c["Spacer"](1, 5), Paragraph("REVIEW NOTES", styles["Heading3"])]
        for w in result["warnings"]:
            story.append(Paragraph("- " + _safe(w), styles["Normal"]))
    doc.build(story)


def _safe(s: str) -> str:
    from xml.sax.saxutils import escape
    return escape(s)


def _styled_table(data: list[list], widths: list[int], colors, header=False):
    from reportlab.platypus import Table, TableStyle
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    rules = [("VALIGN", (0,0), (-1,-1), "MIDDLE"),
             ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
             ("FONTSIZE", (0,0), (-1,-1), 7),
             ("BOTTOMPADDING", (0,0), (-1,-1), 3),
             ("TOPPADDING", (0,0), (-1,-1), 3),
             ("LINEBELOW", (0,-1), (-1,-1), .3, colors.HexColor("#b4c3ce"))]
    if header:
        rules += [("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e3edf3")),
                  ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                  ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f6f9fa")])]
    t.setStyle(TableStyle(rules))
    return t


def render_summary_pdf(summary: dict, path: str | Path) -> None:
    c = _pdf_components()
    styles = c["getSampleStyleSheet"]()
    styles["Normal"].fontSize = 7
    styles["Normal"].leading = 9
    doc = c["SimpleDocTemplate"](str(path), pagesize=c["landscape"](c["A4"]),
                                   leftMargin=30, rightMargin=30, topMargin=35, bottomMargin=35)
    cols = ["Depth m", "Sample", "Specimen", "Profile", "Gravel %", "Sand %", "Fines %",
            "D10 mm", "D30 mm", "D60 mm", "Cu", "Class.*", "Status"]
    data = [cols]
    for r in summary["rows"]:
        wrap = lambda v: c["Paragraph"](_safe(str(v)), styles["Normal"])
        data.append([str(r["SAMP_TOP"]), wrap(r["SAMP_REF"]), wrap(r["SPEC_REF"]), wrap(r["standard_profile"].replace("_", " ")),
                     _fmt(r["gravel_pct"], 1), _fmt(r["sand_pct"], 1), _fmt(r["fines_pct"], 1),
                     _fmt(r["D10_mm"], 4), _fmt(r["D30_mm"], 4), _fmt(r["D60_mm"], 4),
                     _fmt(r["Cu"], 2), r["classification_reported"] or "-", wrap(r["status"])])
    table = _styled_table(data, [42, 75, 75, 105, 51, 48, 48, 52, 52, 52, 43, 47, 82], c["colors"], header=True)
    doc.build([c["Paragraph"](f"TDAC | BOREHOLE {summary['LOCA_ID']} - GRAIN SIZE SUMMARY", styles["Title"]),
               c["Spacer"](1, 14), table, c["Spacer"](1, 10),
               c["Paragraph"](_safe(summary["note"]), styles["Normal"]),
               c["Paragraph"]("* Classification, if present, is supplied from an external lab record.", styles["Normal"])])


def run_file(input_path: Path, output_dir: Path, pdf: bool = True) -> list[dict]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    tests = payload.get("tests")
    if not isinstance(tests, list) or not tests:
        raise InputError("Input must contain a nonempty tests array")
    results = [process_test(t) for t in tests]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps({"results": results}, indent=2, allow_nan=False), encoding="utf-8")
    for i, r in enumerate(results, 1):
        if pdf:
            render_test_pdf(r, output_dir / f"test_{i:02d}.pdf")
    for loca in sorted({r["metadata"]["LOCA_ID"] for r in results}):
        summary = build_borehole_summary(results, loca)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in loca)
        (output_dir / f"BH_{safe}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if pdf:
            render_summary_pdf(summary, output_dir / f"BH_{safe}_summary.pdf")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("grain_size_output"))
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()
    try:
        results = run_file(args.input, args.output_dir, pdf=not args.no_pdf)
    except (InputError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(f"Processed {len(results)} test(s); outputs in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
