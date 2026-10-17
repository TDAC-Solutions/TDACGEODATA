-- Migration: SPT approval / status / creator tracking.
--
-- Minimum-footprint addition: one new TDAC extension table, following the
-- exact same pattern as the existing tdac."SAMPLING_RECORD_ID" table (which
-- already extends ags42."CORE" without adding columns to the AGS4.2 table).
-- No columns are added to ags42."ISPT" and no new Sample ID generator is
-- created — tdac."SAMPLE_ID_COUNTER" (existing) is reused as-is.
--
-- Keyed by (PROJ_ID, LOCA_ID, DEPTH_FROM) where DEPTH_FROM = ISPT.ISPT_TOP,
-- exactly mirroring how tdac."SAMPLING_RECORD_ID" keys off CORE_TOP.

BEGIN;

CREATE TABLE IF NOT EXISTS tdac."SPT_RECORD_STATUS" (
    "PROJ_ID"        text NOT NULL,
    "LOCA_ID"        text NOT NULL,
    "DEPTH_FROM"     numeric NOT NULL,
    "SAMPLE_ID"      text NOT NULL,
    "STATUS"         text NOT NULL DEFAULT 'PENDING'
                         CHECK ("STATUS" IN ('PENDING', 'APPROVED', 'REJECTED')),
    "CREATED_BY"     bigint REFERENCES tdac.users(id),
    "CREATED_AT"     timestamptz NOT NULL DEFAULT now(),
    "APPROVED_BY"    bigint REFERENCES tdac.users(id),
    "APPROVED_AT"    timestamptz,
    "REJECT_REASON"  text,
    PRIMARY KEY ("PROJ_ID", "LOCA_ID", "DEPTH_FROM")
);

CREATE INDEX IF NOT EXISTS ix_spt_record_status_status
    ON tdac."SPT_RECORD_STATUS" ("STATUS");

COMMIT;
