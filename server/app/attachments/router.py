"""HTTP surface for project attachments.

Access is role-based, matching TDAC everywhere else: any authenticated user
who can open a project can list, preview and add attachments to it. There
is no per-user project scoping in TDAC and this router does not invent one.

Files stream to SharePoint; only metadata is stored in PostgreSQL. Uploaded
bytes are held in memory for the request, so the size cap in
attachments.service is the real guard against a phone browser being pinned.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse

from app.attachments import service
from app.attachments.sharepoint_client import (
    SharePointError,
    SharePointNotConfigured,
    is_configured,
    sharepoint,
)
from app.auth.dependencies import get_current_user, get_current_user_for_media
from app.auth.security import create_media_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/attachments", tags=["Attachments"])

# SharePoint forbids these in a file name. Rejecting here gives a clear
# 400 instead of an opaque Graph failure, and stops path-shaped names from
# reaching the drive API.
_ILLEGAL_FILENAME = re.compile(r'[\\/:*?"<>|]')

# SharePoint caps the path length, not just the name. A bare cleaned[:200]
# would strip ".xlsx" / ".pdf" / ".docx", leaving a file with no format and
# the browser unable to pick a viewer.
_MAX_FILENAME_LEN = 200


def _safe_filename(filename: Optional[str]) -> str:
    """Reject unusable names rather than letting Graph fail obscurely."""
    if not filename or not filename.strip():
        raise HTTPException(
            status_code=400, detail="The uploaded file has no name."
        )

    # _ILLEGAL_FILENAME already replaces every separator with "_", so no
    # path structure survives this point: a name like "../../etc/passwd"
    # becomes ".._.._etc_passwd". Trailing dots and spaces are stripped too,
    # because SharePoint rejects them.
    cleaned = _ILLEGAL_FILENAME.sub("_", filename.strip()).rstrip(". ")

    # SharePoint rejects a name that is only dots. A leading dot is kept,
    # because that is what makes ".env" a hidden file rather than "env".
    if not cleaned.strip("."):
        raise HTTPException(
            status_code=400, detail="The uploaded file name is not usable."
        )

    if not cleaned:
        raise HTTPException(
            status_code=400, detail="The uploaded file name is not usable."
        )

    if len(cleaned) <= _MAX_FILENAME_LEN:
        return cleaned

    # Split the extension off, truncate the stem to fit, reattach.
    stem, dot, ext = cleaned.rpartition(".")
    if not dot or not stem:
        # No extension, or a dotfile like ".gitignore" whose only dot is at
        # position 0. Truncate as-is rather than treat the whole name as an
        # extension.
        return cleaned[:_MAX_FILENAME_LEN]

    keep = _MAX_FILENAME_LEN - len(ext) - 1
    if keep <= 0:
        # The extension alone is at or over the cap; keep it and drop the
        # stem rather than truncate the extension.
        return cleaned[-_MAX_FILENAME_LEN:]
    return f"{stem[:keep]}.{ext}"


@router.get("/health")
async def sharepoint_health(
    current_user: dict = Depends(get_current_user),
):
    """Report whether SharePoint is wired, without leaking any secret.

    The frontend uses this to show a clear message instead of failing an
    upload with an opaque 500.
    """
    return {"configured": is_configured()}


@router.get("/{project_id}")
async def list_attachments(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(
        service.DEFAULT_PAGE_SIZE, ge=1, le=service.MAX_PAGE_SIZE
    ),
    current_user: dict = Depends(get_current_user),
):
    """All attachments for a project, newest first."""
    if not await service.project_exists(project_id):
        raise HTTPException(
            status_code=404, detail="Project not found."
        )
    # "attachments" must be the list itself, not the pager dict.
    # service.list_attachments returns {items, total, page, page_size} and
    # that object was passed straight through, so the client received an
    # object where it expected an array: .length was undefined and .map
    # threw during render, which blanked the whole page.
    # The sample route already unwrapped it; both scopes now agree, and the
    # pager fields are still exposed alongside.
    result = await service.list_attachments(
        project_id, page=page, page_size=page_size
    )
    return {
        "project_id": project_id,
        "attachments": result["items"],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


@router.get("/{project_id}/media-token")
async def issue_media_token(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Mint a short-lived token a media element can use.

    An <img> or <video> cannot send an Authorization header. The panel
    fetches this token with apiClient (which can send the header) and puts
    it in the src URL, so the browser's own request for the bytes
    authenticates without one.

    The token is typed `media`, lives for minutes, and grants nothing by
    itself: the content route still resolves the user and checks the
    project.
    """
    return {
        "media_token": create_media_token(current_user["id"]),
        "expires_in": 60 * 5,
    }


@router.get("/{project_id}/{attachment_id}")
async def get_attachment(
    project_id: str,
    attachment_id: int,
    current_user: dict = Depends(get_current_user),
):
    """One attachment's metadata, including its preview link."""
    try:
        return await service.get_attachment(project_id, attachment_id)
    except service.AttachmentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


async def _file_chunks(file: UploadFile, chunk_size: int = 1024 * 1024):
    """Yield the upload body a megabyte at a time.

    Used by the streaming path so a large file is forwarded to Graph as it
    arrives rather than being assembled in this process first.
    """
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        yield chunk


async def _store_attachment(
    project_id: str,
    file: UploadFile,
    current_user: dict,
    folder: str,
    entity_kind: str,
    sample_id: str | None,
) -> dict:
    """Validate, upload and record one file. Shared by both scopes.

    folder is the SharePoint path relative to the drive root, so the project
    scope passes "TDAC-1" and a sample passes "TDAC-1/samples/TDAC-1-16".
    One implementation means the size cap, filename hygiene and error mapping
    cannot drift between the two.
    """
    # Existence first: a bad project or sample id is our data being wrong,
    # and reporting "SharePoint is not configured" for it would send the
    # caller down the wrong path on a server that is correctly configured.
    if not await service.project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")

    if sample_id and not await service.sample_belongs_to_project(
        project_id, sample_id
    ):
        # Same 404 as an unknown project: do not confirm that a sample id
        # exists in some other project.
        raise HTTPException(
            status_code=404, detail="Sample not found in this project."
        )

    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "SharePoint is not configured. Set AZURE_CLIENT_ID, "
                "AZURE_CLIENT_SECRET, AZURE_TENANT_ID, SHAREPOINT_SITE_ID "
                "and SHAREPOINT_DRIVE_ID on the server."
            ),
        )

    filename = _safe_filename(file.filename)
    limit_mb = service.MAX_UPLOAD_BYTES // (1024 * 1024)

    # Cap before reading: an oversized Content-Length is rejected without
    # ever buffering the body.
    if file.size is not None and file.size > service.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {limit_mb} MB limit.",
        )

    content_type = file.content_type or "application/octet-stream"

    try:
        if file.size is not None:
            if file.size > service.MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File is larger than the {limit_mb} MB limit.",
                )

            # Content-Length is known, so the body is forwarded chunk by
            # chunk and never held whole. A 250 MB video would otherwise
            # occupy 250 MB of this process before the first Graph call.
            if file.size == 0:
                raise HTTPException(
                    status_code=400,
                    detail="The uploaded file is empty.",
                )
            item = await sharepoint.upload_stream(
                folder,
                filename,
                _file_chunks(file),
                file.size,
                content_type,
            )
            size_bytes = file.size
        else:
            # No Content-Length: rare, but the cap has to be enforced while
            # reading rather than after, or the body is unbounded.
            buffer = bytearray()
            async for chunk in _file_chunks(file):
                buffer.extend(chunk)
                if len(buffer) > service.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than the {limit_mb} MB limit.",
                    )
            if not buffer:
                raise HTTPException(
                    status_code=400, detail="The uploaded file is empty."
                )
            item = await sharepoint.upload(
                folder, filename, bytes(buffer), content_type
            )
            size_bytes = len(buffer)
    except SharePointNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except SharePointError as error:
        # Graph's message can be long and is client-facing; it carries no
        # secret, since _request deliberately omits the token and body.
        raise HTTPException(status_code=502, detail=str(error)) from None

    item_id = item.get("id")
    web_url = item.get("webUrl")
    if not item_id or not web_url:
        raise HTTPException(
            status_code=502,
            detail="SharePoint did not return an item id and web URL.",
        )

    # Best-effort: a format Graph cannot preview is not an upload failure.
    preview, supported = await sharepoint.preview_url(item_id)

    return await service.record_attachment(
        project_id=project_id,
        filename=filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        item_id=item_id,
        web_url=web_url,
        preview_url=preview,
        uploaded_by=current_user["id"],
        entity_kind=entity_kind,
        sample_id=sample_id,
    )


@router.post("/{project_id}", status_code=201)
async def upload_attachment(
    project_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload one file into the project's SharePoint folder.

    The project id is the folder name, so TDAC-2026-041/ holds every file
    for that project. The folder is created on first upload.
    """
    return await _store_attachment(
        project_id, file, current_user, project_id, "project", None
    )


@router.post("/{project_id}/samples/{sample_id}", status_code=201)
async def upload_sample_attachment(
    project_id: str,
    sample_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload a file against one sample.

    Folder is /{project}/samples/{sample_id}/. Anchored on SAMPLE_ID rather
    than depth because update_spt_record allows ISPT_TOP to change, which
    would orphan a depth-anchored photo.
    """
    return await _store_attachment(
        project_id,
        file,
        current_user,
        f"{project_id}/samples/{sample_id}",
        "sample",
        sample_id,
    )


@router.get("/{project_id}/samples/{sample_id}")
async def list_sample_attachments(
    project_id: str,
    sample_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(
        service.DEFAULT_PAGE_SIZE, ge=1, le=service.MAX_PAGE_SIZE
    ),
    current_user: dict = Depends(get_current_user),
):
    """Files attached to one sample, newest first."""
    if not await service.sample_belongs_to_project(project_id, sample_id):
        raise HTTPException(
            status_code=404, detail="Sample not found in this project."
        )
    result = await service.list_sample_attachments(
        project_id, sample_id, page=page, page_size=page_size
    )
    return {
        "project_id": project_id,
        "sample_id": sample_id,
        "attachments": result["items"],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }




_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_range(header: str, total: int):
    """Parse a single byte range into (start, end_inclusive).

    Returns None when the range is absent, malformed, multi-range, or
    unsatisfiable, so the caller can fall back to a full-body 200. Browsers
    accept that for video seeking.
    """
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None

    start_s, end_s = match.group(1), match.group(2)
    if not start_s and not end_s:
        return None

    if not start_s:
        # Suffix range: the last N bytes.
        n = int(end_s)
        if n <= 0:
            return None
        start, end = max(0, total - n), total - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else total - 1

    if start >= total or start > end:
        return None
    return start, min(end, total - 1)


@router.get("/{project_id}/{attachment_id}/content")
async def attachment_content(
    project_id: str,
    attachment_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_for_media),
):
    """Stream an attachment's raw bytes.

    SharePoint's webUrl and the /preview getUrl are both HTML viewer pages,
    so pointing an <img> or <video> at either yields a broken element. This
    endpoint serves the item's actual content, which is what a media element
    needs. It also keeps the file behind our auth rather than handing the
    browser a pre-authorised Graph URL.

    Authenticates by Authorization header when one is present, and
    otherwise by the short-lived `?mt=` media token, because a media element
    cannot send a header.

    HTTP Range is forwarded to Graph so a large video can be scrubbed
    without downloading it whole. The database work completes and releases
    its connection before the generator starts, so a slow download cannot
    pin a pool slot.
    """
    try:
        attachment = await service.get_attachment(project_id, attachment_id)
    except service.AttachmentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None

    media_type = attachment["content_type"] or "application/octet-stream"
    size = attachment["size_bytes"] or 0
    item_id = attachment["sharepoint_item_id"]

    # Range is an HTTP request header, not a query parameter. Reading it
    # from the query meant a browser seek never reached this handler and
    # every request returned the whole body with 200, so a large video could
    # not be scrubbed.
    range_header = request.headers.get("range")

    # Weak ETag derived from the immutable SharePoint item id and the stored
    # size. A re-request of the same image can then be answered 304 instead of
    # re-downloading the whole body through Graph.
    etag = f'"{item_id}-{size}"'

    base_headers = {
        "Accept-Ranges": "bytes",
        # private, not public: the bytes are behind per-user auth.
        "Cache-Control": "private, max-age=86400",
        "ETag": etag,
        # The media token lives in the URL, and a same-origin outbound link
        # sends the whole URL in Referer by default. Suppress it so a token
        # cannot leak to a third party through a link click.
        "Referrer-Policy": "no-referrer",
    }

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=base_headers)

    if range_header and size:
        parsed = _parse_range(range_header, size)
        if parsed is not None:
            start, end = parsed
            length = end - start + 1

            async def ranged_body():
                try:
                    async for chunk in sharepoint.iter_download(
                        item_id, range_header=f"bytes={start}-{end}"
                    ):
                        yield chunk
                except SharePointError as error:
                    # Headers are already sent, so the stream just ends. The
                    # client sees truncated media rather than a JSON error.
                    logger.warning("Attachment range stream aborted: %s", error)

            return StreamingResponse(
                ranged_body(),
                status_code=206,
                media_type=media_type,
                headers={
                    **base_headers,
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Content-Length": str(length),
                },
            )

    async def body():
        try:
            async for chunk in sharepoint.iter_download(item_id):
                yield chunk
        except SharePointError as error:
            logger.warning("Attachment stream aborted: %s", error)

    headers = dict(base_headers)
    if size:
        headers["Content-Length"] = str(size)

    return StreamingResponse(body(), media_type=media_type, headers=headers)


@router.post("/{project_id}/{attachment_id}/refresh-preview")
async def refresh_preview(
    project_id: str,
    attachment_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Mint a fresh preview URL and persist it.

    Graph preview URLs are short-lived. One stored at upload time is stale
    by the next morning, so the client refreshes on demand rather than
    showing an expired URL.
    """
    try:
        attachment = await service.get_attachment(project_id, attachment_id)
    except service.AttachmentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None

    preview, supported = await sharepoint.preview_url(
        attachment["sharepoint_item_id"]
    )

    # Persist for the next load, but never discard a URL that Graph just
    # minted: if the write fails the refresh still succeeded for this user,
    # and failing here would show "Refresh failed" while the stored URL
    # stays stale anyway.
    try:
        await service.update_preview(
            project_id, attachment_id, preview, supported
        )
    except Exception:  # noqa: BLE001 - the fresh URL is still valid
        logger.warning(
            "Could not persist refreshed preview for attachment %s",
            attachment_id,
            exc_info=True,
        )

    return {
        "id": attachment_id,
        "preview_url": preview,
        "preview_supported": supported,
    }


@router.delete("/{project_id}/{attachment_id}", status_code=204)
async def delete_attachment(
    project_id: str,
    attachment_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Remove the metadata row for an attachment.

    The SharePoint item is left in place on purpose: deleting from the
    client's document store is destructive and not something a single click
    should do. See service.delete_attachment.
    """
    try:
        await service.delete_attachment(project_id, attachment_id)
    except service.AttachmentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


