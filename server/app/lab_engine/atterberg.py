#!/usr/bin/env python3
"""TDAC liquid-limit and plastic-limit calculation module, v0.1.0.

Ported verbatim from the TDAC Basic Lab Developer Package: only the import
line below changed (tdac_lab_common -> app.lab_engine.common). The
calculation bodies are byte-identical to the verified package.
"""

from __future__ import annotations

import argparse
import json
import math
from io import BytesIO
from pathlib import Path

from app.lab_engine.common import (InputError, fmt, linear_regression, mean,
                             metadata_table, nonnegative, number, pdf_components,
                             require_metadata, safe, styled_table, water_content)

VERSION = "0.1.0"
PROFILES = {
    "IS_2720_5_1985": "IS 2720 (Part 5):1985",
    "ISO_17892_12_2018_A1_2021_A2_2022": "ISO 17892-12:2018 + Amd 1:2021 + Amd 2:2022",
}


def _calculate_liquid_limit(section: dict, method: str) -> dict:
    trials_in = section.get("TDAC_LL_TRIALS")
    if not isinstance(trials_in, list) or len(trials_in) < 3:
        raise InputError("At least three liquid-limit trials are required")
    trials = []
    controls = []
    contents = []
    control_field = "TDAC_BLOW_COUNT" if method == "casagrande" else "TDAC_PENETRATION_MM"
    for i, row in enumerate(trials_in, 1):
        wc = water_content(row, f"liquid-limit trial {i}")
        control = number(row.get(control_field), f"liquid-limit trial {i} {control_field}", positive=True)
        trials.append({"trial": i, **wc, "control_value": control})
        controls.append(control)
        contents.append(wc["water_content_pct"])
    if len(set(controls)) != len(controls):
        raise InputError("Liquid-limit control values must be distinct")
    reg = linear_regression([math.log10(x) for x in controls], contents)
    if method == "casagrande":
        reference = 25.0
        if reg["slope"] >= 0:
            raise InputError("Casagrande water content must decrease as blow count increases")
        flow_index = -reg["slope"]
    else:
        reference = number(section.get("TDAC_REFERENCE_PENETRATION_MM"),
                           "TDAC_REFERENCE_PENETRATION_MM", positive=True)
        cone_mass = number(section.get("TDAC_CONE_MASS_G"), "TDAC_CONE_MASS_G", positive=True)
        cone_angle = number(section.get("TDAC_CONE_ANGLE_DEG"), "TDAC_CONE_ANGLE_DEG", positive=True)
        if reg["slope"] <= 0:
            raise InputError("Fall-cone water content must increase as penetration increases")
        flow_index = None
    ll = reg["intercept"] + reg["slope"] * math.log10(reference)
    for row, fitted in zip(trials, reg["fitted"]):
        row["fitted_water_content_pct"] = fitted
        row["residual_pct"] = row["water_content_pct"] - fitted
    result = {"method": method, "reference_control": reference, "trials": trials,
            "liquid_limit_pct": ll, "regression": {k: reg[k] for k in
            ("slope", "intercept", "r_squared")}, "flow_index": flow_index,
            "reference_bracketed": min(controls) <= reference <= max(controls)}
    if method == "fall_cone":
        result.update({"cone_mass_g": cone_mass, "cone_angle_deg": cone_angle})
    return result


def _calculate_plastic_limit(section: dict) -> dict:
    non_plastic = bool(section.get("TDAC_NON_PLASTIC", False))
    rows = section.get("TDAC_PL_TRIALS", [])
    if non_plastic:
        if rows:
            raise InputError("A non-plastic result cannot also contain plastic-limit trials")
        return {"non_plastic": True, "trials": [], "plastic_limit_pct": None,
                "range_pct": None, "replicate_pass": True}
    if not isinstance(rows, list) or len(rows) < 2:
        raise InputError("At least two plastic-limit determinations are required, or mark non-plastic")
    trials = [{"trial": i, **water_content(row, f"plastic-limit trial {i}")}
              for i, row in enumerate(rows, 1)]
    values = [r["water_content_pct"] for r in trials]
    tolerance = section.get("TDAC_PL_RANGE_TOLERANCE_PCT")
    if tolerance is None:
        raise InputError("TDAC_PL_RANGE_TOLERANCE_PCT must be supplied from the lab QA method")
    tolerance = nonnegative(tolerance, "TDAC_PL_RANGE_TOLERANCE_PCT")
    spread = max(values) - min(values)
    return {"non_plastic": False, "trials": trials, "plastic_limit_pct": mean(values),
            "range_pct": spread, "range_tolerance_pct": tolerance,
            "replicate_pass": spread <= tolerance + 1e-12}


def process_test(test: dict) -> dict:
    metadata = test.get("metadata", {})
    require_metadata(metadata)
    profile_id = test.get("standard_profile")
    if profile_id not in PROFILES:
        raise InputError(f"standard_profile must be one of: {', '.join(PROFILES)}")
    method = test.get("liquid_limit_method")
    if method not in {"casagrande", "fall_cone"}:
        raise InputError("liquid_limit_method must be casagrande or fall_cone")
    if profile_id == "IS_2720_5_1985" and method != "casagrande":
        raise InputError("This IS implementation supports the multipoint Casagrande method")
    liquid = _calculate_liquid_limit(test.get("liquid_limit", {}), method)
    plastic = _calculate_plastic_limit(test.get("plastic_limit", {}))
    r2_min = test.get("TDAC_LL_R2_MIN")
    if r2_min is None:
        raise InputError("TDAC_LL_R2_MIN must be supplied from the lab QA method")
    r2_min = number(r2_min, "TDAC_LL_R2_MIN")
    if not 0 <= r2_min <= 1:
        raise InputError("TDAC_LL_R2_MIN must be between 0 and 1")
    ll = liquid["liquid_limit_pct"]
    if plastic["non_plastic"]:
        pl = pi = None
        category = "NP"
    else:
        pl = plastic["plastic_limit_pct"]
        pi = ll - pl
        if pi < 0:
            raise InputError("Calculated plastic limit exceeds liquid limit")
        category = None
    natural = metadata.get("natural_water_content_pct")
    if natural is not None:
        natural = nonnegative(natural, "metadata.natural_water_content_pct")
    liquidity = ((natural - pl) / pi if natural is not None and pl is not None and pi and pi > 0 else None)
    consistency = ((ll - natural) / pi if natural is not None and pi and pi > 0 else None)
    toughness = (pi / liquid["flow_index"] if pi is not None and liquid["flow_index"] else None)
    warnings = []
    if not liquid["reference_bracketed"]:
        warnings.append("Liquid-limit reference lies outside observed control values; result is extrapolated")
    if liquid["regression"]["r_squared"] < r2_min:
        warnings.append(f"Liquid-limit regression R2 is below laboratory QA minimum {r2_min}")
    if not plastic["replicate_pass"]:
        warnings.append("Plastic-limit replicate spread exceeds the entered laboratory tolerance")
    if not metadata.get("method_verified", False):
        warnings.append("Laboratory has not verified the procedure against its controlled standard")
    if not metadata.get("equipment_calibration_verified", False):
        warnings.append("Equipment/calibration verification is incomplete")
    issue_eligible = bool(metadata.get("method_verified") and
                          metadata.get("equipment_calibration_verified") and
                          liquid["reference_bracketed"] and
                          liquid["regression"]["r_squared"] >= r2_min and
                          plastic["replicate_pass"])
    result = {
        "test_type": "atterberg", "engine_version": VERSION,
        "standard_profile": profile_id, "standard": PROFILES[profile_id],
        "liquid_limit_method": method, "metadata": metadata,
        "liquid_limit": liquid, "plastic_limit": plastic,
        "LL_pct": ll, "PL_pct": pl, "PI_pct": pi, "plasticity_category": category,
        "flow_index": liquid["flow_index"], "toughness_index": toughness,
        "liquidity_index": liquidity, "consistency_index": consistency,
        "ll_r2_min": r2_min, "warnings": warnings,
        "issue_eligible": issue_eligible, "report_status": "DRAFT / FOR REVIEW",
    }
    value_pl = "NP" if category == "NP" else pl
    value_pi = "NP" if category == "NP" else pi
    result["ags_candidate"] = {
        "LLPL": {**{k: metadata.get(k) for k in
                    ("LOCA_ID", "SAMP_TOP", "SAMP_REF", "SAMP_TYPE", "SAMP_ID", "SPEC_REF", "SPEC_DPTH")},
                 "LLPL_METH": method, "LLPL_LL": ll, "LLPL_PL": value_pl,
                 "LLPL_PI": value_pi, "LLPL_REM": metadata.get("remarks")},
        "export_note": "Candidate mapping only. NP is categorical, never numeric zero. Validate headings, units, precision and method codes against the chosen AGS dictionary."
    }
    return result


def render_test_pdf(result: dict, path: str | Path) -> None:
    c = pdf_components()
    plt = c["plt"]
    styles = c["getSampleStyleSheet"]()
    styles["Normal"].fontSize = 8.5
    styles["Normal"].leading = 11
    doc = c["SimpleDocTemplate"](str(path), pagesize=c["A4"], leftMargin=40,
                                   rightMargin=40, topMargin=34, bottomMargin=34)
    story = [c["Paragraph"]("TDAC | LIQUID AND PLASTIC LIMITS", styles["Title"]),
             c["Paragraph"]("DRAFT / FOR REVIEW - laboratory approval required", styles["Normal"]),
             c["Spacer"](1, 10), metadata_table(result["metadata"], result["standard"],
                                                        result["liquid_limit_method"], c["colors"]),
             c["Spacer"](1, 9), c["Paragraph"]("LIQUID-LIMIT OBSERVATIONS", styles["Heading3"])]
    control_name = "Blows" if result["liquid_limit_method"] == "casagrande" else "Penetration mm"
    ll_data = [["Trial", control_name, "Container g", "Wet + container g", "Dry + container g", "Water %", "Fitted %", "Residual"]]
    for r in result["liquid_limit"]["trials"]:
        ll_data.append([r["trial"], fmt(r["control_value"], 2), fmt(r["container_g"], 3),
                        fmt(r["container_wet_g"], 3), fmt(r["container_dry_g"], 3),
                        fmt(r["water_content_pct"], 2), fmt(r["fitted_water_content_pct"], 2),
                        fmt(r["residual_pct"], 2)])
    story.append(styled_table(ll_data, [41, 70, 67, 88, 88, 58, 58, 54], c["colors"], header=True))
    if result["liquid_limit_method"] == "fall_cone":
        story.append(c["Paragraph"](
            f"Cone {fmt(result['liquid_limit']['cone_mass_g'], 1)} g / "
            f"{fmt(result['liquid_limit']['cone_angle_deg'], 1)} degrees; "
            f"reference penetration {fmt(result['liquid_limit']['reference_control'], 1)} mm.",
            styles["Normal"]))
    controls = [r["control_value"] for r in result["liquid_limit"]["trials"]]
    contents = [r["water_content_pct"] for r in result["liquid_limit"]["trials"]]
    xmin, xmax = min(controls), max(controls)
    line_x = [10 ** (math.log10(xmin) + i * (math.log10(xmax) - math.log10(xmin)) / 100) for i in range(101)]
    reg = result["liquid_limit"]["regression"]
    line_y = [reg["intercept"] + reg["slope"] * math.log10(x) for x in line_x]
    fig, ax = plt.subplots(figsize=(7.0, 2.55), dpi=180)
    ax.semilogx(line_x, line_y, color="#1f5e82", lw=1.3)
    ax.scatter(controls, contents, color="#d47d3c", s=18, zorder=3)
    ref = result["liquid_limit"]["reference_control"]
    ax.scatter([ref], [result["LL_pct"]], color="#a02c2c", marker="D", s=24, zorder=4, label="Liquid limit")
    ax.set_xlabel(control_name + " - logarithmic")
    ax.set_ylabel("Water content (%)")
    ax.grid(which="both", alpha=.25)
    ax.legend(fontsize=7)
    fig.tight_layout()
    stream = BytesIO()
    fig.savefig(stream, format="png", dpi=180)
    plt.close(fig)
    stream.seek(0)
    story += [c["Spacer"](1, 5), c["Image"](stream, width=500, height=182),
              c["Paragraph"]("PLASTIC-LIMIT OBSERVATIONS", styles["Heading3"])]
    if result["plastic_limit"]["non_plastic"]:
        story.append(c["Paragraph"]("Recorded category: NON-PLASTIC (NP). No numeric zero is stored.", styles["Normal"]))
    else:
        pl_data = [["Trial", "Container g", "Wet + container g", "Dry + container g", "Water %"]]
        for r in result["plastic_limit"]["trials"]:
            pl_data.append([r["trial"], fmt(r["container_g"], 3), fmt(r["container_wet_g"], 3),
                            fmt(r["container_dry_g"], 3), fmt(r["water_content_pct"], 2)])
        story.append(styled_table(pl_data, [60, 102, 118, 118, 90], c["colors"], header=True))
    story += [c["Spacer"](1, 7), c["Paragraph"]("CALCULATED RESULTS", styles["Heading3"])]
    values = [["LL %", "PL %", "PI %", "Flow index", "Toughness", "Liquidity", "Consistency", "LL R2"],
              [fmt(result["LL_pct"], 1), result["plasticity_category"] or fmt(result["PL_pct"], 1),
               result["plasticity_category"] or fmt(result["PI_pct"], 1), fmt(result["flow_index"], 2),
               fmt(result["toughness_index"], 2), fmt(result["liquidity_index"], 2),
               fmt(result["consistency_index"], 2), fmt(reg["r_squared"], 4)]]
    story.append(styled_table(values, [64] * 8, c["colors"], header=True))
    story.append(c["Paragraph"]("Water contents are calculated from container masses. PI = LL - PL. Liquidity and consistency indices are shown only when natural water content is supplied; toughness is shown only for Casagrande flow-index results.", styles["Normal"]))
    if result["warnings"]:
        story += [c["Spacer"](1, 6), c["Paragraph"]("REVIEW NOTES", styles["Heading3"])]
        for item in result["warnings"]:
            story.append(c["Paragraph"]("- " + safe(item), styles["Normal"]))
    doc.build(story)


def build_borehole_summary(results: list[dict], loca_id: str) -> dict:
    selected = sorted((r for r in results if r["metadata"]["LOCA_ID"] == loca_id),
                      key=lambda r: float(r["metadata"]["SAMP_TOP"]))
    if not selected:
        raise InputError(f"No Atterberg results for borehole {loca_id}")
    return {"LOCA_ID": loca_id, "rows": [{
        "SAMP_TOP": r["metadata"]["SAMP_TOP"], "SAMP_BASE": r["metadata"].get("SAMP_BASE"),
        "SAMP_REF": r["metadata"]["SAMP_REF"], "SPEC_REF": r["metadata"]["SPEC_REF"],
        "standard_profile": r["standard_profile"], "method": r["liquid_limit_method"],
        "LL_pct": r["LL_pct"], "PL_pct": r["PL_pct"], "PI_pct": r["PI_pct"],
        "plasticity_category": r["plasticity_category"], "status": r["report_status"]} for r in selected]}


def run_file(input_path: Path, output_dir: Path, pdf: bool = True) -> list[dict]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    tests = payload.get("tests")
    if not isinstance(tests, list) or not tests:
        raise InputError("Input must contain a nonempty tests array")
    results = [process_test(t) for t in tests]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps({"results": results}, indent=2, allow_nan=False), encoding="utf-8")
    if pdf:
        for i, r in enumerate(results, 1):
            render_test_pdf(r, output_dir / f"atterberg_{i:02d}.pdf")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("atterberg_output"))
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()
    try:
        results = run_file(args.input, args.output_dir, not args.no_pdf)
    except (InputError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(f"Processed {len(results)} Atterberg test(s); outputs in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
