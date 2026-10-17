#!/usr/bin/env python3
"""TDAC specific-gravity / particle-density calculation module, v0.1.0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.lab_engine.common import (InputError, fmt, mean, metadata_table, nonnegative,
                             number, pdf_components, require_metadata, safe,
                             styled_table)

VERSION = "0.1.0"
PROFILES = {
    "IS_2720_3_SEC1_1980": "IS 2720 (Part 3/Sec 1):1980",
    "IS_2720_3_SEC2_1980": "IS 2720 (Part 3/Sec 2):1980",
    "ISO_17892_3_2015": "ISO 17892-3:2015",
}


def _fluid_trial(row: dict, index: int) -> dict:
    tag = f"trial {index}"
    m1 = nonnegative(row.get("TDAC_M1_EMPTY_PYCNOMETER_G"), tag + " M1")
    m2 = number(row.get("TDAC_M2_PYC_DRY_SOIL_G"), tag + " M2")
    m3 = number(row.get("TDAC_M3_PYC_SOIL_FLUID_G"), tag + " M3")
    m4 = number(row.get("TDAC_M4_PYC_FLUID_G"), tag + " M4")
    rho_f = number(row.get("TDAC_FLUID_DENSITY_KG_M3"), tag + " fluid density", positive=True)
    rho_ref = number(row.get("TDAC_REFERENCE_WATER_DENSITY_KG_M3"),
                     tag + " reference water density", positive=True)
    temp = number(row.get("TDAC_TEMPERATURE_C"), tag + " temperature")
    soil_mass = m2 - m1
    displaced_fluid_mass = soil_mass - (m3 - m4)
    if soil_mass <= 0 or displaced_fluid_mass <= 0:
        raise InputError(f"{tag}: require M2>M1 and positive displaced-fluid mass")
    rho_s = soil_mass * rho_f / displaced_fluid_mass
    gs = rho_s / rho_ref
    return {"trial": index, "method": "fluid_pycnometer", "temperature_c": temp,
            "m1_g": m1, "m2_g": m2, "m3_g": m3, "m4_g": m4,
            "dry_soil_mass_g": soil_mass, "displaced_fluid_mass_g": displaced_fluid_mass,
            "fluid_density_kg_m3": rho_f, "reference_water_density_kg_m3": rho_ref,
            "particle_density_kg_m3": rho_s, "specific_gravity": gs}


def _gas_trial(row: dict, index: int) -> dict:
    tag = f"trial {index}"
    mass = number(row.get("TDAC_DRY_SOIL_MASS_G"), tag + " dry mass", positive=True)
    volume = number(row.get("TDAC_PARTICLE_VOLUME_CM3"), tag + " particle volume", positive=True)
    rho_ref = number(row.get("TDAC_REFERENCE_WATER_DENSITY_KG_M3"),
                     tag + " reference water density", positive=True)
    temp = number(row.get("TDAC_TEMPERATURE_C"), tag + " temperature")
    rho_s = mass / volume * 1000.0
    return {"trial": index, "method": "gas_pycnometer", "temperature_c": temp,
            "dry_soil_mass_g": mass, "particle_volume_cm3": volume,
            "reference_water_density_kg_m3": rho_ref,
            "particle_density_kg_m3": rho_s, "specific_gravity": rho_s / rho_ref}


def process_test(test: dict) -> dict:
    metadata = test.get("metadata", {})
    require_metadata(metadata)
    profile_id = test.get("standard_profile")
    if profile_id not in PROFILES:
        raise InputError(f"standard_profile must be one of: {', '.join(PROFILES)}")
    method = test.get("method")
    if method not in {"fluid_pycnometer", "gas_pycnometer"}:
        raise InputError("method must be fluid_pycnometer or gas_pycnometer")
    if method == "gas_pycnometer" and profile_id != "ISO_17892_3_2015":
        raise InputError("gas_pycnometer is only available in the ISO profile")
    trials_in = test.get("trials")
    if not isinstance(trials_in, list) or not trials_in:
        raise InputError("trials must be a nonempty array")
    calculator = _fluid_trial if method == "fluid_pycnometer" else _gas_trial
    trials = [calculator(row, i + 1) for i, row in enumerate(trials_in)]
    rho_values = [r["particle_density_kg_m3"] for r in trials]
    gs_values = [r["specific_gravity"] for r in trials]
    rho_mean, gs_mean = mean(rho_values), mean(gs_values)
    rho_range, gs_range = max(rho_values) - min(rho_values), max(gs_values) - min(gs_values)
    tolerance = test.get("TDAC_REPLICATE_TOLERANCE")
    tolerance_basis = test.get("TDAC_TOLERANCE_BASIS", "specific_gravity")
    if tolerance_basis not in {"specific_gravity", "particle_density_kg_m3"}:
        raise InputError("TDAC_TOLERANCE_BASIS must be specific_gravity or particle_density_kg_m3")
    if tolerance is None:
        raise InputError("TDAC_REPLICATE_TOLERANCE must be supplied from the lab QA method")
    tolerance = nonnegative(tolerance, "TDAC_REPLICATE_TOLERANCE")
    spread = gs_range if tolerance_basis == "specific_gravity" else rho_range
    replicate_pass = len(trials) >= 2 and spread <= tolerance + 1e-12
    warnings = []
    if len(trials) < 2:
        warnings.append("Only one determination supplied; replicate acceptance cannot pass")
    if not replicate_pass:
        warnings.append(f"Replicate spread {spread:.4g} exceeds or cannot satisfy tolerance {tolerance:.4g}")
    if not metadata.get("method_verified", False):
        warnings.append("Laboratory has not verified the procedure against its controlled standard")
    if not metadata.get("equipment_calibration_verified", False):
        warnings.append("Equipment/calibration verification is incomplete")
    issue_eligible = bool(metadata.get("method_verified") and
                          metadata.get("equipment_calibration_verified") and replicate_pass)
    result = {
        "test_type": "particle_density", "engine_version": VERSION,
        "standard_profile": profile_id, "standard": PROFILES[profile_id],
        "method": method, "metadata": metadata, "trials": trials,
        "particle_density_kg_m3": rho_mean, "specific_gravity": gs_mean,
        "particle_density_range_kg_m3": rho_range, "specific_gravity_range": gs_range,
        "replicate_tolerance": tolerance, "tolerance_basis": tolerance_basis,
        "replicate_pass": replicate_pass, "warnings": warnings,
        "issue_eligible": issue_eligible, "report_status": "DRAFT / FOR REVIEW",
    }
    result["ags_candidate"] = {
        "LPDN": {**{k: metadata.get(k) for k in
                    ("LOCA_ID", "SAMP_TOP", "SAMP_REF", "SAMP_TYPE", "SAMP_ID", "SPEC_REF", "SPEC_DPTH")},
                 "LPDN_METH": PROFILES[profile_id], "LPDN_PDEN": rho_mean,
                 "LPDN_REM": metadata.get("remarks")},
        "export_note": "Candidate mapping only; validate exact headings, units, precision and mandatory keys against the chosen AGS dictionary."
    }
    return result


def render_test_pdf(result: dict, path: str | Path) -> None:
    c = pdf_components()
    styles = c["getSampleStyleSheet"]()
    styles["Normal"].fontSize = 8.5
    styles["Normal"].leading = 11
    doc = c["SimpleDocTemplate"](str(path), pagesize=c["A4"], leftMargin=40,
                                   rightMargin=40, topMargin=34, bottomMargin=34)
    story = [c["Paragraph"]("TDAC | PARTICLE DENSITY / SPECIFIC GRAVITY", styles["Title"]),
             c["Paragraph"]("DRAFT / FOR REVIEW - laboratory approval required", styles["Normal"]),
             c["Spacer"](1, 10), metadata_table(result["metadata"], result["standard"],
                                                        result["method"], c["colors"]),
             c["Spacer"](1, 10), c["Paragraph"]("RAW OBSERVATIONS AND CALCULATIONS", styles["Heading3"])]
    if result["method"] == "fluid_pycnometer":
        data = [["Trial", "M1 g", "M2 g", "M3 g", "M4 g", "Temp C", "Fluid kg/m3", "rho_s kg/m3", "Gs"]]
        for r in result["trials"]:
            data.append([r["trial"], fmt(r["m1_g"], 3), fmt(r["m2_g"], 3), fmt(r["m3_g"], 3),
                         fmt(r["m4_g"], 3), fmt(r["temperature_c"], 1), fmt(r["fluid_density_kg_m3"], 1),
                         fmt(r["particle_density_kg_m3"], 1), fmt(r["specific_gravity"], 3)])
        story.append(styled_table(data, [37, 52, 52, 52, 52, 48, 66, 72, 45], c["colors"], header=True))
    else:
        data = [["Trial", "Dry mass g", "Volume cm3", "Temp C", "Water ref kg/m3", "rho_s kg/m3", "Gs"]]
        for r in result["trials"]:
            data.append([r["trial"], fmt(r["dry_soil_mass_g"], 3), fmt(r["particle_volume_cm3"], 3),
                         fmt(r["temperature_c"], 1), fmt(r["reference_water_density_kg_m3"], 1),
                         fmt(r["particle_density_kg_m3"], 1), fmt(r["specific_gravity"], 3)])
        story.append(styled_table(data, [45, 78, 78, 60, 96, 88, 55], c["colors"], header=True))
    story += [c["Spacer"](1, 10), c["Paragraph"]("CALCULATED RESULTS", styles["Heading3"])]
    summary = [["Mean particle density kg/m3", "Mean specific gravity", "rho_s range kg/m3", "Gs range", "Replicate QA"],
               [fmt(result["particle_density_kg_m3"], 1), fmt(result["specific_gravity"], 3),
                fmt(result["particle_density_range_kg_m3"], 1), fmt(result["specific_gravity_range"], 4),
                "PASS" if result["replicate_pass"] else "REVIEW"]]
    story.append(styled_table(summary, [116, 105, 105, 85, 101], c["colors"], header=True))
    story.append(c["Paragraph"]("The fluid calculation uses measured displaced-fluid mass and the entered fluid density; Gs is relative to the entered reference-water density.", styles["Normal"]))
    if result["warnings"]:
        story += [c["Spacer"](1, 7), c["Paragraph"]("REVIEW NOTES", styles["Heading3"])]
        for item in result["warnings"]:
            story.append(c["Paragraph"]("- " + safe(item), styles["Normal"]))
    doc.build(story)


def build_borehole_summary(results: list[dict], loca_id: str) -> dict:
    selected = sorted((r for r in results if r["metadata"]["LOCA_ID"] == loca_id),
                      key=lambda r: float(r["metadata"]["SAMP_TOP"]))
    if not selected:
        raise InputError(f"No particle-density results for borehole {loca_id}")
    return {"LOCA_ID": loca_id, "rows": [{
        "SAMP_TOP": r["metadata"]["SAMP_TOP"], "SAMP_BASE": r["metadata"].get("SAMP_BASE"),
        "SAMP_REF": r["metadata"]["SAMP_REF"], "SPEC_REF": r["metadata"]["SPEC_REF"],
        "standard_profile": r["standard_profile"], "particle_density_kg_m3": r["particle_density_kg_m3"],
        "specific_gravity": r["specific_gravity"], "status": r["report_status"]} for r in selected]}


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
            render_test_pdf(r, output_dir / f"particle_density_{i:02d}.pdf")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("particle_density_output"))
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()
    try:
        results = run_file(args.input, args.output_dir, not args.no_pdf)
    except (InputError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(f"Processed {len(results)} particle-density test(s); outputs in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
