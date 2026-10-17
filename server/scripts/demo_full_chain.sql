-- TDAC demo data: full chain from project through field data to lab tests.
-- Follows the app's real ID rules: project TDAC-YYYY-MM-N, sample {project}-{N}.
-- Run order matters: PROJ -> FILE -> LOCA -> GEOL/ISPT + PROJ_METADATA -> SAMP -> CORE/sample-id map -> lab.test.
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

--------------------------------------------------------------------------------
-- 6. Sampling / coring records
--
-- The app records a sample as a CORE interval plus its SAMP identity in one
-- action (create_sampling_record); the Sampling / Coring view reads CORE joined
-- to the app's sample-id map. This seed originally wrote only the SAMP half, so
-- that view came up empty. Backfill the missing half from the samples already
-- present. Recovery and RQD are left NULL: these are undisturbed soil samples,
-- not rock core runs, and no recovery was measured. Re-running changes nothing.
--------------------------------------------------------------------------------
INSERT INTO "ags42"."CORE" ("PROJ_ID", "LOCA_ID", "CORE_TOP", "CORE_BASE", "CORE_REM")
SELECT
    s."PROJ_ID",
    s."LOCA_ID",
    s."SAMP_TOP",
    s."SAMP_BASE",
    CASE s."SAMP_TYPE"
        WHEN 'U' THEN 'Undisturbed (UD) sample'
        WHEN 'D' THEN 'Disturbed sample'
        ELSE NULL
    END
FROM "ags42"."SAMP" s
WHERE s."PROJ_ID" = 'TDAC-2026-09-901'
  AND NOT EXISTS (
      SELECT 1 FROM "ags42"."CORE" c
      WHERE c."PROJ_ID" = s."PROJ_ID"
        AND c."LOCA_ID" = s."LOCA_ID"
        AND c."CORE_TOP" = s."SAMP_TOP"
        AND c."CORE_BASE" = s."SAMP_BASE"
  );

INSERT INTO "tdac"."SAMPLING_RECORD_ID" ("SAMPLE_ID", "PROJ_ID", "LOCA_ID", "DEPTH_FROM")
SELECT s."SAMP_ID", s."PROJ_ID", s."LOCA_ID", s."SAMP_TOP"
FROM "ags42"."SAMP" s
WHERE s."PROJ_ID" = 'TDAC-2026-09-901'
  AND NOT EXISTS (
      SELECT 1 FROM "tdac"."SAMPLING_RECORD_ID" r
      WHERE r."PROJ_ID" = s."PROJ_ID"
        AND r."LOCA_ID" = s."LOCA_ID"
        AND r."DEPTH_FROM" = s."SAMP_TOP"
  );

-- Keep the sample-id counter ahead of the seeded ids so the next record
-- continues the sequence (8, 9, ...) instead of colliding with a sample.
INSERT INTO "tdac"."SAMPLE_ID_COUNTER" ("PROJ_ID", "LAST_NUMBER")
SELECT 'TDAC-2026-09-901', MAX((regexp_replace(s."SAMP_ID", '^.*-', ''))::int)
FROM "ags42"."SAMP" s
WHERE s."PROJ_ID" = 'TDAC-2026-09-901'
  AND s."SAMP_ID" ~ '-[0-9]+$'
ON CONFLICT ("PROJ_ID") DO UPDATE
SET "LAST_NUMBER" = GREATEST("tdac"."SAMPLE_ID_COUNTER"."LAST_NUMBER", EXCLUDED."LAST_NUMBER");