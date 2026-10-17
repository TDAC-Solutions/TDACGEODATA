-- Backfill ags42."FILE" for projects created through the UI before the
-- lazily-provisioning fix in lab_data_service._load_project_and_sample.
-- Each project gets exactly one deterministic file set (FS-<PROJ_ID>).
-- Idempotent: re-running inserts nothing new.
--
-- Run once against the live DB.

INSERT INTO "ags42"."FILE" ("PROJ_ID", "FILE_FSET", "FILE_NAME", "FILE_TYPE")
SELECT
    p."PROJ_ID",
    'FS-' || p."PROJ_ID",
    p."PROJ_ID" || ' AGS Data',
    'AGS'
FROM "ags42"."PROJ" p
WHERE NOT EXISTS (
    SELECT 1 FROM "ags42"."FILE" f WHERE f."PROJ_ID" = p."PROJ_ID"
)
ON CONFLICT ("PROJ_ID", "FILE_FSET", "FILE_NAME") DO NOTHING;
