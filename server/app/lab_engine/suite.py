#!/usr/bin/env python3
"""Run TDAC grain-size, particle-density and Atterberg modules as one suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.lab_engine import atterberg as tdac_atterberg
from app.lab_engine import grain_size as tdac_grain_size
from app.lab_engine import particle_density as tdac_specific_gravity
from app.lab_engine.common import InputError, fmt, pdf_components, safe, styled_table

VERSION = "0.1.0"


def _sample_key(result: dict) -> tuple:
    m = result["metadata"]
    return (m["LOCA_ID"], str(m["SAMP_REF"]), float(m["SAMP_TOP"]),
            None if m.get("SAMP_BASE") is None else float(m["SAMP_BASE"]))


def build_combined_borehole_summary(grain_results: list[dict], density_results: list[dict],
                                    atterberg_results: list[dict], loca_id: str) -> dict:
    rows: dict[tuple, dict[str, Any]] = {}
    def base(result: dict) -> dict:
        m = result["metadata"]
        return {"LOCA_ID": m["LOCA_ID"], "SAMP_TOP": m["SAMP_TOP"],
                "SAMP_BASE": m.get("SAMP_BASE"), "SAMP_REF": m["SAMP_REF"],
                "classification_reported": m.get("classification_reported"),
                "grain_size": None, "particle_density": None, "atterberg": None}
    for result in grain_results:
        if result["metadata"]["LOCA_ID"] == loca_id:
            rows.setdefault(_sample_key(result), base(result))["grain_size"] = {
                "test_key": f"{loca_id}/{result['metadata']['SAMP_REF']}/{result['metadata']['SPEC_REF']}",
                "gravel_pct": result["fractions_profile"]["gravel_pct"],
                "sand_pct": result["fractions_profile"]["sand_pct"],
                "fines_pct": result["fractions_profile"]["fines_pct"],
                "D10_mm": result["d_values"]["D10_mm"], "D60_mm": result["d_values"]["D60_mm"],
                "Cu": result["Cu"], "status": result["report_status"]}
    for result in density_results:
        if result["metadata"]["LOCA_ID"] == loca_id:
            rows.setdefault(_sample_key(result), base(result))["particle_density"] = {
                "test_key": f"{loca_id}/{result['metadata']['SAMP_REF']}/{result['metadata']['SPEC_REF']}",
                "specific_gravity": result["specific_gravity"],
                "particle_density_kg_m3": result["particle_density_kg_m3"],
                "status": result["report_status"]}
    for result in atterberg_results:
        if result["metadata"]["LOCA_ID"] == loca_id:
            rows.setdefault(_sample_key(result), base(result))["atterberg"] = {
                "test_key": f"{loca_id}/{result['metadata']['SAMP_REF']}/{result['metadata']['SPEC_REF']}",
                "LL_pct": result["LL_pct"], "PL_pct": result["PL_pct"],
                "PI_pct": result["PI_pct"], "plasticity_category": result["plasticity_category"],
                "status": result["report_status"]}
    if not rows:
        raise InputError(f"No laboratory results for borehole {loca_id}")
    return {"LOCA_ID": loca_id, "suite_version": VERSION,
            "rows": sorted(rows.values(), key=lambda row: float(row["SAMP_TOP"])),
            "note": "One row per sample/depth. ND means not determined from supplied observations. Each detailed test remains independently versioned and reviewable."}


def render_combined_summary_pdf(summary: dict, path: str | Path) -> None:
    c = pdf_components()
    styles = c["getSampleStyleSheet"]()
    styles["Normal"].fontSize = 6.5
    styles["Normal"].leading = 8
    doc = c["SimpleDocTemplate"](str(path), pagesize=c["landscape"](c["A4"]),
                                   leftMargin=25, rightMargin=25, topMargin=30, bottomMargin=30)
    headers = ["Depth m", "Sample", "Gravel %", "Sand %", "Fines %", "D10 mm", "D60 mm",
               "Cu", "Gs", "rho_s kg/m3", "LL %", "PL %", "PI %", "Class.*"]
    data = [headers]
    for row in summary["rows"]:
        g = row["grain_size"] or {}
        d = row["particle_density"] or {}
        a = row["atterberg"] or {}
        depth = str(row["SAMP_TOP"]) if row["SAMP_BASE"] is None else f"{row['SAMP_TOP']}-{row['SAMP_BASE']}"
        pl = a.get("plasticity_category") or fmt(a.get("PL_pct"), 1)
        pi = a.get("plasticity_category") or fmt(a.get("PI_pct"), 1)
        data.append([depth, c["Paragraph"](safe(row["SAMP_REF"]), styles["Normal"]),
                     fmt(g.get("gravel_pct"), 1), fmt(g.get("sand_pct"), 1), fmt(g.get("fines_pct"), 1),
                     fmt(g.get("D10_mm"), 4), fmt(g.get("D60_mm"), 4), fmt(g.get("Cu"), 2),
                     fmt(d.get("specific_gravity"), 3), fmt(d.get("particle_density_kg_m3"), 0),
                     fmt(a.get("LL_pct"), 1), pl, pi, row.get("classification_reported") or "-"])
    table = styled_table(data, [48, 70, 49, 49, 49, 51, 51, 43, 44, 72, 43, 43, 43, 52],
                         c["colors"], header=True, font_size=6.5)
    story = [c["Paragraph"](f"TDAC | BOREHOLE {safe(summary['LOCA_ID'])} - LABORATORY SUMMARY", styles["Title"]),
             c["Spacer"](1, 12), table, c["Spacer"](1, 9),
             c["Paragraph"](safe(summary["note"]), styles["Normal"]),
             c["Paragraph"]("* Classification, if present, is carried from an external record and is not calculated by this package.", styles["Normal"])]
    doc.build(story)


def load_tests(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    tests = payload.get("tests")
    if not isinstance(tests, list):
        raise InputError(f"{path} must contain a tests array")
    return tests


def run_suite(grain_tests: list[dict], density_tests: list[dict], atterberg_tests: list[dict],
              output_dir: Path, pdf: bool = True) -> dict:
    g_results = [tdac_grain_size.process_test(t) for t in grain_tests]
    d_results = [tdac_specific_gravity.process_test(t) for t in density_tests]
    a_results = [tdac_atterberg.process_test(t) for t in atterberg_tests]
    if not (g_results or d_results or a_results):
        raise InputError("At least one test is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    details_dir = output_dir / "detailed_reports"
    if pdf:
        details_dir.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(g_results, 1):
            tdac_grain_size.render_test_pdf(r, details_dir / f"grain_size_{i:02d}.pdf")
        for i, r in enumerate(d_results, 1):
            tdac_specific_gravity.render_test_pdf(r, details_dir / f"particle_density_{i:02d}.pdf")
        for i, r in enumerate(a_results, 1):
            tdac_atterberg.render_test_pdf(r, details_dir / f"atterberg_{i:02d}.pdf")
    all_results = {"suite_version": VERSION, "grain_size": g_results,
                   "particle_density": d_results, "atterberg": a_results}
    (output_dir / "calculation_results.json").write_text(json.dumps(all_results, indent=2, allow_nan=False), encoding="utf-8")
    locations = sorted({r["metadata"]["LOCA_ID"] for r in g_results + d_results + a_results})
    summaries = []
    for loca in locations:
        summary = build_combined_borehole_summary(g_results, d_results, a_results, loca)
        summaries.append(summary)
        safe_loca = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in loca)
        (output_dir / f"BH_{safe_loca}_laboratory_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if pdf:
            render_combined_summary_pdf(summary, output_dir / f"BH_{safe_loca}_laboratory_summary.pdf")
    return {"results": all_results, "summaries": summaries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grain-size", type=Path)
    parser.add_argument("--particle-density", type=Path)
    parser.add_argument("--atterberg", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("tdac_lab_output"))
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()
    try:
        result = run_suite(load_tests(args.grain_size), load_tests(args.particle_density),
                           load_tests(args.atterberg), args.output_dir, not args.no_pdf)
    except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    count = sum(len(v) for v in result["results"].values() if isinstance(v, list))
    print(f"Processed {count} test(s); outputs in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
