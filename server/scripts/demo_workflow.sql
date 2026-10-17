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
);