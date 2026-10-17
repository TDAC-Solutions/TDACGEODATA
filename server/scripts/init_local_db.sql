-- TDAC_clean local database bootstrap.
--
-- Creates the exact tables the application touches and nothing else:
--   ags42: PROJ, LOCA, GEOL, CORE, ISPT  (column types follow the AGS 4.2
--          type-map used by the AGSValidator schema builder: ID/PA/X ->
--          TEXT, nDP -> NUMERIC, DT -> TIMESTAMP WITH TIME ZONE)
--   tdac:  roles, users                  (auth contract of app/auth/*)
--          PROJ_METADATA                  (project/report settings read and
--                                          written by portfolio_service.py,
--                                          including PROJECT_TYPE)
--
-- Idempotent: safe to re-run. Runs against the single real database
-- ags42_data (same one the app and the AGS projects use):
--   psql -h 127.0.0.1 -U postgres -d ags42_data -f server/scripts/init_local_db.sql
-- Existing tables are left untouched (CREATE TABLE IF NOT EXISTS).

\connect ags42_data

CREATE SCHEMA IF NOT EXISTS "ags42";
CREATE SCHEMA IF NOT EXISTS tdac;

-- ---------------------------------------------------------------------
-- ags42 data groups (only the columns this application reads/writes)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "ags42"."PROJ" (
    "PROJ_ID"   TEXT PRIMARY KEY,
    "PROJ_NAME" TEXT,
    "PROJ_LOC"  TEXT,
    "PROJ_CLNT" TEXT
);

CREATE TABLE IF NOT EXISTS "ags42"."LOCA" (
    "LOCA_ID"   TEXT NOT NULL,
    "LOCA_TYPE" TEXT,
    "LOCA_STAR" TIMESTAMP WITH TIME ZONE,
    "LOCA_ENDD" TIMESTAMP WITH TIME ZONE,
    "LOCA_FDEP" NUMERIC,
    "PROJ_ID"   TEXT NOT NULL REFERENCES "ags42"."PROJ" ("PROJ_ID")
);

-- Rule 10a: the KEY columns (*) form the identity of each record.
CREATE UNIQUE INDEX IF NOT EXISTS uq_loca_ident
    ON "ags42"."LOCA" ("LOCA_ID", "PROJ_ID");

CREATE TABLE IF NOT EXISTS "ags42"."GEOL" (
    "PROJ_ID"   TEXT NOT NULL,
    "LOCA_ID"   TEXT NOT NULL,
    "GEOL_TOP"  NUMERIC NOT NULL,
    "GEOL_BASE" NUMERIC NOT NULL,
    "GEOL_DESC" TEXT,
    "GEOL_GEOL" TEXT,
    FOREIGN KEY ("PROJ_ID", "LOCA_ID")
        REFERENCES "ags42"."LOCA" ("PROJ_ID", "LOCA_ID")
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_geol_ident
    ON "ags42"."GEOL" ("LOCA_ID", "GEOL_TOP", "GEOL_BASE", "PROJ_ID");

CREATE TABLE IF NOT EXISTS "ags42"."CORE" (
    "PROJ_ID"   TEXT NOT NULL,
    "LOCA_ID"   TEXT NOT NULL,
    "CORE_TOP"  NUMERIC NOT NULL,
    "CORE_BASE" NUMERIC NOT NULL,
    "CORE_PREC" NUMERIC,
    "CORE_RQD"  NUMERIC,
    "CORE_REM"  TEXT,
    FOREIGN KEY ("PROJ_ID", "LOCA_ID")
        REFERENCES "ags42"."LOCA" ("PROJ_ID", "LOCA_ID")
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_core_ident
    ON "ags42"."CORE" ("LOCA_ID", "CORE_TOP", "CORE_BASE", "PROJ_ID");

CREATE TABLE IF NOT EXISTS "ags42"."ISPT" (
    "PROJ_ID"    TEXT NOT NULL,
    "LOCA_ID"    TEXT NOT NULL,
    "ISPT_TOP"   NUMERIC NOT NULL,
    "ISPT_INC1"  NUMERIC,
    "ISPT_INC2"  NUMERIC,
    "ISPT_INC3"  NUMERIC,
    "ISPT_NVAL"  NUMERIC,
    FOREIGN KEY ("PROJ_ID", "LOCA_ID")
        REFERENCES "ags42"."LOCA" ("PROJ_ID", "LOCA_ID")
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ispt_ident
    ON "ags42"."ISPT" ("LOCA_ID", "ISPT_TOP", "PROJ_ID");

-- ---------------------------------------------------------------------
-- tdac auth schema (app/auth/user_service.py contract)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tdac.roles (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    permissions TEXT,
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Role ids fixed by the application: admin 1, engineer 2, client 10.
INSERT INTO tdac.roles (id, name) VALUES
    (1, 'admin'), (2, 'engineer'), (10, 'client')
ON CONFLICT (id) DO NOTHING;
SELECT setval(
    pg_get_serial_sequence('tdac.roles', 'id'),
    GREATEST((SELECT MAX(id) FROM tdac.roles), 10)
);

CREATE TABLE IF NOT EXISTS tdac.users (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role_id         BIGINT NOT NULL REFERENCES tdac.roles (id),
    token_gen       INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- tdac project metadata (Create project + Overview contract)
-- ---------------------------------------------------------------------
-- The project screens read and write these fields, PROJECT_TYPE among them,
-- so the table has to exist before any project screen or seed runs.

CREATE TABLE IF NOT EXISTS "tdac"."PROJ_METADATA" (
    "PROJ_ID"                               TEXT PRIMARY KEY,
    "ROAD_REFERENCE"                        TEXT,
    "CHAINAGE_TEXT"                         TEXT,
    "STRUCTURE_REFERENCE"                   TEXT,
    "SELECTED_BOREHOLES"                    TEXT,
    "PROJECT_TYPE"                          TEXT,
    "REPORT_TYPE"                           TEXT,
    "REPORT_TITLE"                          TEXT,
    "REPORT_VOLUME_TITLE"                   TEXT,
    "DOCUMENT_REFERENCE"                    TEXT,
    "REVISION"                              TEXT,
    "REPORT_DATE"                           DATE,
    "ISSUE_STATUS"                          TEXT,
    "TDAC_COMPANY_NAME"                     TEXT,
    "GROUNDWATER_BASIS"                     TEXT,
    "DESIGN_STANDARD_BASIS"                 TEXT,
    "FACTOR_OF_SAFETY_BASIS"                TEXT,
    "LOAD_COMBINATION_BASIS"                TEXT,
    "CONSTRUCTION_VERIFICATION_REQUIREMENT" TEXT,
    "PILE_LOAD_TEST_REQUIREMENT"            TEXT
);

-- A database created before a field was introduced keeps its old shape.
-- Add anything missing so an older clone matches this file.

ALTER TABLE "tdac"."PROJ_METADATA"
    ADD COLUMN IF NOT EXISTS "PROJECT_TYPE" TEXT;
