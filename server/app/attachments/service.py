"""Attachment metadata for TDAC.

SharePoint holds the bytes; PostgreSQL holds what the gallery needs to
list them without asking SharePoint on every page load: filename, type,
size, and whether a preview exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app import database

# What the gallery renders. Anything else falls back to the iframe preview.
# Membership is tested against the MIME type with its parameters stripped
# and lowercased; see classify() below.
IMAGE_TYPES = {
    "image/jpeg", "image/jpg", "image/pjpeg",
    "image/png", "image/gif", "image/webp", "image/bmp",
    "image/svg+xml", "image/tiff", "image/avif",
    # iOS camera output. Without HEIC a field crew's photos fell to the
    # generic preview path and rendered as a link instead of a thumbnail.
    "image/heic", "image/heif",
}
VIDEO_TYPES = {
    "video/mp4", "video/webm", "video/ogg", "video/quicktime",
    "video/x-msvideo", "video/x-matroska", "video/mpeg",
    "video/3gpp", "video/x-m4v",
}

# Uploads are capped to keep a phone browser from pinning memory on a
# multi-hundred-MB site video. SharePoint itself allows far more; raise
# this only alongside the upload-session limits in sharepoint_service.
MAX_UPLOAD_BYTES = 250 * 1024 * 1024

# Page sizes for the list endpoints. A project with thousands of site
# photos should not return all of them to render one screen of a gallery.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class AttachmentError(RuntimeError):
    """An attachment could not be stored."""


class AttachmentNotFound(AttachmentError):
    """No attachment with that id for this project."""


async def project_exists(project_id: str) -> bool:
    async with database.pool.acquire() as connection:
        return bool(
            await connection.fetchval(
                'SELECT 1 FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1',
                project_id,
            )
        )


def classify(content_type: Optional[str]) -> str:
    """Rendering hint for the gallery: image, video, or preview.

    A real upload sends parameters, for example
    "image/svg+xml; charset=utf-8". Comparing that string against the sets
    above missed every entry and pushed the file onto the generic preview
    path, so the parameters are stripped and the type lowercased first.
    """
    if not content_type:
        return "preview"
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in IMAGE_TYPES:
        return "image"
    if mime in VIDEO_TYPES:
        return "video"
    return "preview"


def row_to_attachment(row: Any) -> Dict[str, Any]:
    """Map a DB row to the API shape the client consumes."""
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "entity_kind": row["entity_kind"],
        "sample_id": row["sample_id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "size_bytes": row["size_bytes"],
        # kind drives which renderer the gallery picks.
        "kind": classify(row["content_type"]),
        "sharepoint_item_id": row["sharepoint_item_id"],
        "web_url": row["web_url"],
        "preview_url": row["preview_url"],
        "preview_supported": row["preview_supported"],
        "uploaded_by": row["uploaded_by"],
        "uploaded_by_username": row["uploaded_by_username"],
        "uploaded_at": row["uploaded_at"],
    }


_SELECT_COLUMNS = """
    SELECT
        a."id",
        a."project_id",
        a."filename",
        a."content_type",
        a."size_bytes",
        a."sharepoint_item_id",
        a."web_url",
        a."preview_url",
        a."preview_supported",
        a."uploaded_by",
        a."entity_kind",
        a."sample_id",
        u."username" AS "uploaded_by_username",
        a."uploaded_at"
    FROM "tdac"."attachments" a
    LEFT JOIN "tdac"."users" u ON u."id" = a."uploaded_by"
"""

# Filter and sort are separate so a single-row fetch can add its own
# predicate without landing after ORDER BY.
# Project-level listing is scoped to entity_kind='project' so sample files do
# not leak into the project header panel. That filter is what the partial
# index ix_attachments_project_only exists for.
_LIST_SQL = (
    _SELECT_COLUMNS
    + ' WHERE a."project_id" = $1 AND a."entity_kind" = \'project\''
    + ' ORDER BY a."uploaded_at" DESC, a."id" DESC'
    + ' LIMIT $2 OFFSET $3'
)

_LIST_COUNT_SQL = (
    'SELECT COUNT(*) FROM "tdac"."attachments"'
    ' WHERE "project_id" = $1 AND "entity_kind" = \'project\''
)

_SAMPLE_LIST_SQL = (
    _SELECT_COLUMNS
    + ' WHERE a."project_id" = $1 AND a."sample_id" = $2'
      ' AND a."entity_kind" = \'sample\''
    + ' ORDER BY a."uploaded_at" DESC, a."id" DESC'
    + ' LIMIT $3 OFFSET $4'
)

_SAMPLE_LIST_COUNT_SQL = (
    'SELECT COUNT(*) FROM "tdac"."attachments"'
    ' WHERE "project_id" = $1 AND "sample_id" = $2'
    '   AND "entity_kind" = \'sample\''
)

_GET_SQL = _SELECT_COLUMNS + ' WHERE a."project_id" = $1 AND a."id" = $2'


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    """Keep paging inputs sane regardless of what the caller sent."""
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    return page, page_size


async def list_attachments(
    project_id: str,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """One page of project-level attachments, newest first.

    Sample files are excluded. Paged because a project can accumulate
    thousands of site photos, and returning all of them to render one screen
    of a gallery is wasteful.
    """
    page, page_size = _clamp_page(page, page_size)
    offset = (page - 1) * page_size

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(_LIST_SQL, project_id, page_size, offset)
        total = await connection.fetchval(_LIST_COUNT_SQL, project_id)

    return {
        "items": [row_to_attachment(row) for row in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


async def sample_belongs_to_project(project_id: str, sample_id: str) -> bool:
    """True when this sample id exists in this project.

    Checked before an upload so a sample id from another project cannot be
    written into this project's folder.
    """
    async with database.pool.acquire() as connection:
        return bool(
            # A SAMPLE_ID can come from the SPT workflow
            # (tdac.SPT_RECORD_STATUS), the coring workflow
            # (tdac.SAMPLING_RECORD_ID) or the Rock workflow
            # (tdac.ROCK_RECORD). Checking only the first rejected every core
            # sample, so a photo could not be attached to one.
            await connection.fetchval(
                """
                SELECT 1 FROM "tdac"."SPT_RECORD_STATUS"
                 WHERE "PROJ_ID" = $1 AND "SAMPLE_ID" = $2
                UNION ALL
                SELECT 1 FROM "tdac"."SAMPLING_RECORD_ID"
                 WHERE "PROJ_ID" = $1 AND "SAMPLE_ID" = $2
                UNION ALL
                SELECT 1 FROM "tdac"."ROCK_RECORD"
                 WHERE "PROJ_ID" = $1 AND "SAMPLE_ID" = $2
                LIMIT 1
                """,
                project_id,
                sample_id,
            )
        )


async def list_sample_attachments(
    project_id: str,
    sample_id: str,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """One page of the files attached to a single sample."""
    page, page_size = _clamp_page(page, page_size)
    offset = (page - 1) * page_size

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            _SAMPLE_LIST_SQL, project_id, sample_id, page_size, offset
        )
        total = await connection.fetchval(
            _SAMPLE_LIST_COUNT_SQL, project_id, sample_id
        )

    return {
        "items": [row_to_attachment(row) for row in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


async def get_attachment(project_id: str, attachment_id: int) -> Dict[str, Any]:
    async with database.pool.acquire() as connection:
        row = await connection.fetchrow(
            _GET_SQL, project_id, attachment_id
        )
    if row is None:
        raise AttachmentNotFound(
            f"Attachment {attachment_id} not found for project {project_id}."
        )
    return row_to_attachment(row)


async def record_attachment(
    project_id: str,
    filename: str,
    content_type: Optional[str],
    size_bytes: int,
    item_id: str,
    web_url: str,
    preview_url: Optional[str],
    uploaded_by: int,
    entity_kind: str = "project",
    sample_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist metadata for one uploaded item.

    Re-uploading the same SharePoint item upserts rather than duplicating,
    so a replace-in-place keeps one row instead of two.
    """
    async with database.pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO "tdac"."attachments" (
                "project_id", "filename", "content_type", "size_bytes",
                "sharepoint_item_id", "web_url", "preview_url",
                "preview_supported", "uploaded_by",
                "entity_kind", "sample_id"
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT ("project_id", "sharepoint_item_id")
            DO UPDATE SET
                "filename" = EXCLUDED."filename",
                "content_type" = EXCLUDED."content_type",
                "size_bytes" = EXCLUDED."size_bytes",
                "web_url" = EXCLUDED."web_url",
                "preview_url" = EXCLUDED."preview_url",
                "preview_supported" = EXCLUDED."preview_supported",
                "uploaded_by" = EXCLUDED."uploaded_by",
                "entity_kind" = EXCLUDED."entity_kind",
                "sample_id" = EXCLUDED."sample_id",
                "uploaded_at" = now()
            RETURNING "id"
            """,
            project_id,
            filename,
            content_type,
            size_bytes,
            item_id,
            web_url,
            preview_url,
            preview_url is not None,
            uploaded_by,
            entity_kind,
            sample_id,
        )
        attachment_id = row["id"]
        stored = await connection.fetchrow(
            _GET_SQL, project_id, attachment_id
        )

    return row_to_attachment(stored)


async def update_preview(
    project_id: str,
    attachment_id: int,
    preview_url: Optional[str],
    supported: bool,
) -> None:
    """Persist a freshly minted preview URL.

    Graph preview URLs expire in about an hour, so the stored one goes
    stale. This keeps the row current without re-uploading the file.
    """
    async with database.pool.acquire() as connection:
        result = await connection.execute(
            """
            UPDATE "tdac"."attachments"
            SET "preview_url" = $3, "preview_supported" = $4
            WHERE "project_id" = $1 AND "id" = $2
            """,
            project_id,
            attachment_id,
            preview_url,
            supported,
        )
        if result == "UPDATE 0":
            raise AttachmentNotFound(
                f"Attachment {attachment_id} not found for project {project_id}."
            )


async def delete_sample_attachments(
    connection, project_id: str, sample_id: str
) -> int:
    """Remove metadata rows for a sample, on a caller-supplied connection.

    Takes the connection rather than acquiring its own so the SPT delete can
    do this inside its own transaction. If the SPT delete succeeded and this
    cleanup was left to a separate call, a failure would orphan metadata
    pointing at a record that no longer exists.
    """
    result = await connection.execute(
        'DELETE FROM "tdac"."attachments"'
        ' WHERE "project_id" = $1 AND "sample_id" = $2'
        '   AND "entity_kind" = \'sample\'',
        project_id,
        sample_id,
    )
    # asyncpg returns a status string like "DELETE 2".
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


async def delete_attachment(project_id: str, attachment_id: int) -> None:
    """Remove the metadata row.

    Deliberately does not delete the SharePoint item. That is a
    destructive act on the client's document store, and a mis-click should
    not remove a site photo the crew may still need. The orphaned file stays
    in the project folder and can be cleaned up deliberately later.
    """
    async with database.pool.acquire() as connection:
        result = await connection.execute(
            'DELETE FROM "tdac"."attachments" WHERE "project_id" = $1 AND "id" = $2',
            project_id,
            attachment_id,
        )
        if result == "DELETE 0":
            raise AttachmentNotFound(
                f"Attachment {attachment_id} not found for project {project_id}."
            )
