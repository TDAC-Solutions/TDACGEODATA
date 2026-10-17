-- TDAC demo data: one project, 3 locations, samples per location, multiple tests per sample.
-- Follows the app's real ID rules: project TDAC-YYYY-MM-N, sample {project}-{N}.
-- Run order matters: PROJ -> FILE -> LOCA -> SAMP -> lab.test (FK chain).
-- Guarded with WHERE NOT EXISTS so re-running never duplicates.

-- 0. Project (carry-forward root)
INSERT INTO "ags42"."PROJ" ("PROJ_ID", "PROJ_NAME", "PROJ_LOC", "PROJ_CLNT", "PROJ_ENG", "PROJ_CONT")
SELECT 'TDAC-2026-09-901', 'Champakkulam GI Investigation', 'CHAMPAKKULAM', 'Mr. BEJOY MICHLE', 'TDAC Engineering', 'TDAC Consultants'
WHERE NOT EXISTS (SELECT 1 FROM "ags42"."PROJ" WHERE "PROJ_ID" = 'TDAC-2026-09-901');

-- 0a. FILE row (create_lab_test reads FILE_FSET from the project)
INSERT INTO "ags42"."FILE" ("PROJ_ID", "FILE_FSET", "FILE_NAME", "FILE_TYPE")
SELECT 'TDAC-2026-09-901', 'FS-TDAC-901', 'TDAC-2026-09-901 AGS Data', 'AGS'
WHERE NOT EXISTS (SELECT 1 FROM "ags42"."FILE" WHERE "FILE_FSET" = 'FS-TDAC-901');

-- 0b. Project ID counter (so the app continues numbering AFTER the seed)
INSERT INTO "tdac"."PROJECT_ID_COUNTER" ("YEAR", "MONTH", "LAST_NUMBER")
VALUES (2026, 9, 901)
ON CONFLICT ("YEAR", "MONTH") DO NOTHING;

-- 1. Locations (3 boreholes)
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

-- 2. Samples (SAMP rows, different depths per borehole; SAMPLE_ID per app rule)
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

-- 3. Lab tests: MULTIPLE per sample (different spec_ref / test_type)
-- method_definition_id resolved by SELECT from the seeded methods - never hardcoded.
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
