-- Migration: Field Data user attribution + field-level audit support.
--
-- Smallest-footprint change. No AGS4.2 (ags42.*) table is touched and no new
-- user system / Sample ID generator / audit table is created:
--   * field-level history is written to the EXISTING tdac.audit_log
--   * Sample IDs keep coming from the EXISTING tdac."SAMPLE_ID_COUNTER"
--   * creators reference the EXISTING tdac.users
--
-- 1. tdac."BOREHOLE_RECORD_META": "Created By" for Borehole / Drilling rows.
--    Same pattern as tdac."SPT_RECORD_STATUS" / tdac."SAMPLING_RECORD_ID":
--    keyed by (PROJ_ID, LOCA_ID, DEPTH_FROM = GEOL_TOP), re-keyed when the
--    depth is edited. Existing rows simply have no meta row (shown as "-").
-- 2. tdac."SAMPLING_RECORD_ID": nullable CREATED_BY / CREATED_AT for coring
--    samples (SPT samples already have them in SPT_RECORD_STATUS).
-- 3. Two partial indexes so the Admin audit lookups on audit_log stay fast.

BEGIN;

CREATE TABLE IF NOT EXISTS tdac."BOREHOLE_RECORD_META" (
    "PROJ_ID"     text NOT NULL,
    "LOCA_ID"     text NOT NULL,
    "DEPTH_FROM"  numeric NOT NULL,
    "CREATED_BY"  bigint REFERENCES tdac.users(id),
    "CREATED_AT"  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY ("PROJ_ID", "LOCA_ID", "DEPTH_FROM")
);

ALTER TABLE tdac."SAMPLING_RECORD_ID"
    ADD COLUMN IF NOT EXISTS "CREATED_BY" bigint REFERENCES tdac.users(id);
ALTER TABLE tdac."SAMPLING_RECORD_ID"
    ADD COLUMN IF NOT EXISTS "CREATED_AT" timestamptz;

CREATE INDEX IF NOT EXISTS ix_audit_log_borehole_entry
    ON tdac.audit_log ((meta->>'project_id'), (meta->>'loca_id'))
    WHERE action LIKE 'BOREHOLE\_%';

CREATE INDEX IF NOT EXISTS ix_audit_log_sample_entry
    ON tdac.audit_log ((meta->>'sample_id'))
    WHERE meta ? 'sample_id';

COMMIT;
