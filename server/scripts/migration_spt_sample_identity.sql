-- TDAC — SPT sample identity backfill + attachment scoping
--
-- Why this exists
-- ---------------
-- Attachments for an SPT record must be anchored on SAMPLE_ID, not on depth:
-- update_spt_record allows ISPT_TOP to change, so a depth anchor would orphan
-- every photo the moment a depth was edited. SAMPLE_ID is allocated once and
-- survives depth edits.
--
-- The blocker: SAMPLE_ID is only allocated when a record is submitted through
-- the workflow. Pre-existing and merely-drafted ISPT rows have no status row
-- and therefore no SAMPLE_ID, so they cannot host a photo.
--
--   Measured on the live database before this migration:
--     29 of 36 SPT rows had no SAMPLE_ID.
--
-- This migration gives every ISPT row a SAMPLE_ID so any row can carry files.
-- It is additive: no AGS table is touched, no existing row is modified, and
-- no existing sample id is renumbered.
--
-- Reversible with:
--   DELETE FROM "tdac"."SPT_RECORD_STATUS"
--    WHERE "CREATED_BY" IS NULL AND "SAMPLE_ID" IN (<the ids this run added>);
-- Capture them with the temp table below before COMMIT, or scope the delete
-- to "CREATED_AT >= <run start>".

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Attachments gain a scope
-- ---------------------------------------------------------------------------
-- entity_kind + sample_id make the table polymorphic by scope rather than by
-- a second table. 'project' keeps every row written before this migration and
-- is what the project-header panel lists. 'sample' is any file anchored to a
-- sample: SPT now, cores and UD samples later, all of which already have a
-- SAMPLE_ID.
ALTER TABLE "tdac"."attachments"
    ADD COLUMN IF NOT EXISTS "entity_kind" TEXT NOT NULL DEFAULT 'project',
    ADD COLUMN IF NOT EXISTS "sample_id" TEXT;

-- The schema contract: the two legal shapes, and nothing else.
ALTER TABLE "tdac"."attachments"
    DROP CONSTRAINT IF EXISTS chk_attachments_entity;
ALTER TABLE "tdac"."attachments"
    ADD CONSTRAINT chk_attachments_entity CHECK (
        ("entity_kind" = 'project' AND "sample_id" IS NULL)
        OR ("entity_kind" = 'sample' AND "sample_id" IS NOT NULL)
    );

-- Hot path: the per-row attachment count in the SPT list, and the
-- sample-scoped panel listing.
CREATE INDEX IF NOT EXISTS ix_attachments_sample
    ON "tdac"."attachments" ("project_id", "sample_id")
    WHERE "entity_kind" = 'sample';

-- Hot path: the project-header panel, which must NOT see sample files.
CREATE INDEX IF NOT EXISTS ix_attachments_project_only
    ON "tdac"."attachments" ("project_id", "uploaded_at" DESC)
    WHERE "entity_kind" = 'project';

-- ---------------------------------------------------------------------------
-- 2. Backfill a SAMPLE_ID for every ISPT row that lacks one
-- ---------------------------------------------------------------------------
-- Recorded so the run is reversible and auditable.
CREATE TEMP TABLE _backfilled_samples ON COMMIT DROP AS
SELECT i."PROJ_ID" AS proj_id, i."LOCA_ID" AS loca_id,
       i."ISPT_TOP" AS depth_from, 'pending' AS sample_id
FROM "ags42"."ISPT" i
LEFT JOIN "tdac"."SPT_RECORD_STATUS" sr
    ON sr."PROJ_ID" = i."PROJ_ID"
   AND sr."LOCA_ID" = i."LOCA_ID"
   AND sr."DEPTH_FROM" = i."ISPT_TOP"
WHERE sr."PROJ_ID" IS NULL;

\echo 'ISPT rows needing a sample id:'
SELECT COUNT(*) FROM _backfilled_samples;

-- Allocate ids from the shared counter, then advance the counter in the same
-- transaction so the next manual submit cannot collide with these.
--
-- Two deliberate choices:
--   * STATUS = 'APPROVED', not 'PENDING'. The CHECK allows only PENDING,
--     APPROVED and REJECTED. Writing PENDING would drop 29 rows nobody
--     submitted into the admin approval queue.
--   * CREATED_BY IS NULL because a legacy row has no known author. It is also
--     the marker that distinguishes a migration row from an app row.
--
-- Note: ags42.ISPT has no CREATED_AT column, so there is no honest historical
-- timestamp to preserve. now() is used and CREATED_BY IS NULL marks it.
WITH allocated AS (
    SELECT
        b."proj_id", b."loca_id", b."depth_from",
        b."proj_id" || '-' || (c."LAST_NUMBER" + ROW_NUMBER()
            OVER (PARTITION BY b."proj_id" ORDER BY b."loca_id", b."depth_from")
            )::TEXT AS sample_id,
        c."LAST_NUMBER" AS counter_before
    FROM _backfilled_samples b
    JOIN "tdac"."SAMPLE_ID_COUNTER" c ON c."PROJ_ID" = b."proj_id"
),
inserted AS (
    INSERT INTO "tdac"."SPT_RECORD_STATUS" (
        "PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
        "STATUS", "CREATED_BY", "CREATED_AT"
    )
    SELECT a."proj_id", a."loca_id", a."depth_from", a."sample_id",
           'APPROVED', NULL, now()
    FROM allocated a
    RETURNING "SAMPLE_ID"
)
UPDATE _backfilled_samples b
SET "sample_id" = i."SAMPLE_ID"
FROM inserted i, allocated a
WHERE i."SAMPLE_ID" = a."sample_id"
  AND b."proj_id" = a."proj_id"
  AND b."loca_id" = a."loca_id"
  AND b."depth_from" = a."depth_from";

-- ---------------------------------------------------------------------------
-- 3. Advance the shared counter above every allocated id
-- ---------------------------------------------------------------------------
-- SAMPLE_ID_COUNTER is shared by SPT_RECORD_STATUS and SAMPLING_RECORD_ID, so
-- the floor must come from BOTH tables.
--
-- The trailing-digit extraction must be a regex, not split_part: sample ids
-- look like 'TDAC-2026-09-901-16', so split_part(x, '-', 3) yields '09' and
-- ('TDAC-2026-09-901-16')::text::int raises 'invalid input syntax'.
UPDATE "tdac"."SAMPLE_ID_COUNTER" c
SET "LAST_NUMBER" = GREATEST(
        c."LAST_NUMBER",
        COALESCE((
            SELECT MAX((substring(s."SAMPLE_ID" from '([0-9]+)$'))::int)
            FROM (
                SELECT "SAMPLE_ID" FROM "tdac"."SPT_RECORD_STATUS"
                WHERE "PROJ_ID" = c."PROJ_ID"
                UNION ALL
                SELECT "SAMPLE_ID" FROM "tdac"."SAMPLING_RECORD_ID"
                WHERE "PROJ_ID" = c."PROJ_ID"
            ) s
            WHERE s."SAMPLE_ID" ~ '-[0-9]+$'
        ), 0)
    )
WHERE EXISTS (SELECT 1 FROM _backfilled_samples b WHERE b."proj_id" = c."PROJ_ID");

-- Ensure a counter row exists for any project that had backfilled rows but no
-- counter yet, then set it the same way.
INSERT INTO "tdac"."SAMPLE_ID_COUNTER" ("PROJ_ID", "LAST_NUMBER")
SELECT DISTINCT b."proj_id", 0 FROM _backfilled_samples b
ON CONFLICT ("PROJ_ID") DO NOTHING;

UPDATE "tdac"."SAMPLE_ID_COUNTER" c
SET "LAST_NUMBER" = GREATEST(
        c."LAST_NUMBER",
        COALESCE((
            SELECT MAX((substring(s."SAMPLE_ID" from '([0-9]+)$'))::int)
            FROM (
                SELECT "SAMPLE_ID" FROM "tdac"."SPT_RECORD_STATUS"
                WHERE "PROJ_ID" = c."PROJ_ID"
                UNION ALL
                SELECT "SAMPLE_ID" FROM "tdac"."SAMPLING_RECORD_ID"
                WHERE "PROJ_ID" = c."PROJ_ID"
            ) s
            WHERE s."SAMPLE_ID" ~ '-[0-9]+$'
        ), 0)
    )
WHERE EXISTS (SELECT 1 FROM _backfilled_samples b WHERE b."proj_id" = c."PROJ_ID");

-- ---------------------------------------------------------------------------
-- 4. Self-verification
-- ---------------------------------------------------------------------------
\echo 'ISPT rows still without a sample id (must be 0):'
SELECT COUNT(*) AS still_missing
FROM "ags42"."ISPT" i
LEFT JOIN "tdac"."SPT_RECORD_STATUS" sr
    ON sr."PROJ_ID" = i."PROJ_ID"
   AND sr."LOCA_ID" = i."LOCA_ID"
   AND sr."DEPTH_FROM" = i."ISPT_TOP"
WHERE sr."PROJ_ID" IS NULL;

\echo 'Migration rows added (CREATED_BY IS NULL):'
SELECT COUNT(*) FROM "tdac"."SPT_RECORD_STATUS" WHERE "CREATED_BY" IS NULL;

\echo 'Counter position per project:'
SELECT "PROJ_ID", "LAST_NUMBER" FROM "tdac"."SAMPLE_ID_COUNTER" ORDER BY "PROJ_ID";

\echo 'Ids allocated by this run:'
SELECT * FROM _backfilled_samples ORDER BY "proj_id", "depth_from";

-- Roll back automatically if any ISPT row still lacks a sample id. A
-- half-applied backfill is worse than none: those rows would silently fail
-- to accept photos later.
DO $$
DECLARE
    missing INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing
    FROM "ags42"."ISPT" i
    LEFT JOIN "tdac"."SPT_RECORD_STATUS" sr
        ON sr."PROJ_ID" = i."PROJ_ID"
       AND sr."LOCA_ID" = i."LOCA_ID"
       AND sr."DEPTH_FROM" = i."ISPT_TOP"
    WHERE sr."PROJ_ID" IS NULL;

    IF missing > 0 THEN
        RAISE EXCEPTION 'Backfill incomplete: % ISPT rows still lack a SAMPLE_ID. Rolling back.', missing;
    END IF;
END $$;

COMMIT;