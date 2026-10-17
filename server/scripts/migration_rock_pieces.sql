-- Migration: Rock pieces (Field Data > Rock).
--
-- Replaces the single hand-typed total with the individual piece lengths that
-- the total was always a stand-in for, so Recovery and RQD can be derived
-- instead of asserted.
--
--   * ONE new TDAC table, following the same pattern as tdac."ROCK_RECORD":
--     keyed on (PROJ_ID, LOCA_ID, DEPTH_FROM) so pieces belong to exactly one
--     run and are written, replaced and deleted with it.
--   * "BLOCK_NO" is the 1-based order the pieces were entered in, which is
--     what the "Block Number 1, 2, 3, ..." boxes show, and it is part of the
--     key so a run can hold a different number of pieces than its neighbour.
--   * "LENGTH_CM" is ALWAYS centimetres. The UI lets the engineer type metres
--     or centimetres, but the conversion happens on the server so the stored
--     unit can never depend on what a browser decided to send. The RQD
--     10 cm threshold is therefore always applied to these values.
--   * tdac."ROCK_RECORD"."PIECE_LENGTH_CM" is dropped: the total is now
--     SUM("LENGTH_CM"), so keeping it would store a second, redundant number
--     that could disagree with the pieces.
--   * No ags42.* table is altered. Recovery and RQD keep living in
--     ags42."CORE"."CORE_PREC" / "CORE_RQD"; they are simply computed now.
--
-- Additive and idempotent (IF NOT EXISTS).
--
-- Reversible with:
--   ALTER TABLE tdac."ROCK_RECORD" ADD COLUMN "PIECE_LENGTH_CM" numeric;
--   DROP TABLE IF EXISTS tdac."ROCK_PIECE";
--
-- NOTE: dropping PIECE_LENGTH_CM discards the old hand-typed totals. Run
-- this only where no Rock record has been entered yet, or accept the loss --
-- the totals are derivable from the pieces once those exist. Use
-- PIECES_ONLY_DROP_TOTAL=0 to keep the column for a staged rollout.

BEGIN;

CREATE TABLE IF NOT EXISTS tdac."ROCK_PIECE" (
    "PROJ_ID"     text    NOT NULL,
    "LOCA_ID"     text    NOT NULL,
    "DEPTH_FROM"  numeric NOT NULL,
    "SAMPLE_ID"   text    NOT NULL,
    "BLOCK_NO"    integer NOT NULL CHECK ("BLOCK_NO" >= 1),
    "LENGTH_CM"   numeric NOT NULL CHECK ("LENGTH_CM" >= 0),
    PRIMARY KEY ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "BLOCK_NO")
);

CREATE INDEX IF NOT EXISTS ix_rock_piece_sample
    ON tdac."ROCK_PIECE" ("PROJ_ID", "SAMPLE_ID");

-- Carry an existing total across as a single piece, so a run entered before
-- this migration keeps a value and does not silently become 0% recovery.
-- Only runs that still have the old column are touched.
DO $$
DECLARE
    carried integer := 0;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'tdac' AND table_name = 'ROCK_RECORD'
          AND column_name = 'PIECE_LENGTH_CM'
    ) THEN
        INSERT INTO tdac."ROCK_PIECE"
            ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID", "BLOCK_NO", "LENGTH_CM")
        SELECT "PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID", 1, "PIECE_LENGTH_CM"
        FROM tdac."ROCK_RECORD"
        WHERE "PIECE_LENGTH_CM" IS NOT NULL AND "PIECE_LENGTH_CM" > 0
        ON CONFLICT DO NOTHING;

        GET DIAGNOSTICS carried = ROW_COUNT;
        RAISE NOTICE 'carried % existing rock total(s) into ROCK_PIECE', carried;

        IF current_setting('tdac.pieces_only_drop_total', true) IS DISTINCT FROM '0' THEN
            ALTER TABLE tdac."ROCK_RECORD" DROP COLUMN "PIECE_LENGTH_CM";
            RAISE NOTICE 'dropped tdac."ROCK_RECORD"."PIECE_LENGTH_CM"';
        END IF;
    END IF;
END $$;

COMMIT;