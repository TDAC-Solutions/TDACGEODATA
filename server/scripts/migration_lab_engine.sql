-- Lab engine configuration migration (data only; no DDL, no new tables).
--
-- What this does:
--   1. Pins each engine-backed method's calculation profile + QA tolerances in
--      lab.method_definition.validation_schema (JSONB), which the server
--      engine reads at calculate/save time. Nothing is hardcoded in Python:
--      the lab edits these values to match its controlled QA method.
--   2. Fixes a pre-existing seed bug: PSD's result_schema declared
--      percent_passing / percent_retained, which no calculation ever
--      produced, so PSD could never pass the release gate ("no released
--      value"). The engine-backed outputs are the fraction/D-value keys.
--   3. Fixes the matching ATTERBERG gap: plastic_limit was missing from its
--      declared outputs.
--
-- Idempotent: jsonb_build_object replaces the whole document, so re-running
-- yields the same rows.
--
-- NOTE on method_verified / equipment_calibration_verified:
--   They are deliberately NOT set here. The engines gate issue_eligible
--   behind those flags, and the package's handover requires the laboratory
--   to verify the procedure against its controlled copy of the standard.
--   The lab lead flips them to true in this schema after sign-off; until
--   then every engine result is DRAFT / FOR REVIEW, which is correct.
--
--   For PSD with hydrometer readings the engine additionally gates on
--   'hydrometer_calibration_verified'. Same rule: set it to true here once
--   the hydrometer instrument's calibration is verified; without it a
--   hydrometer-backed PSD stays issue-ineligible even when the other two
--   flags are true.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Engine configuration per method (validation_schema)
-- ---------------------------------------------------------------------------

UPDATE lab.method_definition SET validation_schema = jsonb_build_object(
    'standard_profile', 'IS_2720_4_1985',
    'sieve_method_default', 'wet_sieving',
    'mass_tolerance_pct', 0.5,
    'checks', jsonb_build_array('percent_bounds', 'mass_balance')
)
WHERE test_type = 'PSD' AND method_code = 'PSD' AND method_version = 1;

UPDATE lab.method_definition SET validation_schema = jsonb_build_object(
    'standard_profile', 'IS_2720_3_SEC1_1980',
    'method', 'fluid_pycnometer',
    'replicate_tolerance', 0.03,
    'tolerance_basis', 'specific_gravity',
    'checks', jsonb_build_array('gs_range', 'repeatability')
)
WHERE test_type = 'PARTICLE_DENSITY' AND method_code = 'PARTICLE_DENSITY' AND method_version = 1;

UPDATE lab.method_definition SET validation_schema = jsonb_build_object(
    'standard_profile', 'IS_2720_5_1985',
    'liquid_limit_method', 'casagrande',
    'll_r2_min', 0.95,
    'pl_range_tolerance_pct', 1.0,
    'checks', jsonb_build_array('flow_curve_fit', 'pi_non_negative')
)
WHERE test_type = 'ATTERBERG' AND method_code = 'ATTERBERG' AND method_version = 1;

-- ---------------------------------------------------------------------------
-- 2. Released output keys the engines actually produce (result_schema)
--
--    These must match app/lab_engine/adapters.DECLARED_OUTPUTS exactly:
--    the publish step releases ONLY keys declared here, and the engine
--    writes ONLY keys declared there. A mismatch means a value the engine
--    produced can never be released.
--
--    The WHERE clauses mirror section 1 exactly (test_type + method_code +
--    version) so a future method variant at the same version can never be
--    updated by one statement and skipped by the other.
-- ---------------------------------------------------------------------------

UPDATE lab.method_definition SET result_schema = jsonb_build_object(
    'outputs', jsonb_build_array(
        'gravel_pct', 'sand_pct', 'fines_pct', 'silt_pct', 'clay_pct',
        'd10_mm', 'd30_mm', 'd60_mm', 'cu', 'cc'
    )
)
WHERE test_type = 'PSD' AND method_code = 'PSD' AND method_version = 1;

UPDATE lab.method_definition SET result_schema = jsonb_build_object(
    'outputs', jsonb_build_array('specific_gravity', 'particle_density')
)
WHERE test_type = 'PARTICLE_DENSITY' AND method_code = 'PARTICLE_DENSITY' AND method_version = 1;

UPDATE lab.method_definition SET result_schema = jsonb_build_object(
    'outputs', jsonb_build_array(
        'liquid_limit', 'plastic_limit', 'plasticity_index', 'flow_index'
    )
)
WHERE test_type = 'ATTERBERG' AND method_code = 'ATTERBERG' AND method_version = 1;

COMMIT;
