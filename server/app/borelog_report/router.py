"""HTTP surface for the Field Data -> Overview borelog report.

Three endpoints over one data source:

    GET /api/portfolio/projects/{project_id}/locas/{loca_id}/borelog-report
        The continuous report, as JSON. No page breaks -- the client scrolls
        one table, whatever the depth.

    GET /api/portfolio/projects/{project_id}/locas/{loca_id}/borelog-report/pdf
        The same report paginated at 20 m a page, drawn by the ported v6
        renderer, plus the v6 rock-logging appendix when the hole has core
        runs to print, returned as application/pdf.

    GET /api/portfolio/projects/{project_id}/locas/{loca_id}/borelog-report/docx
        The v6 soil-profile narrative -- every stratum in order with its SPT
        result(s) and a numbered summary -- as a Word document.

All call `fetch_report_data`. None computes a display value: those all come
from `layout.py`, so the preview, the paper and the narrative are renderings of
one assembly and cannot disagree about a number.

Two deliberate performance choices, because this sits on a tab that opens on
every location:

  * `pdf_renderer` is imported on the first PDF request, not at startup.
    matplotlib is the heaviest import in the server and the preview endpoint
    must not pay for it on every page load.

  * Rendered PDFs are memoised on a fingerprint of the *data*, not on the
    project id. Editing a borehole record changes the fingerprint, so the next
    request re-renders; asking for the same report twice does not. There is no
    invalidation to get wrong, because the key is the input.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth.dependencies import get_current_user
from app.borelog_report.data_source import ReportDataNotFound, fetch_report_data
from app.borelog_report.layout import report_to_json

router = APIRouter(
    prefix="/api/portfolio/projects/{project_id}/locas/{loca_id}",
    tags=["Borelog Report"],
)

#: How many rendered PDFs to hold. A handful is plenty -- a user regenerates
#: the same report, and a bulk job over one project's boreholes walks them in
#: order, so the tail of the cache is what a loop actually uses.
_PDF_CACHE_SIZE = 8

#: Importing matplotlib costs the better part of a second and builds a font
#: cache on first use. One thread, one import, however many requests arrive.
_renderer_lock = threading.Lock()
_renderer_module: Any = None


def _renderer() -> Any:
    """The PDF renderer module, imported on first use."""
    global _renderer_module

    if _renderer_module is not None:
        return _renderer_module

    with _renderer_lock:
        if _renderer_module is None:
            from app.borelog_report import pdf_renderer

            _renderer_module = pdf_renderer

    return _renderer_module


def reset_pdf_cache() -> None:
    """Drop every memoised PDF. For tests, and for an operator who has just
    replaced the logo."""
    with _renderer_lock:
        _pdf_cache.clear()


# ---------------------------------------------------------------------------
# PDF memoisation
# ---------------------------------------------------------------------------

_pdf_cache: "OrderedDict[str, bytes]" = OrderedDict()
_pdf_cache_lock = threading.Lock()


def _fingerprint(payload: dict) -> str:
    """A key that changes exactly when the report changes.

    Keyed on the serialised payload plus the layout version, so it covers every
    input the renderer reads -- header, layers, SPT, the derived values -- and
    nothing else. Adding a field to the payload therefore invalidates the cache
    on its own, which is the property that lets this be safe.
    """
    digest = hashlib.sha256()
    digest.update(str(LAYOUT_VERSION).encode())
    digest.update(json.dumps(payload, sort_keys=True, default=str).encode())
    return digest.hexdigest()


#: Bump when the drawn output changes for unchanged input. Callers may pass
#: their own build identifier to separate deployments that share a process.
#: 2: the PDF download gained the appended rock-logging appendix pages.
LAYOUT_VERSION = 2


def _cached_pdf(key: str) -> Optional[bytes]:
    with _pdf_cache_lock:
        hit = _pdf_cache.get(key)
        if hit is not None:
            _pdf_cache.move_to_end(key)
        return hit


def _store_pdf(key: str, payload: bytes) -> None:
    with _pdf_cache_lock:
        _pdf_cache[key] = payload
        _pdf_cache.move_to_end(key)
        while len(_pdf_cache) > _PDF_CACHE_SIZE:
            _pdf_cache.popitem(last=False)


def _load_logo() -> Optional[bytes]:
    """The TDAC logo for the PDF header, if this deployment has one.

    The renderer skips a missing logo silently, exactly as the v6 script did
    when its logo path did not resolve.
    """
    from pathlib import Path

    for candidate in _logo_candidates():
        try:
            return candidate.read_bytes()
        except OSError:
            continue
    return None


def _logo_candidates():
    from pathlib import Path

    here = Path(__file__).resolve()
    # app/borelog_report/router.py -> server/assets, and the repo-level assets
    # directory, so the logo is found whether it ships with the server or sits
    # beside the project. These are FILE paths: returning the directories
    # themselves made every read_bytes() raise IsADirectoryError (an OSError,
    # so it was swallowed) and the logo never loaded.
    directories = (here.parents[2] / "assets", here.parents[3] / "assets")
    names = ("TDAC GEOTECH LOGO1.png", "tdac_logo.png", "logo.png")
    return tuple(directory / name for directory in directories for name in names)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def _require_loca(project_id: str, loca_id: str) -> None:
    """Same boundary every field-data route uses, so a location from another
    project is a 404 here too and the report is never assembled for it."""
    from app.field_data_service import loca_belongs_to_project

    if not await loca_belongs_to_project(project_id, loca_id):
        raise HTTPException(
            status_code=404,
            detail="This location does not belong to the selected project.",
        )


async def _load(project_id: str, loca_id: str):
    try:
        return await fetch_report_data(project_id, loca_id)
    except ReportDataNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


def _render_pdf(data, logo: Optional[bytes]) -> bytes:
    """The main log, plus the v6 rock-logging appendix when the hole has core
    runs worth printing.

    Runs on the router's worker thread together with the matplotlib draw, so
    the reportlab table and the pypdf join also stay off the event loop.
    """
    from app.borelog_report import rock_appendix

    main_pdf = _renderer().render_borelog_pdf(data, logo)
    return rock_appendix.render_with_appendix(main_pdf, data)


@router.get("/borelog-report")
async def borelog_report(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """The continuous report: one table, every row, no depth page break."""
    await _require_loca(project_id, loca_id)
    data = await _load(project_id, loca_id)

    payload = report_to_json(data)
    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "max_depth_per_page": payload["summary"]["max_depth_per_page"],
        "pdf_page_count": payload["summary"]["page_count"],
        **payload,
    }


@router.get("/borelog-report/pdf")
async def borelog_report_pdf(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_user),
) -> Response:
    """The report as a PDF, paginated at 20 m a page as the v6 script did."""
    await _require_loca(project_id, loca_id)
    data = await _load(project_id, loca_id)

    if not data.layers:
        raise HTTPException(
            status_code=404,
            detail="No borelog data to render for this location.",
        )

    payload = report_to_json(data)
    key = _fingerprint(payload)

    pdf_bytes = _cached_pdf(key)
    if pdf_bytes is None:
        # matplotlib is CPU-bound and not thread-safe, so it runs in a worker
        # thread: the event loop keeps serving the preview while a 3-page log
        # is being drawn.
        import asyncio

        pdf_bytes = await asyncio.to_thread(_render_pdf, data, _load_logo())
        _store_pdf(key, pdf_bytes)

    filename = f"{project_id}_{loca_id}_borelog_report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            # Project data behind a token: never let an intermediary or the
            # browser cache keep a borehole log after the user logs out.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/borelog-report/docx")
async def borelog_report_docx(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_user),
) -> Response:
    """The v6 soil-profile narrative as a Word document.

    Not memoised: building a few paragraphs is far cheaper than the cache
    lookup would be, and a Word file cannot be rendered by the browser anyway,
    so it is served as an attachment.
    """
    await _require_loca(project_id, loca_id)
    data = await _load(project_id, loca_id)

    if not data.layers:
        raise HTTPException(
            status_code=404,
            detail="No borelog data to describe for this location.",
        )

    import asyncio

    from app.borelog_report import profile_docx

    docx_bytes = await asyncio.to_thread(profile_docx.render_profile_docx, data)

    filename = f"{project_id}_{loca_id}_soil_profile.docx"
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )