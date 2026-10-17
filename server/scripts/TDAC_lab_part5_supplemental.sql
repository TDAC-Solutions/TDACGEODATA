-- ============================================================================
-- TDAC Lab Data - PART 5 (supplemental field groundwater + lab trial/stage)
-- Single-file, idempotent. Creates NO new tables, deletes NOTHING.
-- Run against ags42_data. Safe to re-run (ON CONFLICT / WHERE NOT EXISTS).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. Ensure the consolidation test (sample -7) has a revision row first.
--    The trial/stage tables FK to lab.test_revision on (test_id, revision_no),
--    so a test without any revision cannot have trials inserted against it.
--    test_revision is keyed on (test_id, revision_no) - guarded idempotently.
--    Mirrors the revision insert shape used in PART 4.
-- ----------------------------------------------------------------------------
INSERT INTO lab.test_revision (
    test_id, revision_no, raw_input_snapshot,
    calculation_package, calculation_package_version,
    method_definition_id, revision_reason, status,
    immutable, created_at, created_by
)
SELECT t.test_id, 1,
       '{"consolidation_stages":[],"readings":{}}'::jsonb,
       'consolidation', '1',
       t.method_definition_id,
       'Initial revision (part 5 supplemental seed)',
       'CALCULATED',
       false, now(), 'seed'
FROM lab.test t
WHERE t.samp_id = 'TDAC-2026-09-901-7'
  AND t.test_type = 'CONSOLIDATION'
  AND NOT EXISTS (
    SELECT 1 FROM lab.test_revision r
    WHERE r.test_id = t.test_id AND r.revision_no = 1
  );

-- ----------------------------------------------------------------------------
-- 1. Groundwater - written to the EXISTING standard AGS water-strike table
--    ags42."WSTG" (NOT a new table). uq_wstg_identity is the uniqueness guard.
--    Idempotent via WHERE NOT EXISTS on the identity.
-- ----------------------------------------------------------------------------
INSERT INTO "ags42"."WSTG" ("PROJ_ID", "LOCA_ID", "WSTG_DPTH", "WSTG_DTIM", "WSTG_REM")
VALUES
    ('TDAC-2026-09-901', 'BH-1', 0.20, '2026-08-17 09:30:00+00', 'Groundwater struck at 0.20m bgl during boring'),
    ('TDAC-2026-09-901', 'BH-2', 0.25, '2026-08-18 10:15:00+00', 'Groundwater struck at 0.25m bgl during boring'),
    ('TDAC-2026-09-901', 'BH-3', 0.30, '2026-08-20 11:00:00+00', 'Groundwater struck at 0.30m bgl during boring')
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- 2. Atterberg liquid trials - COMPLETE all NOT NULL columns
--    (test_id, revision_no, trial_no, method_type, the three masses,
--     water_content_percent, accepted)
-- ----------------------------------------------------------------------------
INSERT INTO lab.atterberg_liquid_trial (
    test_id, revision_no, trial_no, method_type, blows, container_id,
    mass_container_g, mass_container_wet_soil_g, mass_container_dry_soil_g,
    water_content_percent, accepted
)
SELECT t.test_id, 1, trial.no, 'CASAGRANDE', trial.blows, trial.cid,
       trial.m_c, trial.m_cw, trial.m_cd, trial.wc, true
FROM lab.test t
JOIN (VALUES
    (1, 18, 'C-01', 10.20, 27.31, 22.01, 52.1),
    (2, 24, 'C-02', 10.15, 26.85, 21.80, 51.9),
    (3, 31, 'C-03', 10.50, 25.90, 21.20, 51.4)
) AS trial(no, blows, cid, m_c, m_cw, m_cd, wc) ON true
WHERE t.samp_id = 'TDAC-2026-09-901-1'
  AND t.test_type = 'ATTERBERG'
ON CONFLICT DO NOTHING;

-- Atterberg plastic trials - COMPLETE all NOT NULL columns incl. non_plastic
INSERT INTO lab.atterberg_plastic_trial (
    test_id, revision_no, trial_no, container_id,
    mass_container_g, mass_container_wet_soil_g, mass_container_dry_soil_g,
    water_content_percent, non_plastic, accepted
)
SELECT t.test_id, 1, trial.no, trial.cid,
       trial.m_c, trial.m_cw, trial.m_cd, trial.wc, false, true
FROM lab.test t
JOIN (VALUES
    (1, 'P-01', 9.80, 18.50, 16.82, 23.9),
    (2, 'P-02', 9.95, 18.90, 17.20, 24.1)
) AS trial(no, cid, m_c, m_cw, m_cd, wc) ON true
WHERE t.samp_id = 'TDAC-2026-09-901-1'
  AND t.test_type = 'ATTERBERG'
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- 3. PSD sieve readings - COMPLETE all NOT NULL columns
--    (test_id, revision_no, reading_no, fraction, sieve_opening_mm,
--     retained_mass_g, percent_retained, percent_passing)
-- ----------------------------------------------------------------------------
INSERT INTO lab.psd_sieve_reading (
    test_id, revision_no, reading_no, fraction, sieve_opening_mm,
    retained_mass_g, percent_retained, percent_passing
)
SELECT t.test_id, 1, s.reading_no, 'COMBINED', s.sieve_mm,
       s.retained_g, s.pct_ret, s.pct_pass
FROM lab.test t
JOIN (VALUES
    (1, 20.0,    0.0,   0.0, 100.0),
    (2, 10.0,   12.5,   2.5,  97.5),
    (3,  4.75,  25.0,   5.0,  92.5),
    (4,  2.0,   37.5,   7.5,  85.0),
    (5,  0.425, 125.0, 25.0,  60.0),
    (6,  0.075, 150.0, 30.0,  30.0)
) AS s(reading_no, sieve_mm, retained_g, pct_ret, pct_pass) ON true
WHERE t.samp_id = 'TDAC-2026-09-901-1'
  AND t.spec_ref = 'SP-02'
  AND t.test_type = 'PSD'
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- 4. Triaxial UU specimen - COMPLETE all NOT NULL columns incl. accepted
-- ----------------------------------------------------------------------------
INSERT INTO lab.triaxial_uu_specimen (
    test_id, revision_no, specimen_no, ags_test_stage_ref, diameter_mm,
    initial_length_mm, cell_pressure_kpa,
    corrected_deviator_stress_failure_kpa, undrained_shear_strength_kpa,
    failure_mode, accepted
)
SELECT t.test_id, 1, 1, 'STAGE-1', 38.0, 76.0, 100.0, 96.0, 48.0,
       'Plastic Failure', true
FROM lab.test t
WHERE t.samp_id = 'TDAC-2026-09-901-3'
  AND t.test_type = 'TRIAXIAL_UU'
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- 5. Consolidation stages - COMPLETE all NOT NULL columns incl. accepted
--    (the revision row is guaranteed by step 0 above)
-- ----------------------------------------------------------------------------
INSERT INTO lab.consolidation_stage (
    test_id, revision_no, stage_no, ags_increment_ref, loading_direction,
    stress_start_kpa, stress_end_kpa, void_ratio_start, void_ratio_end,
    mv_m2_mn, accepted
)
SELECT t.test_id, 1, s.stage_no, s.inc_ref, s.dir,
       s.s_start, s.s_end, s.e_start, s.e_end, s.mv, true
FROM lab.test t
JOIN (VALUES
    (1, 'INC-1', 'LOAD',   0.0,  25.0, 0.950, 0.920, 0.24),
    (2, 'INC-2', 'LOAD',  25.0,  50.0, 0.920, 0.880, 0.21),
    (3, 'INC-3', 'LOAD',  50.0, 100.0, 0.880, 0.820, 0.18),
    (4, 'INC-4', 'LOAD', 100.0, 200.0, 0.820, 0.740, 0.15)
) AS s(stage_no, inc_ref, dir, s_start, s_end, e_start, e_end, mv) ON true
WHERE t.samp_id = 'TDAC-2026-09-901-7'
  AND t.test_type = 'CONSOLIDATION'
ON CONFLICT DO NOTHING;
