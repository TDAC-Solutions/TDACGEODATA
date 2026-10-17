-- TDAC LABORATORY MODULE - complete demo seed (single file)
-- 1) lab schema DDL, 2) seed_lab_methods, 3) demo_full_chain (project..tests), 4) demo_workflow (approved/submitted + field data + metadata)
-- Target: ags42_data. Idempotent. Applied 2026-09-20.

/* ============ PART 1 - lab schema DDL ============ */
-- TDAC Laboratory Module - corrected companion schema for AGS 4.2
-- Version 1.0 | corrected for current TDAC AGS schema
--
-- Corrections made:
--   1. Removed FK references to ags42."FILE"("FILE_FSET") because FILE_FSET
--      is not declared UNIQUE/PRIMARY KEY in the current AGS schema.
--      The file_fset columns are retained as plain text.
--   2. Removed the composite FK from lab.test to
--      ags42."SAMP"("LOCA_ID","SAMP_ID") because that pair is not declared
--      UNIQUE/PRIMARY KEY in the current AGS schema.
--      The loca_id and samp_id columns are retained and sample existence
--      must be validated by the API/service layer.
--
-- Do not modify ags42."FILE" or ags42."SAMP" with this script.

CREATE SCHEMA IF NOT EXISTS lab;

CREATE TABLE IF NOT EXISTS lab.method_definition (
    method_definition_id uuid PRIMARY KEY,
    method_code text NOT NULL,
    method_version integer NOT NULL,
    test_type text NOT NULL CHECK (test_type IN (
        'PSD','PARTICLE_DENSITY','ATTERBERG','SHRINKAGE_LIMIT',
        'TRIAXIAL_UU','CONSOLIDATION'
    )),
    method_name text NOT NULL,
    standard_body text,
    standard_reference text,
    standard_edition text,
    calculation_package text NOT NULL,
    calculation_package_version text NOT NULL,
    input_schema jsonb NOT NULL,
    validation_schema jsonb NOT NULL,
    result_schema jsonb NOT NULL,
    ags_mapping_profile jsonb NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NOT NULL,
    UNIQUE (method_code, method_version)
);

CREATE TABLE IF NOT EXISTS lab.equipment (
    equipment_id uuid PRIMARY KEY,
    equipment_code text NOT NULL UNIQUE,
    equipment_type text NOT NULL,
    manufacturer text,
    model text,
    serial_number text,
    laboratory text,
    status text NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE','OUT_OF_SERVICE','RETIRED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NOT NULL
);

CREATE TABLE IF NOT EXISTS lab.equipment_calibration (
    calibration_id uuid PRIMARY KEY,
    equipment_id uuid NOT NULL REFERENCES lab.equipment(equipment_id),
    certificate_number text NOT NULL,
    calibrated_at timestamptz NOT NULL,
    valid_until timestamptz NOT NULL,
    calibration_provider text,
    certificate_file_fset text,
    status text NOT NULL DEFAULT 'VALID'
        CHECK (status IN ('VALID','EXPIRED','REVOKED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NOT NULL,
    CHECK (valid_until >= calibrated_at)
);

CREATE TABLE IF NOT EXISTS lab.test (
    test_id uuid PRIMARY KEY,
    file_fset text NOT NULL,
    loca_id text NOT NULL,
    samp_id text NOT NULL,
    samp_top numeric,
    samp_ref text,
    samp_type text,
    spec_ref text NOT NULL,
    spec_depth numeric,
    spec_base numeric,
    spec_desc text,
    spec_prep text,
    test_type text NOT NULL CHECK (test_type IN (
        'PSD','PARTICLE_DENSITY','ATTERBERG','SHRINKAGE_LIMIT',
        'TRIAXIAL_UU','CONSOLIDATION'
    )),
    method_definition_id uuid NOT NULL
        REFERENCES lab.method_definition(method_definition_id),
    laboratory text NOT NULL,
    technician text,
    test_started_at timestamptz,
    test_completed_at timestamptz,
    source_type text NOT NULL DEFAULT 'MANUAL'
        CHECK (source_type IN ('MANUAL','INSTRUMENT','AGS','XLSX_CSV','API','MIGRATION')),
    source_reference text,
    status text NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN (
            'DRAFT','CALCULATED','SUBMITTED','RETURNED','CHECKED',
            'APPROVED','PUBLISHED','SUPERSEDED','VOID'
        )),
    current_revision integer NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    row_version integer NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL,
    CHECK (spec_base IS NULL OR spec_depth IS NULL OR spec_base >= spec_depth),
    CHECK (test_completed_at IS NULL OR test_started_at IS NULL OR test_completed_at >= test_started_at),
    UNIQUE (file_fset, loca_id, samp_id, spec_ref, test_type, current_revision)
);

CREATE INDEX IF NOT EXISTS ix_lab_test_project_status
    ON lab.test (file_fset, status, test_type);

CREATE INDEX IF NOT EXISTS ix_lab_test_sample
    ON lab.test (file_fset, loca_id, samp_id, spec_ref);

CREATE INDEX IF NOT EXISTS ix_lab_test_depth
    ON lab.test (file_fset, loca_id, spec_depth);

CREATE TABLE IF NOT EXISTS lab.test_revision (
    test_id uuid NOT NULL REFERENCES lab.test(test_id),
    revision_no integer NOT NULL CHECK (revision_no >= 1),
    raw_input_snapshot jsonb NOT NULL,
    calculation_output_snapshot jsonb,
    validation_snapshot jsonb,
    calculation_package text NOT NULL,
    calculation_package_version text NOT NULL,
    method_definition_id uuid NOT NULL
        REFERENCES lab.method_definition(method_definition_id),
    revision_reason text,
    status text NOT NULL,
    immutable boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NOT NULL,
    PRIMARY KEY (test_id, revision_no)
);

CREATE TABLE IF NOT EXISTS lab.test_equipment (
    test_id uuid NOT NULL REFERENCES lab.test(test_id),
    equipment_id uuid NOT NULL REFERENCES lab.equipment(equipment_id),
    calibration_id uuid REFERENCES lab.equipment_calibration(calibration_id),
    role text NOT NULL,
    PRIMARY KEY (test_id, equipment_id, role)
);

CREATE TABLE IF NOT EXISTS lab.psd_sieve_reading (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    reading_no integer NOT NULL,
    fraction text NOT NULL CHECK (fraction IN ('COARSE','FINE','COMBINED')),
    sieve_opening_mm numeric NOT NULL CHECK (sieve_opening_mm > 0),
    tare_mass_g numeric,
    tare_plus_retained_g numeric,
    retained_mass_g numeric NOT NULL CHECK (retained_mass_g >= 0),
    cumulative_retained_g numeric,
    percent_retained numeric,
    percent_passing numeric,
    ags_grat_type text,
    remarks text,
    PRIMARY KEY (test_id, revision_no, reading_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no),
    CHECK (percent_retained IS NULL OR percent_retained BETWEEN 0 AND 100),
    CHECK (percent_passing IS NULL OR percent_passing BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS lab.psd_hydrometer_reading (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    reading_no integer NOT NULL,
    elapsed_seconds numeric NOT NULL CHECK (elapsed_seconds > 0),
    temperature_c numeric NOT NULL,
    observed_reading numeric NOT NULL,
    meniscus_correction numeric NOT NULL DEFAULT 0,
    blank_correction numeric NOT NULL DEFAULT 0,
    temperature_correction numeric NOT NULL DEFAULT 0,
    dispersant_correction numeric NOT NULL DEFAULT 0,
    corrected_reading numeric,
    effective_depth_mm numeric,
    particle_size_mm numeric,
    percent_finer numeric,
    remarks text,
    PRIMARY KEY (test_id, revision_no, reading_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no),
    CHECK (percent_finer IS NULL OR percent_finer BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS lab.particle_density_trial (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    trial_no integer NOT NULL,
    pycnometer_id text,
    pycnometer_volume_ml numeric,
    temperature_c numeric NOT NULL,
    mass_empty_g numeric NOT NULL,
    mass_bottle_dry_soil_g numeric NOT NULL,
    mass_bottle_soil_water_g numeric NOT NULL,
    mass_bottle_water_g numeric NOT NULL,
    temperature_correction numeric,
    specific_gravity numeric,
    particle_density_mg_m3 numeric,
    accepted boolean NOT NULL DEFAULT true,
    remarks text,
    PRIMARY KEY (test_id, revision_no, trial_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE TABLE IF NOT EXISTS lab.atterberg_liquid_trial (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    trial_no integer NOT NULL,
    method_type text NOT NULL CHECK (method_type IN ('CASAGRANDE','CONE','ONE_POINT')),
    blows integer,
    cone_penetration_mm numeric,
    container_id text,
    mass_container_g numeric NOT NULL,
    mass_container_wet_soil_g numeric NOT NULL,
    mass_container_dry_soil_g numeric NOT NULL,
    water_content_percent numeric,
    accepted boolean NOT NULL DEFAULT true,
    remarks text,
    PRIMARY KEY (test_id, revision_no, trial_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE TABLE IF NOT EXISTS lab.atterberg_plastic_trial (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    trial_no integer NOT NULL,
    container_id text,
    mass_container_g numeric NOT NULL,
    mass_container_wet_soil_g numeric NOT NULL,
    mass_container_dry_soil_g numeric NOT NULL,
    water_content_percent numeric,
    non_plastic boolean NOT NULL DEFAULT false,
    accepted boolean NOT NULL DEFAULT true,
    remarks text,
    PRIMARY KEY (test_id, revision_no, trial_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE TABLE IF NOT EXISTS lab.shrinkage_trial (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    trial_no integer NOT NULL,
    container_id text,
    initial_water_content_percent numeric,
    wet_mass_g numeric,
    dry_mass_g numeric,
    wet_volume_cm3 numeric,
    dry_volume_cm3 numeric,
    initial_density_mg_m3 numeric,
    shrinkage_limit_percent numeric,
    shrinkage_ratio numeric,
    accepted boolean NOT NULL DEFAULT true,
    remarks text,
    PRIMARY KEY (test_id, revision_no, trial_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE TABLE IF NOT EXISTS lab.triaxial_uu_specimen (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    specimen_no integer NOT NULL,
    ags_test_stage_ref text NOT NULL,
    diameter_mm numeric NOT NULL CHECK (diameter_mm > 0),
    initial_length_mm numeric NOT NULL CHECK (initial_length_mm > 0),
    initial_mass_g numeric,
    initial_water_content_percent numeric,
    final_water_content_percent numeric,
    initial_bulk_density_mg_m3 numeric,
    initial_dry_density_mg_m3 numeric,
    cell_pressure_kpa numeric NOT NULL CHECK (cell_pressure_kpa >= 0),
    strain_rate_percent_min numeric,
    failure_criterion text,
    corrected_deviator_stress_failure_kpa numeric,
    axial_strain_failure_percent numeric,
    undrained_shear_strength_kpa numeric,
    failure_mode text,
    accepted boolean NOT NULL DEFAULT true,
    remarks text,
    PRIMARY KEY (test_id, revision_no, specimen_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE TABLE IF NOT EXISTS lab.triaxial_uu_reading (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    specimen_no integer NOT NULL,
    reading_no integer NOT NULL,
    elapsed_seconds numeric,
    axial_displacement_mm numeric NOT NULL,
    axial_load_n numeric NOT NULL,
    axial_strain_percent numeric,
    corrected_area_mm2 numeric,
    deviator_stress_kpa numeric,
    remarks text,
    PRIMARY KEY (test_id, revision_no, specimen_no, reading_no),
    FOREIGN KEY (test_id, revision_no, specimen_no)
        REFERENCES lab.triaxial_uu_specimen(test_id, revision_no, specimen_no)
);

CREATE TABLE IF NOT EXISTS lab.consolidation_stage (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    stage_no integer NOT NULL,
    ags_increment_ref text NOT NULL,
    loading_direction text NOT NULL CHECK (loading_direction IN ('LOAD','UNLOAD','RELOAD')),
    stress_start_kpa numeric NOT NULL CHECK (stress_start_kpa >= 0),
    stress_end_kpa numeric NOT NULL CHECK (stress_end_kpa >= 0),
    stage_started_at timestamptz,
    stage_completed_at timestamptz,
    average_temperature_c numeric,
    void_ratio_start numeric,
    void_ratio_end numeric,
    mv_m2_mn numeric,
    secondary_compression_coefficient numeric,
    cv_root_time_m2_year numeric,
    cv_log_time_m2_year numeric,
    permeability_m_s numeric,
    accepted boolean NOT NULL DEFAULT true,
    remarks text,
    PRIMARY KEY (test_id, revision_no, stage_no),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no),
    CHECK (stage_completed_at IS NULL OR stage_started_at IS NULL OR stage_completed_at >= stage_started_at)
);

CREATE TABLE IF NOT EXISTS lab.consolidation_reading (
    test_id uuid NOT NULL,
    revision_no integer NOT NULL,
    stage_no integer NOT NULL,
    reading_no integer NOT NULL,
    elapsed_seconds numeric NOT NULL CHECK (elapsed_seconds >= 0),
    dial_reading numeric,
    displacement_mm numeric NOT NULL,
    specimen_height_mm numeric,
    axial_strain_percent numeric,
    void_ratio numeric,
    remarks text,
    PRIMARY KEY (test_id, revision_no, stage_no, reading_no),
    FOREIGN KEY (test_id, revision_no, stage_no)
        REFERENCES lab.consolidation_stage(test_id, revision_no, stage_no)
);

CREATE TABLE IF NOT EXISTS lab.validation_issue (
    validation_issue_id uuid PRIMARY KEY,
    test_id uuid NOT NULL REFERENCES lab.test(test_id),
    revision_no integer NOT NULL,
    rule_code text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('INFO','WARNING','ERROR','BLOCKER')),
    field_path text,
    message text NOT NULL,
    observed_value jsonb,
    expected_rule jsonb,
    resolved boolean NOT NULL DEFAULT false,
    resolution_reason text,
    resolved_by text,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE INDEX IF NOT EXISTS ix_lab_validation_open
    ON lab.validation_issue (test_id, revision_no, severity)
    WHERE resolved = false;

CREATE TABLE IF NOT EXISTS lab.review_event (
    review_event_id uuid PRIMARY KEY,
    test_id uuid NOT NULL REFERENCES lab.test(test_id),
    revision_no integer NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'CREATED','CALCULATED','SUBMITTED','RETURNED','CHECKED',
        'APPROVED','PUBLISHED','SUPERSEDED','VOIDED'
    )),
    from_status text,
    to_status text NOT NULL,
    actor text NOT NULL,
    actor_role text NOT NULL,
    reason text,
    event_at timestamptz NOT NULL DEFAULT now(),
    correlation_id text NOT NULL,
    signature_metadata jsonb,
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE INDEX IF NOT EXISTS ix_lab_review_event_test
    ON lab.review_event (test_id, revision_no, event_at);

CREATE TABLE IF NOT EXISTS lab.attachment_link (
    attachment_link_id uuid PRIMARY KEY,
    test_id uuid NOT NULL REFERENCES lab.test(test_id),
    revision_no integer NOT NULL,
    file_fset text NOT NULL,
    category text NOT NULL CHECK (category IN (
        'RAW_INSTRUMENT','CALIBRATION','PHOTO','WORKSHEET','RESULT_SHEET','OTHER'
    )),
    checksum_sha256 text,
    source_name text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by text NOT NULL,
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

CREATE TABLE IF NOT EXISTS lab.ags_projection (
    test_id uuid NOT NULL REFERENCES lab.test(test_id),
    revision_no integer NOT NULL,
    ags_group text NOT NULL CHECK (ags_group IN (
        'GRAG','GRAT','LPDN','LLPL','LSLT','TRIG','TRIT','CONG','CONS'
    )),
    business_key jsonb NOT NULL,
    projected_row_count integer NOT NULL CHECK (projected_row_count >= 0),
    projected_row_hash text NOT NULL,
    projection_status text NOT NULL CHECK (projection_status IN ('PENDING','PROJECTED','FAILED','SUPERSEDED')),
    projected_at timestamptz,
    projected_by text,
    error_detail jsonb,
    PRIMARY KEY (test_id, revision_no, ags_group),
    FOREIGN KEY (test_id, revision_no)
        REFERENCES lab.test_revision(test_id, revision_no)
);

-- Implementation requirements not expressible by simple DDL alone:
-- 1. Prevent UPDATE/DELETE of lab.review_event.
-- 2. Prevent modification of immutable lab.test_revision rows.
-- 3. Require zero unresolved BLOCKER/ERROR issues before CHECKED/APPROVED.
-- 4. Enforce preparer/checker separation according to organisation policy.
-- 5. Project AGS rows and lab.ags_projection in one transaction.
-- 6. Use optimistic concurrency: reject stale row_version updates.
-- 7. Before deployment, verify any future AGS foreign keys against live DDL.
-- 8. API/service must verify that (loca_id, samp_id) exists in ags42.SAMP.

/* ============ PART 2 - method definitions ============ */
-- Seed the 6 in-scope laboratory methods (spec section 21) into lab.method_definition.
-- Versioned configuration: stable code, version, standard, calculation package,
-- and schema placeholders. The input/validation/result schemas are minimal but
-- real JSONB documents - they get enriched when the calculation engine lands.
--
-- Idempotent: ON CONFLICT (method_code, method_version) does nothing.

INSERT INTO lab.method_definition (
    method_definition_id, method_code, method_version, test_type,
    method_name, standard_body, standard_reference, standard_edition,
    calculation_package, calculation_package_version,
    input_schema, validation_schema, result_schema, ags_mapping_profile,
    effective_from, active, created_at, created_by
)
VALUES
    (gen_random_uuid(), 'PSD', 1, 'PSD',
     'Grain size analysis (sieve + hydrometer)', 'BIS', 'IS 2720', 'Part 4',
     'psd_engine', '1.0.0',
     '{"rows": ["size", "tare", "tareRet", "gratType"]}'::jsonb,
     '{"checks": ["percent_bounds", "mass_balance"]}'::jsonb,
     '{"outputs": ["percent_passing", "percent_retained"]}'::jsonb,
     '{"groups": ["GRAG", "GRAT"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'PARTICLE_DENSITY', 1, 'PARTICLE_DENSITY',
     'Particle density and specific gravity (pycnometer)', 'BIS', 'IS 2720', 'Part 3',
     'particle_density_engine', '1.0.0',
     '{"rows": ["trial", "m1", "m2", "m3", "m4", "temp", "use"]}'::jsonb,
     '{"checks": ["gs_range", "repeatability"]}'::jsonb,
     '{"outputs": ["specific_gravity", "particle_density"]}'::jsonb,
     '{"groups": ["LPDN"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'ATTERBERG', 1, 'ATTERBERG',
     'Atterberg limits (liquid + plastic)', 'BIS', 'IS 2720', 'Part 5',
     'atterberg_engine', '1.0.0',
     '{"rows": ["blows", "containerMass", "wetContainer", "dryContainer", "use"], "rows2": ["containerMass", "wetContainer", "dryContainer"]}'::jsonb,
     '{"checks": ["flow_curve_fit", "pi_non_negative"]}'::jsonb,
     '{"outputs": ["liquid_limit", "plasticity_index", "flow_index"]}'::jsonb,
     '{"groups": ["LLPL"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'SHRINKAGE_LIMIT', 1, 'SHRINKAGE_LIMIT',
     'Shrinkage limit and ratio', 'BIS', 'IS 2720', 'Part 6',
     'shrinkage_engine', '1.0.0',
     '{"rows": ["trial", "wetMass", "dryMass", "wetVol", "dryVol"]}'::jsonb,
     '{"checks": ["volume_positive"]}'::jsonb,
     '{"outputs": ["shrinkage_limit", "shrinkage_ratio"]}'::jsonb,
     '{"groups": ["LSLT"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'TRIAXIAL_UU', 1, 'TRIAXIAL_UU',
     'Undrained undrained triaxial (UU)', 'BIS', 'IS 2720', 'Part 11',
     'triaxial_uu_engine', '1.0.0',
     '{"rows": ["spec", "dia", "length", "cell", "q", "strain", "mode"]}'::jsonb,
     '{"checks": ["dia_positive", "cu_half_q_uu_only"]}'::jsonb,
     '{"outputs": ["cu", "failure_mode"]}'::jsonb,
     '{"groups": ["TRIG", "TRIT"]}'::jsonb,
     '2026-01-01', true, now(), 'seed'),

    (gen_random_uuid(), 'CONSOLIDATION', 1, 'CONSOLIDATION',
     'One-dimensional consolidation (oedometer)', 'BIS', 'IS 2720', 'Part 15',
     'consolidation_engine', '1.0.0',
     '{"rows": ["stage", "direction", "stress", "eStart", "eEnd"]}'::jsonb,
     '{"checks": ["stage_order", "stress_positive"]}'::jsonb,
     '{"outputs": ["mv", "cv", "permeability"]}'::jsonb,
     '{"groups": ["CONG", "CONS"]}'::jsonb,
     '2026-01-01', true, now(), 'seed')

ON CONFLICT (method_code, method_version) DO NOTHING;

/* ============ PART 3 - demo full chain ============ */
-- TDAC demo data: full chain from project through field data to lab tests.
-- Follows the app's real ID rules: project TDAC-YYYY-MM-N, sample {project}-{N}.
-- Run order matters: PROJ -> FILE -> LOCA -> GEOL/ISPT + PROJ_METADATA -> SAMP -> lab.test.
-- Guarded with WHERE NOT EXISTS / ON CONFLICT so re-running never duplicates.
--
-- Sources: project/location/sample/lab test rows already in demo_lab_data.sql;
-- GEOL layers and ISPT records from ~/storage/downloads/Input_sheet_V8_AGS_mapped.xlsx
-- (Borelog + SPT_Data sheets); project metadata rows (report basis) seeded as
-- config for the Overview tab.

--------------------------------------------------------------------------------
-- 0. Project (carry-forward root)
--------------------------------------------------------------------------------
INSERT INTO "ags42"."PROJ" ("PROJ_ID", "PROJ_NAME", "PROJ_LOC", "PROJ_CLNT", "PROJ_ENG", "PROJ_CONT")
SELECT 'TDAC-2026-09-901', 'Champakkulam GI Investigation', 'CHAMPAKKULAM', 'Mr. BEJOY MICHLE', 'TDAC Engineering', 'TDAC Consultants'
WHERE NOT EXISTS (SELECT 1 FROM "ags42"."PROJ" WHERE "PROJ_ID" = 'TDAC-2026-09-901');

-- 0a. Project metadata (Overview tab reads tdac.PROJ_METADATA)
INSERT INTO "tdac"."PROJ_METADATA" (
    "PROJ_ID", "ROAD_REFERENCE", "CHAINAGE_TEXT", "STRUCTURE_REFERENCE",
    "SELECTED_BOREHOLES", "REPORT_TYPE", "REPORT_TITLE", "REPORT_VOLUME_TITLE",
    "DOCUMENT_REFERENCE", "REVISION", "REPORT_DATE", "ISSUE_STATUS",
    "TDAC_COMPANY_NAME", "GROUNDWATER_BASIS", "DESIGN_STANDARD_BASIS",
    "FACTOR_OF_SAFETY_BASIS", "LOAD_COMBINATION_BASIS",
    "CONSTRUCTION_VERIFICATION_REQUIREMENT", "PILE_LOAD_TEST_REQUIREMENT"
)
SELECT 'TDAC-2026-09-901', NULL, NULL, NULL,
       'BH-1, BH-2, BH-3', 'Factual', 'Geotechnical Investigation Report', NULL,
       NULL, NULL, NULL, 'For Review',
       'TDAC', '0.2 m below ground level (from ProjectInfo)', 'IS 2720 / Eurocode-7 basis',
       NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM "tdac"."PROJ_METADATA" WHERE "PROJ_ID" = 'TDAC-2026-09-901');

-- 0b. FILE row (create_lab_test reads FILE_FSET from the project)
INSERT INTO "ags42"."FILE" ("PROJ_ID", "FILE_FSET", "FILE_NAME", "FILE_TYPE")
SELECT 'TDAC-2026-09-901', 'FS-TDAC-901', 'TDAC-2026-09-901 AGS Data', 'AGS'
WHERE NOT EXISTS (SELECT 1 FROM "ags42"."FILE" WHERE "FILE_FSET" = 'FS-TDAC-901');

-- 0c. Project ID counter (so the app continues numbering AFTER the seed)
INSERT INTO "tdac"."PROJECT_ID_COUNTER" ("YEAR", "MONTH", "LAST_NUMBER")
VALUES (2026, 9, 901)
ON CONFLICT ("YEAR", "MONTH") DO NOTHING;

--------------------------------------------------------------------------------
-- 1. Locations (3 boreholes)
--------------------------------------------------------------------------------
INSERT INTO "ags42"."LOCA" ("PROJ_ID", "LOCA_ID", "LOCA_TYPE", "LOCA_STAR", "LOCA_ENDD", "LOCA_FDEP")
SELECT v.proj_id, v.loca_id, v.loca_type, v.loca_star::timestamptz, v.loca_endd::timestamptz, v.loca_fdep
FROM (VALUES
    ('TDAC-2026-09-901', 'BH-1', 'BH', '2026-08-17', '2026-08-17', 23.45),
    ('TDAC-2026-09-901', 'BH-2', 'BH', '2026-08-18', '2026-08-19', 20.00),
    ('TDAC-2026-09-901', 'BH-3', 'BH', '2026-08-20', '2026-08-21', 15.50)
) AS v(proj_id, loca_id, loca_type, loca_star, loca_endd, loca_fdep)
WHERE NOT EXISTS (
    SELECT 1 FROM "ags42"."LOCA" l
    WHERE l."PROJ_ID" = v.proj_id AND l."LOCA_ID" = v.loca_id
);

--------------------------------------------------------------------------------
-- 2. Borehole soil layers (Overview Field Data -> BoreholeModule reads GEOL)
-- Source: Borelog sheet of Input_sheet_V8 (BH-2 column). GEOL_GEOL carries
-- the S/C normalized material class.
--------------------------------------------------------------------------------
INSERT INTO "ags42"."GEOL" ("PROJ_ID", "LOCA_ID", "GEOL_TOP", "GEOL_BASE", "GEOL_DESC", "GEOL_GEOL")
SELECT v.proj_id, v.loca_id, v.geol_top, v.geol_base, v.geol_desc, v.geol_geol
FROM (VALUES
    ('TDAC-2026-09-901', 'BH-2',  0.0,  1.5, 'Filling Gravel', 'SAND'),
    ('TDAC-2026-09-901', 'BH-2',  1.5,  2.5, 'Soft Sandy CLAY with Organic Matters', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2',  2.5,  3.6, 'Very Soft Sandy CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2',  3.6,  5.8, 'Very Soft Silty CLAY with Shell Dust', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2',  5.8,  6.8, 'Very Soft Silty CLAY with Organic Matters', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2',  6.8, 11.5, 'Very Soft to Soft Silty CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2', 11.5, 14.4, 'Soft Silty CLAY with Shell Dust', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2', 14.4, 17.4, 'Soft Silty CLAY with Decayed Wood', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2', 17.4, 19.0, 'Stiff Sandy CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-2', 19.0, 23.45, 'Dense Fine SAND', 'SAND')
) AS v(proj_id, loca_id, geol_top, geol_base, geol_desc, geol_geol)
WHERE NOT EXISTS (
    SELECT 1 FROM "ags42"."GEOL" g
    WHERE g."PROJ_ID" = v.proj_id AND g."LOCA_ID" = v.loca_id
      AND g."GEOL_TOP" = v.geol_top AND g."GEOL_BASE" = v.geol_base
);

--------------------------------------------------------------------------------
-- 3. SPT records (Field Data -> SptModule reads ISPT)
-- Source: SPT_Data sheet of Input_sheet_V8 (BH-2). ISPT_INC1/2/3 = the three
-- incremental 150mm drives; ISPT_NVAL = reported N.
--------------------------------------------------------------------------------
INSERT INTO "ags42"."ISPT" ("PROJ_ID", "LOCA_ID", "ISPT_TOP", "ISPT_INC1", "ISPT_INC2", "ISPT_INC3", "ISPT_NVAL")
SELECT v.proj_id, v.loca_id, v.ispt_top, v.inc1, v.inc2, v.inc3, v.nval
FROM (VALUES
    ('TDAC-2026-09-901', 'BH-2',  1.0, 1, 1, 1, 2),
    ('TDAC-2026-09-901', 'BH-2',  2.0, 1, 1, 1, 2),
    ('TDAC-2026-09-901', 'BH-2',  3.0, 1, 1, 0, 1),
    ('TDAC-2026-09-901', 'BH-2',  4.5, 1, 0, 0, 0),
    ('TDAC-2026-09-901', 'BH-2',  6.0, 1, 0, 0, 0),
    ('TDAC-2026-09-901', 'BH-2',  7.5, 1, 0, 1, 1),
    ('TDAC-2026-09-901', 'BH-2',  9.0, 1, 1, 1, 2),
    ('TDAC-2026-09-901', 'BH-2', 10.5, 1, 1, 1, 2),
    ('TDAC-2026-09-901', 'BH-2', 12.0, 1, 2, 1, 3),
    ('TDAC-2026-09-901', 'BH-2', 13.5, 1, 1, 2, 3),
    ('TDAC-2026-09-901', 'BH-2', 15.0, 1, 2, 2, 4),
    ('TDAC-2026-09-901', 'BH-2', 18.0, 8, 6, 6, 12),
    ('TDAC-2026-09-901', 'BH-2', 20.0, 13, 24, 26, 50),
    ('TDAC-2026-09-901', 'BH-2', 23.0, 12, 19, 26, 45)
) AS v(proj_id, loca_id, ispt_top, inc1, inc2, inc3, nval)
WHERE NOT EXISTS (
    SELECT 1 FROM "ags42"."ISPT" s
    WHERE s."PROJ_ID" = v.proj_id AND s."LOCA_ID" = v.loca_id AND s."ISPT_TOP" = v.ispt_top
);

--------------------------------------------------------------------------------
-- 4. Samples (SAMP rows, different depths per borehole; SAMPLE_ID per app rule)
--------------------------------------------------------------------------------
INSERT INTO "ags42"."SAMP" ("PROJ_ID", "LOCA_ID", "SAMP_ID", "SAMP_TOP", "SAMP_BASE", "SAMP_REF", "SAMP_TYPE")
SELECT v.proj_id, v.loca_id, v.samp_id, v.samp_top, v.samp_base, v.samp_ref, v.samp_type
FROM (VALUES
    ('TDAC-2026-09-901', 'BH-1', 'TDAC-2026-09-901-1', 1.50, 2.50, 'UD', 'U'),
    ('TDAC-2026-09-901', 'BH-1', 'TDAC-2026-09-901-2', 6.80, 11.50, 'UD', 'U'),
    ('TDAC-2026-09-901', 'BH-1', 'TDAC-2026-09-901-3', 19.00, 23.45, 'UD', 'U'),
    ('TDAC-2026-09-901', 'BH-2', 'TDAC-2026-09-901-4', 2.50, 5.80, 'UD', 'U'),
    ('TDAC-2026-09-901', 'BH-2', 'TDAC-2026-09-901-5', 11.50, 17.40, 'UD', 'U'),
    ('TDAC-2026-09-901', 'BH-3', 'TDAC-2026-09-901-6', 3.60, 6.80, 'UD', 'U'),
    ('TDAC-2026-09-901', 'BH-3', 'TDAC-2026-09-901-7', 14.40, 15.50, 'UD', 'U')
) AS v(proj_id, loca_id, samp_id, samp_top, samp_base, samp_ref, samp_type)
WHERE NOT EXISTS (
    SELECT 1 FROM "ags42"."SAMP" s
    WHERE s."PROJ_ID" = v.proj_id AND s."LOCA_ID" = v.loca_id AND s."SAMP_ID" = v.samp_id
);

--------------------------------------------------------------------------------
-- 5. Lab tests: MULTIPLE per sample (different spec_ref / test_type)
-- method_definition_id resolved by SELECT from the seeded methods - never hardcoded.
--------------------------------------------------------------------------------
INSERT INTO lab.test (
    test_id, file_fset, loca_id, samp_id, spec_ref, spec_depth,
    test_type, method_definition_id, laboratory, technician, status, created_by, updated_by
)
SELECT
    gen_random_uuid(), t.file_fset, t.loca_id, t.samp_id, t.spec_ref, t.spec_depth,
    t.test_type, m.method_definition_id, t.laboratory, t.technician, 'DRAFT', 'seed', 'seed'
FROM (VALUES
    ('FS-TDAC-901','BH-1','TDAC-2026-09-901-1','SP-01',1.50,'ATTERBERG','TDAC Central Laboratory','Lab Tech A'),
    ('FS-TDAC-901','BH-1','TDAC-2026-09-901-1','SP-02',1.50,'PSD','TDAC Central Laboratory','Lab Tech A'),
    ('FS-TDAC-901','BH-1','TDAC-2026-09-901-2','SP-01',6.80,'ATTERBERG','TDAC Central Laboratory','Lab Tech B'),
    ('FS-TDAC-901','BH-1','TDAC-2026-09-901-3','SP-01',19.00,'TRIAXIAL_UU','TDAC Central Laboratory','Lab Tech A'),
    ('FS-TDAC-901','BH-2','TDAC-2026-09-901-4','SP-01',2.50,'ATTERBERG','TDAC Central Laboratory','Lab Tech B'),
    ('FS-TDAC-901','BH-2','TDAC-2026-09-901-5','SP-01',11.50,'PSD','TDAC Central Laboratory','Lab Tech A'),
    ('FS-TDAC-901','BH-3','TDAC-2026-09-901-6','SP-01',3.60,'ATTERBERG','TDAC Central Laboratory','Lab Tech C'),
    ('FS-TDAC-901','BH-3','TDAC-2026-09-901-6','SP-02',3.60,'SHRINKAGE_LIMIT','TDAC Central Laboratory','Lab Tech C'),
    ('FS-TDAC-901','BH-3','TDAC-2026-09-901-7','SP-01',14.40,'CONSOLIDATION','TDAC Central Laboratory','Lab Tech C')
) AS t(file_fset, loca_id, samp_id, spec_ref, spec_depth, test_type, laboratory, technician)
JOIN "lab"."method_definition" m ON m.test_type = t.test_type AND m.active = true
WHERE NOT EXISTS (
    SELECT 1 FROM lab.test x
    WHERE x.loca_id = t.loca_id AND x.samp_id = t.samp_id
      AND x.spec_ref = t.spec_ref AND x.test_type = t.test_type
);
/* ============ PART 4 - demo workflow ============ */
-- TDAC demo WORKFLOW data: moves seeded DRAFT tests through the lifecycle so the
-- Historic Data (status=APPROVED), QA and Approval (status=SUBMITTED) and Overview
-- tabs show real rows instead of empty states. Also fills BH-1/BH-3 field data and
-- the blank project metadata.
--
-- This is DEMO data only. Run after demo_full_chain.sql. Idempotent (guarded).

--------------------------------------------------------------------------------
-- A. Fill blank project metadata (Overview tab)
--------------------------------------------------------------------------------
UPDATE "tdac"."PROJ_METADATA" SET
    "ROAD_REFERENCE" = 'NH-66 (Kochi–Kollam corridor)',
    "CHAINAGE_TEXT"  = 'KM 45+200',
    "STRUCTURE_REFERENCE" = 'Pile cap area (admin block)',
    "REPORT_VOLUME_TITLE" = 'Volume 1 – Main Report',
    "DOCUMENT_REFERENCE" = 'TDAC-GI-901-REP-001',
    "REVISION" = 'R0',
    "REPORT_DATE" = '2026-09-20',
    "FACTOR_OF_SAFETY_BASIS" = 'Global FoS >= 1.5 (drained)',
    "LOAD_COMBINATION_BASIS" = 'ULS + SLS per load table 3.1',
    "CONSTRUCTION_VERIFICATION_REQUIREMENT" = 'Proof pile at grid D-2 required',
    "PILE_LOAD_TEST_REQUIREMENT" = '2 no. maintained-load tests to 1.5x working load'
WHERE "PROJ_ID" = 'TDAC-2026-09-901';

--------------------------------------------------------------------------------
-- B. BH-1 and BH-3 soil layers (GEOL), realistic — BH-2 already seeded
--------------------------------------------------------------------------------
INSERT INTO "ags42"."GEOL" ("PROJ_ID", "LOCA_ID", "GEOL_TOP", "GEOL_BASE", "GEOL_DESC", "GEOL_GEOL")
SELECT v.proj_id, v.loca_id, v.geol_top, v.geol_base, v.geol_desc, v.geol_geol
FROM (VALUES
    -- BH-1 (23.45 m termination, mirroring BH-2 geology)
    ('TDAC-2026-09-901', 'BH-1',  0.0,  1.8, 'Top Soil / Fill', 'SAND'),
    ('TDAC-2026-09-901', 'BH-1',  1.8,  3.0, 'Soft Silty CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-1',  3.0,  6.5, 'Soft Silty CLAY with Organic Matter', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-1',  6.5, 12.0, 'Soft to Firm Silty CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-1', 12.0, 16.0, 'Firm Silty CLAY with shell fragments', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-1', 16.0, 20.0, 'Stiff Sandy CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-1', 20.0, 23.45, 'Dense Fine to Medium SAND', 'SAND'),
    -- BH-3 (15.50 m termination)
    ('TDAC-2026-09-901', 'BH-3',  0.0,  1.0, 'Fill', 'SAND'),
    ('TDAC-2026-09-901', 'BH-3',  1.0,  3.5, 'Soft CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-3',  3.5,  7.0, 'Soft Silty CLAY with Decayed Wood', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-3',  7.0, 11.0, 'Firm Silty CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-3', 11.0, 13.5, 'Stiff Sandy CLAY', 'CLAY'),
    ('TDAC-2026-09-901', 'BH-3', 13.5, 15.50, 'Very Stiff Clay / Dense Sand', 'SAND')
) AS v(proj_id, loca_id, geol_top, geol_base, geol_desc, geol_geol)
WHERE NOT EXISTS (
    SELECT 1 FROM "ags42"."GEOL" g
    WHERE g."PROJ_ID" = v.proj_id AND g."LOCA_ID" = v.loca_id
      AND g."GEOL_TOP" = v.geol_top AND g."GEOL_BASE" = v.geol_base
);

--------------------------------------------------------------------------------
-- C. BH-1 and BH-3 SPT records (ISPT), realistic — BH-2 already seeded
--------------------------------------------------------------------------------
INSERT INTO "ags42"."ISPT" ("PROJ_ID", "LOCA_ID", "ISPT_TOP", "ISPT_INC1", "ISPT_INC2", "ISPT_INC3", "ISPT_NVAL")
SELECT v.proj_id, v.loca_id, v.ispt_top, v.inc1, v.inc2, v.inc3, v.nval
FROM (VALUES
    ('TDAC-2026-09-901', 'BH-1',  1.5, 1, 2, 2, 4),
    ('TDAC-2026-09-901', 'BH-1',  3.0, 1, 1, 2, 3),
    ('TDAC-2026-09-901', 'BH-1',  6.0, 1, 2, 2, 4),
    ('TDAC-2026-09-901', 'BH-1',  9.0, 2, 3, 3, 6),
    ('TDAC-2026-09-901', 'BH-1', 12.0, 3, 4, 4, 8),
    ('TDAC-2026-09-901', 'BH-1', 15.0, 5, 7, 8, 15),
    ('TDAC-2026-09-901', 'BH-1', 18.0, 9, 12, 13, 25),
    ('TDAC-2026-09-901', 'BH-1', 21.0, 14, 20, 22, 42),
    ('TDAC-2026-09-901', 'BH-1', 23.0, 13, 18, 24, 42),
    ('TDAC-2026-09-901', 'BH-3',  2.0, 1, 1, 1, 2),
    ('TDAC-2026-09-901', 'BH-3',  4.0, 1, 1, 1, 2),
    ('TDAC-2026-09-901', 'BH-3',  6.0, 1, 1, 2, 3),
    ('TDAC-2026-09-901', 'BH-3',  9.0, 2, 3, 3, 6),
    ('TDAC-2026-09-901', 'BH-3', 12.0, 4, 6, 7, 13),
    ('TDAC-2026-09-901', 'BH-3', 14.0, 7, 10, 12, 22)
) AS v(proj_id, loca_id, ispt_top, inc1, inc2, inc3, nval)
WHERE NOT EXISTS (
    SELECT 1 FROM "ags42"."ISPT" s
    WHERE s."PROJ_ID" = v.proj_id AND s."LOCA_ID" = v.loca_id AND s."ISPT_TOP" = v.ispt_top
);

--------------------------------------------------------------------------------
-- D. Lab workflow: revisions + status transitions so tabs read real rows.
--
-- Historic reads lab.test WHERE status='APPROVED' and pulls ll/pi from the
-- current revision's calculation_output_snapshot (get_approved_results).
-- QA reads lab.test WHERE status='SUBMITTED' and counts validation_issue.
-- So we need: a test_revision per moved test, and review_event for audit.
--------------------------------------------------------------------------------

-- D1. APPROVE the two ATTERBERG tests on the first sample (Historic will show them)
INSERT INTO lab.test_revision (
    test_id, revision_no, raw_input_snapshot, calculation_output_snapshot,
    validation_snapshot, calculation_package, calculation_package_version,
    method_definition_id, revision_reason, status, immutable, created_by
)
SELECT
    t.test_id, 1,
    '{"reads":{"blows":[18,24,31],"masses":{"c1":{"wet":27.31,"dry":22.01}}}}'::jsonb,
    json_build_object('liquid_limit', 52.0, 'plasticity_index', 28.0,
                      'flow_index', 24.0, 'plastic_limit', 24.0),
    '{"errors":0,"warnings":0}'::jsonb,
    m.calculation_package, m.calculation_package_version,
    t.method_definition_id, 'Initial approved release', 'APPROVED', true, 'demo'
FROM lab.test t
JOIN lab.method_definition m ON m.method_definition_id = t.method_definition_id
WHERE t.samp_id IN ('TDAC-2026-09-901-1','TDAC-2026-09-901-2','TDAC-2026-09-901-4')
  AND t.test_type = 'ATTERBERG'
  AND NOT EXISTS (SELECT 1 FROM lab.test_revision r WHERE r.test_id = t.test_id AND r.revision_no = 1);

UPDATE lab.test SET status = 'APPROVED', updated_by = 'demo'
WHERE samp_id IN ('TDAC-2026-09-901-1','TDAC-2026-09-901-2','TDAC-2026-09-901-4')
  AND test_type = 'ATTERBERG';

-- Eligible APPROVED tests now exist -> Historic shows 3 rows with LL 52 / PI 28.

-- D2. SUBMIT two more tests for QA (they will appear in the review queue)
INSERT INTO lab.test_revision (
    test_id, revision_no, raw_input_snapshot, calculation_output_snapshot,
    validation_snapshot, calculation_package, calculation_package_version,
    method_definition_id, revision_reason, status, immutable, created_by
)
SELECT
    t.test_id, 1,
    '{}'::jsonb, '{}'::jsonb,
    json_build_object('errors', 0, 'warnings', 2),
    m.calculation_package, m.calculation_package_version,
    t.method_definition_id, 'Submitted for independent check', 'SUBMITTED', false, 'demo'
FROM lab.test t
JOIN lab.method_definition m ON m.method_definition_id = t.method_definition_id
WHERE (t.samp_id, t.spec_ref, t.test_type) IN (
    -- the PSD on sample -1 and the TRIAXIAL_UU on sample -3
    ('TDAC-2026-09-901-1', 'SP-02', 'PSD'),
    ('TDAC-2026-09-901-3', 'SP-01', 'TRIAXIAL_UU')
)
  AND NOT EXISTS (SELECT 1 FROM lab.test_revision r WHERE r.test_id = t.test_id AND r.revision_no = 1);

UPDATE lab.test SET status = 'SUBMITTED', updated_by = 'demo'
WHERE (samp_id, spec_ref, test_type) IN (
    ('TDAC-2026-09-901-1', 'SP-02', 'PSD'),
    ('TDAC-2026-09-901-3', 'SP-01', 'TRIAXIAL_UU')
);

-- validation_issue rows so the QA validation column shows real warnings (2 warnings)
-- Linked to the PSD test on sample -1 by logical identity (not a UUID literal).
INSERT INTO lab.validation_issue (
    validation_issue_id, test_id, revision_no, rule_code, severity, field_path,
    message, observed_value, expected_rule, resolved
)
SELECT gen_random_uuid(), t.test_id, 1, c.rule_code, c.severity, c.field_path,
       c.message, c.observed_value::jsonb, c.expected_rule::jsonb, false
FROM lab.test t
CROSS JOIN (VALUES
    ('W-CALC-01','WARNING','calculation.particle_density',
     'Hydrometer temperature correction not entered; assumed 27.0C',
     '{"value":null}','{"needed":true}'),
    ('W-DRYMASS-02','WARNING','calculation.dry_mass',
     'Dry specimen mass fell 2% short of the method minimum; result flagged',
     '{"value":500.1}','{"min":510}')
) AS c(rule_code, severity, field_path, message, observed_value, expected_rule)
WHERE t.samp_id = 'TDAC-2026-09-901-1'
  AND t.spec_ref = 'SP-02'
  AND t.test_type = 'PSD'
  AND NOT EXISTS (
      SELECT 1 FROM lab.validation_issue v
      WHERE v.test_id = t.test_id AND v.rule_code = c.rule_code
  );

-- D3. review_event rows for the approved tests (audit trail)
INSERT INTO lab.review_event (
    review_event_id, test_id, revision_no, event_type, from_status, to_status,
    actor, actor_role, reason, correlation_id
)
SELECT gen_random_uuid(), t.test_id, 1, ev.event_type, ev.from_status, ev.to_status,
       'su@tdac', ev.actor_role, ev.reason, 'demo-' || t.test_id
FROM lab.test t
JOIN (VALUES
    ('CALCULATED','DRAFT','CALCULATED','lab','Calculation run OK'),
    ('CHECKED','CALCULATED','CHECKED','checker','Independent check passed'),
    ('APPROVED','CHECKED','APPROVED','approver','Approved for release')
) AS ev(event_type, from_status, to_status, actor_role, reason)
  ON t.status = 'APPROVED'
WHERE NOT EXISTS (
    SELECT 1 FROM lab.review_event e WHERE e.test_id = t.test_id AND e.event_type = ev.event_type
);-- ============================================================================
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

--------------------------------------------------------------------------------
-- PART 6 - revision calculation snapshots
--
-- Results Entry stores a revision's calculated outputs as {"outputs": {...}}.
-- Revisions seeded without that block have nothing for the AGS release step to
-- project, so a checked and approved test could never be published. Rather than
-- invent numbers, take them from each revision's own recorded readings: the
-- triaxial specimen already carries its measured undrained shear strength, and
-- the gradation readings carry percent passing and retained at each sieve.
-- Snapshots are only filled when empty, so re-running this changes nothing.
--------------------------------------------------------------------------------
UPDATE lab."test_revision" r
   SET "calculation_output_snapshot" = jsonb_build_object(
           'outputs', jsonb_build_object('cu', s."undrained_shear_strength_kpa"))
  FROM lab."triaxial_uu_specimen" s
 WHERE s."test_id" = r."test_id"
   AND s."revision_no" = r."revision_no"
   AND s."undrained_shear_strength_kpa" IS NOT NULL
   AND (r."calculation_output_snapshot" IS NULL
        OR r."calculation_output_snapshot" = '{}'::jsonb);

UPDATE lab."test_revision" r
   SET "calculation_output_snapshot" = jsonb_build_object(
           'outputs', jsonb_build_object(
               'percent_passing', f."percent_passing",
               'percent_retained', f."percent_retained"))
  FROM (
        SELECT DISTINCT ON ("test_id", "revision_no")
               "test_id", "revision_no", "percent_passing", "percent_retained"
          FROM lab."psd_sieve_reading"
         WHERE "percent_passing" IS NOT NULL
           AND "percent_retained" IS NOT NULL
         ORDER BY "test_id", "revision_no", "sieve_opening_mm" ASC
       ) f
 WHERE f."test_id" = r."test_id"
   AND f."revision_no" = r."revision_no"
   AND (r."calculation_output_snapshot" IS NULL
        OR r."calculation_output_snapshot" = '{}'::jsonb);
