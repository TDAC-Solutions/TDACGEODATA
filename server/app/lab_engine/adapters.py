"""Translate between the Results Entry raw snapshot and the lab engine's
test-record contract. The engines are never touched; this file is the only
place that knows both shapes.

Direction 1: engine_input()   app snapshot + method config  ->  engine record
Direction 2: engine_output()  engine result                ->  display shape

Design rules:
* The client grid is unordered and may hold blank rows; the engines demand
  strictly ordered sieve stacks and complete trials. Sorting sieves and
  dropping fully-blank rows here is translation, not physics.
* Rows the technician ticked "use = No" are excluded before the engine sees
  them, which is exactly what the browser preview does today.
* Numeric defaults the UI does not capture yet (pan mass, fluid density from
  temperature via Kell 1975) are filled here so the engine's documented
  contract is satisfied; measured values always win when present.
* Messages the engines raise use TDAC_* field names. humanize_message()
  rewrites the common ones into the words the Results Entry form uses, so a
  400 from the server reads like a form error, not a schema error.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.lab_engine.common import InputError
from app.lab_engine import atterberg, grain_size, particle_density

_PROCESSORS = {
    "PSD": grain_size.process_test,
    "PARTICLE_DENSITY": particle_density.process_test,
    "ATTERBERG": atterberg.process_test,
}

SUPPORTED_TESTS = tuple(_PROCESSORS)

# Output keys written for each test type. The migration declares exactly
# these keys in lab.method_definition.result_schema, so the publish step can
# only release values the engine actually produced.
DECLARED_OUTPUTS = {
    "PSD": (
        "gravel_pct", "sand_pct", "fines_pct", "silt_pct", "clay_pct",
        "d10_mm", "d30_mm", "d60_mm", "cu", "cc",
    ),
    "PARTICLE_DENSITY": ("specific_gravity", "particle_density"),
    "ATTERBERG": ("liquid_limit", "plastic_limit", "plasticity_index", "flow_index"),
}

# Standard profiles the engines implement, by test type. The migration pins
# the profile per method in validation_schema; this is only the fallback for
# methods configured before that migration ran.
FALLBACK_PROFILE = {
    "PSD": "IS_2720_4_1985",
    "PARTICLE_DENSITY": "IS_2720_3_SEC1_1980",
    "ATTERBERG": "IS_2720_5_1985",
}


# --------------------------------------------------------------------- helpers

def _num(value: Any) -> float | None:
    """UI values arrive as strings ('' when blank) or numbers."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rho_water_kell(t_c: float) -> float:
    """Kell (1975) water density, kg/m3, 0-40 C. Used only as a default when
    the technician did not measure the fluid density -- the same formula the
    client preview engine uses, so preview and server agree."""
    t = float(t_c)
    return (
        999.83952 + 16.945176 * t - 7.9870401e-3 * t ** 2
        - 46.170461e-6 * t ** 3 + 105.56302e-9 * t ** 4
        - 280.54253e-12 * t ** 5
    ) / (1 + 16.87985e-3 * t)


def _used(rows: list[dict]) -> list[dict]:
    """Drop trials the technician flagged Use=No (the UI stores 'false')."""
    return [r for r in rows if str(r.get("use", "true")).lower() != "false"]


def _blank(row: dict, keys: tuple[str, ...]) -> bool:
    return all(str(row.get(k, "") or "").strip() == "" for k in keys)


_MESSAGE_LABELS = {
    "TDAC_DRY_MASS_G": "dry specimen mass",
    "TDAC_PAN_MASS_G": "pan mass",
    "TDAC_WASH_LOSS_G": "wash loss",
    "TDAC_MASS_TOLERANCE_PCT": "mass tolerance",
    "TDAC_RETAINED_G": "retained mass",
    "GRAT_SIZE": "sieve size",
    "TDAC_SIEVE_ROWS": "sieve readings",
    "TDAC_FINE_TEST_DRY_MASS_G": "fine specimen dry mass",
    "TDAC_SUSPENSION_VOLUME_L": "suspension volume",
    "TDAC_PARTICLE_DENSITY_KG_M3": "particle density",
    "TDAC_M1_EMPTY_PYCNOMETER_G": "M1 (empty pycnometer)",
    "TDAC_M2_PYC_DRY_SOIL_G": "M2 (pycnometer + dry soil)",
    "TDAC_M3_PYC_SOIL_FLUID_G": "M3 (pycnometer + soil + fluid)",
    "TDAC_M4_PYC_FLUID_G": "M4 (pycnometer + fluid)",
    "TDAC_FLUID_DENSITY_KG_M3": "fluid density",
    "TDAC_REFERENCE_WATER_DENSITY_KG_M3": "reference water density",
    "TDAC_TEMPERATURE_C": "temperature",
    "TDAC_REPLICATE_TOLERANCE": "replicate tolerance",
    "TDAC_BLOW_COUNT": "blow count",
    "TDAC_PENETRATION_MM": "penetration",
    "TDAC_CONTAINER_G": "container mass",
    "TDAC_CONTAINER_WET_G": "container + wet soil",
    "TDAC_CONTAINER_DRY_G": "container + dry soil",
    "TDAC_LL_TRIALS": "liquid-limit trials",
    "TDAC_PL_TRIALS": "plastic-limit trials",
    "TDAC_PL_RANGE_TOLERANCE_PCT": "plastic-limit range tolerance",
    "TDAC_LL_R2_MIN": "liquid-limit R2 minimum",
    "TDAC_NON_PLASTIC": "non-plastic flag",
    "TDAC_REFERENCE_PENETRATION_MM": "reference penetration",
    "TDAC_CONE_MASS_G": "cone mass",
    "TDAC_CONE_ANGLE_DEG": "cone angle",
    "natural_water_content_pct": "natural water content",
}

_TDAC_TOKEN = re.compile(r"\b(?:TDAC_|GRAT_)[A-Z0-9_]+\b")
_METADATA_TOKEN = re.compile(r"\bmetadata\.([A-Za-z0-9_]+)\b")


def humanize_message(message: str) -> str:
    """Rewrite engine field tokens into the words the Results Entry form uses.

    Two token shapes reach the user:
      * TDAC_*/GRAT_* uppercase schema names
      * metadata.<field> lowercase names (the engines' require_metadata and
        nonnegative labels, e.g. metadata.natural_water_content_pct)
    """
    def replace(match: re.Match) -> str:
        token = match.group(0)
        return _MESSAGE_LABELS.get(token, token.replace("TDAC_", "").replace("GRAT_", "").replace("_", " ").lower())

    message = _TDAC_TOKEN.sub(replace, str(message))

    def replace_metadata(match: re.Match) -> str:
        field = match.group(1)
        return _MESSAGE_LABELS.get(field) or field.replace("_", " ")

    return _METADATA_TOKEN.sub(replace_metadata, message)


def _metadata(raw: dict, project_id: str, test_row: dict, config: dict) -> dict:
    """The metadata block every engine's require_metadata() expects."""
    identity = raw.get("identity") or {}

    depth_top = test_row.get("spec_depth")
    if depth_top is None:
        depth_top = _num(identity.get("specimenDepth"))

    depth_base = test_row.get("spec_base")
    if depth_base is None:
        depth_base = _num(identity.get("specimenBase"))

    return {
        "PROJ_ID": project_id,
        "LOCA_ID": test_row.get("loca_id") or identity.get("locationId") or "",
        "SAMP_REF": test_row.get("samp_id") or identity.get("sampleId") or "",
        "SPEC_REF": test_row.get("spec_ref") or identity.get("specimenReference") or "",
        "SAMP_TOP": depth_top,
        "SAMP_BASE": depth_base,
        "TEST_DATE": identity.get("testDate") or None,
        # The lab's own controlled verification. Deliberately defaults to
        # False: the engines gate issue_eligible behind these flags and the
        # package's handover forbids defaulting them True. Flip them in the
        # method definition's validation_schema once the lab lead signs off.
        "method_verified": bool(config.get("method_verified", False)),
        "equipment_calibration_verified": bool(
            config.get("equipment_calibration_verified", False)
        ),
        # Separate gate for the hydrometer instrument (grain-size engine
        # checks it only when hydrometer readings are present). Same rule:
        # the lab lead flips it in validation_schema after sign-off.
        "hydrometer_calibration_verified": bool(
            config.get("hydrometer_calibration_verified", False)
        ),
        "remarks": raw.get("remarks") or None,
        # Natural water content is optional; when present the Atterberg
        # engine additionally reports liquidity and consistency indices.
        # Read from the identity block the Results Entry form builds (the
        # field lives next to testDate there).
        **(
            {"natural_water_content_pct": natural_w}
            if (natural_w := _num(identity.get("naturalWaterContent"))) is not None
            else {}
        ),
    }


# ============================================================ DIRECTION 1

def engine_input(
    test_type: str,
    raw: dict,
    *,
    project_id: str,
    test_row: dict,
    method_config: dict,
) -> dict:
    """Build the engine's test record from the app's raw snapshot."""
    if test_type not in _PROCESSORS:
        raise InputError(f"No server calculation engine for test type {test_type}.")

    data = raw.get("data") or {}
    rows = data.get("rows") or []

    metadata = _metadata(raw, project_id, test_row, method_config)
    profile = method_config.get("standard_profile") or FALLBACK_PROFILE.get(test_type)
    if not profile:
        raise InputError(f"The pinned method has no standard profile for {test_type}.")
    profile = str(profile)

    if test_type == "ATTERBERG":
        return _atterberg_input(data, metadata, profile, method_config)

    if test_type == "PARTICLE_DENSITY":
        return _particle_density_input(data, metadata, profile, method_config)

    return _psd_input(data, metadata, profile, method_config)


def _psd_input(data: dict, metadata: dict, profile: str, config: dict) -> dict:
    params = data.get("params") or {}
    rows = data.get("rows") or []

    sieve_rows: list[dict] = []
    for row in rows:
        if _blank(row, ("size", "tareRet")):
            continue
        opening = _num(row.get("size"))
        tare = _num(row.get("tare")) or 0.0
        tare_ret = _num(row.get("tareRet"))
        if opening is None or tare_ret is None:
            # Partially entered row: pass it through so the engine states
            # exactly which reading is incomplete.
            sieve_rows.append({
                "GRAT_SIZE": row.get("size"),
                "TDAC_RETAINED_G": row.get("tareRet"),
            })
            continue
        sieve_rows.append({
            "GRAT_SIZE": opening,
            "TDAC_RETAINED_G": tare_ret - tare,
        })

    # The UI is a grid; the engine demands a strictly decreasing sieve stack.
    # Sorting is order-independent for the physics (cumulative retained is a
    # sum) and makes an unsorted grid calculate instead of erroring.
    sieve_rows.sort(key=lambda r: -(_num(r.get("GRAT_SIZE")) or 0.0))

    pretreatment = str(params.get("pretreatment") or "").lower()
    if "wet" in pretreatment:
        sieve_method = "wet_sieving"
    elif "dry" in pretreatment:
        sieve_method = "dry_sieving"
    else:
        sieve_method = str(config.get("sieve_method_default") or "unconfirmed")

    record = {
        "standard_profile": profile,
        "sieve_method": sieve_method,
        "metadata": metadata,
        "sieve": {
            "TDAC_DRY_MASS_G": _num(params.get("dryMass")),
            "TDAC_PAN_MASS_G": _num(params.get("panMass")) or 0.0,
            "TDAC_WASH_LOSS_G": _num(params.get("washLoss")) or 0.0,
            "TDAC_MASS_TOLERANCE_PCT": (
                _num(params.get("massTolerance"))
                if _num(params.get("massTolerance")) is not None
                else config.get("mass_tolerance_pct", 0.5)
            ),
            "TDAC_SIEVE_ROWS": sieve_rows,
        },
    }

    # The hydrometer block is optional and the UI does not capture it yet.
    # When a future sub-tab stores an engine-shaped block, it passes through.
    hydro = data.get("hydrometer")
    if isinstance(hydro, dict) and hydro.get("TDAC_READINGS"):
        record["hydrometer"] = hydro

    return record


def _particle_density_input(data: dict, metadata: dict, profile: str, config: dict) -> dict:
    rows = _used(data.get("rows") or [])

    trials: list[dict] = []
    for row in rows:
        if _blank(row, ("m1", "m2", "m3", "m4", "temp")):
            continue
        temp = _num(row.get("temp"))
        fluid_density = _num(row.get("fluidDensity"))
        if fluid_density is None and temp is not None:
            fluid_density = _rho_water_kell(temp)
        reference = _num(row.get("referenceWaterDensity"))
        if reference is None and temp is not None:
            reference = _rho_water_kell(temp)
        trials.append({
            "TDAC_M1_EMPTY_PYCNOMETER_G": _num(row.get("m1")),
            "TDAC_M2_PYC_DRY_SOIL_G": _num(row.get("m2")),
            "TDAC_M3_PYC_SOIL_FLUID_G": _num(row.get("m3")),
            "TDAC_M4_PYC_FLUID_G": _num(row.get("m4")),
            "TDAC_TEMPERATURE_C": temp,
            "TDAC_FLUID_DENSITY_KG_M3": fluid_density,
            "TDAC_REFERENCE_WATER_DENSITY_KG_M3": reference,
        })

    return {
        "standard_profile": profile,
        "method": str(config.get("method") or "fluid_pycnometer"),
        "metadata": metadata,
        "TDAC_REPLICATE_TOLERANCE": config.get("replicate_tolerance", 0.03),
        "TDAC_TOLERANCE_BASIS": config.get("tolerance_basis", "specific_gravity"),
        "trials": trials,
    }


def _atterberg_input(data: dict, metadata: dict, profile: str, config: dict) -> dict:
    liquid_rows = _used(data.get("rows") or [])
    plastic_rows = data.get("rows2") or []

    ll_trials: list[dict] = []
    for row in liquid_rows:
        if _blank(row, ("blows", "containerMass", "wetContainer", "dryContainer")):
            continue
        ll_trials.append({
            "TDAC_BLOW_COUNT": _num(row.get("blows")),
            "TDAC_CONTAINER_G": _num(row.get("containerMass")),
            "TDAC_CONTAINER_WET_G": _num(row.get("wetContainer")),
            "TDAC_CONTAINER_DRY_G": _num(row.get("dryContainer")),
        })

    pl_trials: list[dict] = []
    for row in plastic_rows:
        if _blank(row, ("containerMass", "wetContainer", "dryContainer")):
            continue
        pl_trials.append({
            "TDAC_CONTAINER_G": _num(row.get("containerMass")),
            "TDAC_CONTAINER_WET_G": _num(row.get("wetContainer")),
            "TDAC_CONTAINER_DRY_G": _num(row.get("dryContainer")),
        })

    method = str(config.get("liquid_limit_method") or "casagrande")
    liquid_limit: dict[str, Any] = {"TDAC_LL_TRIALS": ll_trials}
    if method == "fall_cone":
        liquid_limit.update({
            "TDAC_REFERENCE_PENETRATION_MM": config.get("reference_penetration_mm", 20.0),
            "TDAC_CONE_MASS_G": config.get("cone_mass_g", 80.0),
            "TDAC_CONE_ANGLE_DEG": config.get("cone_angle_deg", 30.0),
        })

    return {
        "standard_profile": profile,
        "liquid_limit_method": method,
        "metadata": metadata,
        "TDAC_LL_R2_MIN": config.get("ll_r2_min", 0.95),
        "liquid_limit": liquid_limit,
        "plastic_limit": {
            "TDAC_NON_PLASTIC": bool(data.get("nonPlastic", False)),
            "TDAC_PL_RANGE_TOLERANCE_PCT": config.get("pl_range_tolerance_pct", 1.0),
            "TDAC_PL_TRIALS": pl_trials,
        },
    }


# ============================================================ RUNNER

def run_engine(test_type: str, engine_record: dict) -> dict:
    """Run the engine for this test type. InputError passes through with its
    message humanized for the Results Entry form."""
    try:
        return _PROCESSORS[test_type](engine_record)
    except InputError:
        raise
    except ValueError as exc:  # engine validation surfaces as ValueError
        raise InputError(str(exc)) from exc


# ============================================================ DIRECTION 2

def _fmt(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "ND"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:,.{decimals}f}"
    return str(value)


def engine_output(test_type: str, result: dict) -> dict:
    """Engine result -> the snapshot shape Results Entry, QA, Historic Data
    and the AGS Mapping tab all read.

    outputs holds ONLY the numeric released keys the method declares; the
    publish step refuses to release anything not in result_schema, so this
    is the contract the migration pins.
    """
    if test_type == "ATTERBERG":
        return _atterberg_output(result)
    if test_type == "PARTICLE_DENSITY":
        return _pd_output(result)
    return _psd_output(result)


def _meta(result: dict) -> dict:
    return {
        "report_status": result.get("report_status"),
        "issue_eligible": bool(result.get("issue_eligible", False)),
        "standard": result.get("standard"),
        "standard_profile": result.get("standard_profile"),
        "engine_version": result.get("engine_version"),
        "test_type": result.get("test_type"),
    }


def _psd_output(result: dict) -> dict:
    sieve = result.get("sieve") or {}
    fractions = result.get("fractions_profile") or {}
    d_values = result.get("d_values") or {}

    outputs = {
        "gravel_pct": fractions.get("gravel_pct"),
        "sand_pct": fractions.get("sand_pct"),
        "fines_pct": fractions.get("fines_pct"),
        "silt_pct": fractions.get("silt_pct"),
        "clay_pct": fractions.get("clay_pct"),
        "d10_mm": d_values.get("D10_mm"),
        "d30_mm": d_values.get("D30_mm"),
        "d60_mm": d_values.get("D60_mm"),
        "cu": result.get("Cu"),
        "cc": result.get("Cc"),
    }
    outputs = {k: v for k, v in outputs.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}

    results = [
        {"label": "Gravel", "value": _fmt(fractions.get("gravel_pct"), 1), "unit": "%"},
        {"label": "Sand", "value": _fmt(fractions.get("sand_pct"), 1), "unit": "%"},
        {"label": "Fines", "value": _fmt(fractions.get("fines_pct"), 1), "unit": "%"},
        {"label": "Silt", "value": _fmt(fractions.get("silt_pct"), 1), "unit": "%"},
        {"label": "Clay", "value": _fmt(fractions.get("clay_pct"), 1), "unit": "%"},
        {"label": "D10", "value": _fmt(d_values.get("D10_mm"), 4), "unit": "mm"},
        {"label": "D30", "value": _fmt(d_values.get("D30_mm"), 4), "unit": "mm"},
        {"label": "D60", "value": _fmt(d_values.get("D60_mm"), 4), "unit": "mm"},
        {"label": "Cu", "value": _fmt(result.get("Cu"), 2)},
        {"label": "Cc", "value": _fmt(result.get("Cc"), 2)},
        {
            "label": "Mass balance",
            "value": (
                f"{_fmt(sieve.get('mass_difference_g'), 3)} g "
                f"({_fmt(sieve.get('mass_difference_pct'), 2)}% of dry mass, "
                f"tolerance {_fmt(sieve.get('mass_tolerance_pct'), 2)}%)"
            ),
        },
    ]

    return {
        "outputs": outputs,
        "results": results,
        "curve": result.get("curve_points"),
        "perRow": (sieve.get("rows") or []) and [
            {
                "size_mm": row.get("size_mm"),
                "retained_g": row.get("retained_g"),
                "passing_pct": row.get("passing_pct"),
                "source": row.get("source"),
            }
            for row in sieve["rows"]
        ] or None,
        "hydrometer": result.get("hydrometer"),
        "ags": result.get("ags_candidate"),
        "meta": _meta(result),
    }


def _pd_output(result: dict) -> dict:
    outputs = {
        "specific_gravity": result.get("specific_gravity"),
        "particle_density": result.get("particle_density_kg_m3"),
    }
    outputs = {k: v for k, v in outputs.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}

    results = [
        {"label": "Mean Gs", "value": _fmt(result.get("specific_gravity"), 3)},
        {"label": "Particle density", "value": _fmt(result.get("particle_density_kg_m3"), 1), "unit": "kg/m3"},
        {"label": "Gs range", "value": _fmt(result.get("specific_gravity_range"), 4)},
        {"label": "Replicate tolerance", "value": _fmt(result.get("replicate_tolerance"), 3)},
        {"label": "Replicate QA", "value": "Pass" if result.get("replicate_pass") else "Review"},
        {"label": "Method", "value": str(result.get("method") or "").replace("_", " ")},
        {"label": "Determinations", "value": str(len(result.get("trials") or []))},
    ]

    return {
        "outputs": outputs,
        "results": results,
        "perRow": result.get("trials"),
        "ags": result.get("ags_candidate"),
        "meta": _meta(result),
    }


def _atterberg_output(result: dict) -> dict:
    non_plastic = result.get("plasticity_category") == "NP"
    liquid = result.get("liquid_limit") or {}
    plastic = result.get("plastic_limit") or {}
    regression = liquid.get("regression") or {}

    outputs = {
        "liquid_limit": result.get("LL_pct"),
        "plastic_limit": None if non_plastic else result.get("PL_pct"),
        "plasticity_index": None if non_plastic else result.get("PI_pct"),
        "flow_index": result.get("flow_index"),
    }
    outputs = {k: v for k, v in outputs.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}

    results = [
        {"label": "Liquid limit", "value": _fmt(result.get("LL_pct"), 1), "unit": "%"},
        {
            "label": "Plastic limit",
            "value": "NP" if non_plastic else _fmt(result.get("PL_pct"), 1),
            "unit": "" if non_plastic else "%",
        },
        {
            "label": "Plasticity index",
            "value": "NP" if non_plastic else _fmt(result.get("PI_pct"), 1),
            "unit": "" if non_plastic else "%",
        },
        {"label": "Flow index", "value": _fmt(result.get("flow_index"), 2)},
        {"label": "Regression R2", "value": _fmt(regression.get("r_squared"), 4)},
        {
            "label": "Reference bracketed",
            "value": "Yes" if liquid.get("reference_bracketed") else "No (extrapolated)",
        },
        {"label": "Method", "value": str(result.get("liquid_limit_method") or "").replace("_", " ")},
    ]
    if result.get("toughness_index") is not None:
        results.append({"label": "Toughness index", "value": _fmt(result.get("toughness_index"), 2)})
    if result.get("liquidity_index") is not None:
        results.append({"label": "Liquidity index", "value": _fmt(result.get("liquidity_index"), 2)})
    if result.get("consistency_index") is not None:
        results.append({"label": "Consistency index", "value": _fmt(result.get("consistency_index"), 2)})

    return {
        "outputs": outputs,
        "results": results,
        "curve": [
            {"x": trial.get("control_value"), "y": trial.get("water_content_pct")}
            for trial in liquid.get("trials") or []
        ],
        "perRow": (liquid.get("trials") or []) and [
            {
                "trial": trial.get("trial"),
                "control_value": trial.get("control_value"),
                "water_content_pct": trial.get("water_content_pct"),
                "fitted_water_content_pct": trial.get("fitted_water_content_pct"),
                "residual_pct": trial.get("residual_pct"),
            }
            for trial in liquid["trials"]
        ] or None,
        "plastic_limit": plastic or None,
        "ags": result.get("ags_candidate"),
        "meta": _meta(result),
    }


# ============================================================ SNAPSHOT BUILDER

def build_snapshots(test_type: str, result: dict) -> tuple[dict, dict]:
    """Engine result -> (calculation_output_snapshot, validation_snapshot).

    The validation snapshot feeds lab.validation_issue through the existing
    save path: engine warnings become WARNING rows (never blockers -- the
    engines already refuse to *calculate* anything they consider invalid, so
    what survives to a warning is advisory by definition).
    """
    mapped = engine_output(test_type, result)
    warnings = [humanize_message(w) for w in result.get("warnings", [])]

    calculation_snapshot = {
        "outputs": mapped["outputs"],
        "results": mapped["results"],
        "curve": mapped.get("curve"),
        "perRow": mapped.get("perRow"),
        "ags": mapped.get("ags"),
        "meta": mapped.get("meta"),
        "engine": "tdac_lab_engine",
    }
    if test_type == "PSD" and mapped.get("hydrometer"):
        calculation_snapshot["hydrometer"] = mapped["hydrometer"]
    if test_type == "ATTERBERG" and mapped.get("plastic_limit"):
        calculation_snapshot["plastic_limit"] = mapped["plastic_limit"]

    validation_snapshot = {
        "issues": [{"level": "warning", "message": message} for message in warnings],
        "errors": 0,
        "warnings": len(warnings),
        "engine": "tdac_lab_engine",
        "issue_eligible": bool(result.get("issue_eligible", False)),
        "standard": result.get("standard"),
    }

    return calculation_snapshot, validation_snapshot
