-- TDAC — project attachments (SharePoint-backed file store)
--
-- Files live in SharePoint, not in this database: SharePoint is already
-- paid for, serves the previews, and keeps versioning and retention that
-- a byte column would not. This table holds metadata only — never file
-- content.
--
-- Access is role-based, matching the rest of TDAC: any authenticated user
-- who can open a project can list and download its attachments. There is
-- no per-user project scoping in TDAC, and this table does not introduce
-- one.

CREATE TABLE IF NOT EXISTS tdac.attachments (
    id                  BIGSERIAL PRIMARY KEY,

    -- Owning project. ags42.PROJ is the AGS project register; the FK keeps
    -- an attachment from outliving its project.
    project_id          TEXT NOT NULL
                        REFERENCES ags42."PROJ" ("PROJ_ID") ON DELETE CASCADE,

    filename            TEXT NOT NULL,

    -- Size in bytes and MIME type are captured at upload so the gallery can
    -- pick a renderer (img / video / iframe) without re-reading SharePoint,
    -- and so an unsupported type is rejected before it ever lands.
    content_type        TEXT,
    size_bytes          BIGINT,

    -- SharePoint identity of the uploaded item.
    sharepoint_item_id  TEXT NOT NULL,
    web_url             TEXT NOT NULL,

    -- Graph's /preview returns a short-lived embeddable URL, and it is
    -- NULL for formats Graph cannot preview (Office docs, some binaries).
    -- Hence nullable: a .docx upload must not fail on a missing preview.
    preview_url         TEXT,

    -- Whether Graph produced a usable preview. Separate from preview_url
    -- being NULL for "not generated" vs "not supported".
    preview_supported   BOOLEAN NOT NULL DEFAULT FALSE,

    uploaded_by         BIGINT REFERENCES tdac.users (id),
    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The gallery lists a project's attachments newest-first.
CREATE INDEX IF NOT EXISTS ix_attachments_project
    ON tdac.attachments (project_id, uploaded_at DESC);

-- A re-upload of the same filename replaces the SharePoint item rather
-- than creating a duplicate, so keep one row per (project, item).
CREATE UNIQUE INDEX IF NOT EXISTS ux_attachments_project_item
    ON tdac.attachments (project_id, sharepoint_item_id);
