-- Migration: Field Data > Rock (approval workflow + TDAC-specific fields).
--
-- Minimum-footprint addition: ONE new TDAC table, following the exact same
-- pattern as tdac."SPT_RECORD_STATUS" (identity + approval state) and
-- tdac."SAMPLING_RECORD_ID" (extends an AGS table without adding columns to it).
--
--   * No ags42.* table is altered. Rock values still live in the AGS tables:
--       Run Depth From -> ags42."CORE"."CORE_TOP"
--       Run Depth To   -> ags42."CORE"."CORE_BASE"
--       Recovery %     -> ags42."CORE"."CORE_PREC"
--       RQD            -> ags42."CORE"."CORE_RQD"
--       Type of Rock   -> ags42."GEOL"."GEOL_DESC" (interval CORE_TOP..CORE_BASE)
--   * Only the two TDAC-specific fields have no AGS home, so they are stored
--     here: "LIFT_NO" and "PIECE_LENGTH_CM".
--   * No new Sample ID generator: "SAMPLE_ID" is allocated from the existing
--     tdac."SAMPLE_ID_COUNTER" by the application, same as SPT / coring.
--   * Approval/creator/approver columns mirror tdac."SPT_RECORD_STATUS".
--
-- Keyed by (PROJ_ID, LOCA_ID, DEPTH_FROM) where DEPTH_FROM = CORE_TOP, i.e. the
-- run's top depth. Several runs at one location are different DEPTH_FROM values,
-- so multiple runs per location are supported.
--
-- Additive and idempotent (IF NOT EXISTS). Reversible with:
--   DROP TABLE IF EXISTS tdac."ROCK_RECORD";

BEGIN;

CREATE TABLE IF NOT EXISTS tdac."ROCK_RECORD" (
    "PROJ_ID"          text    NOT NULL,
    "LOCA_ID"          text    NOT NULL,
    "DEPTH_FROM"       numeric NOT NULL,
    "SAMPLE_ID"        text    NOT NULL,
    "STATUS"           text    NOT NULL DEFAULT 'PENDING'
                           CHECK ("STATUS" IN ('PENDING', 'APPROVED', 'REJECTED')),
    "LIFT_NO"          text,
    "PIECE_LENGTH_CM"  numeric CHECK ("PIECE_LENGTH_CM" IS NULL OR "PIECE_LENGTH_CM" >= 0),
    "CREATED_BY"       bigint REFERENCES tdac.users(id),
    "CREATED_AT"       timestamptz NOT NULL DEFAULT now(),
    "APPROVED_BY"      bigint REFERENCES tdac.users(id),
    "APPROVED_AT"      timestamptz,
    "REJECT_REASON"    text,
    PRIMARY KEY ("PROJ_ID", "LOCA_ID", "DEPTH_FROM")
);

-- A Sample ID identifies exactly one record in a project.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rock_record_sample
    ON tdac."ROCK_RECORD" ("PROJ_ID", "SAMPLE_ID");

CREATE INDEX IF NOT EXISTS ix_rock_record_status
    ON tdac."ROCK_RECORD" ("STATUS");

COMMIT;
