"""Render a stored revision to the method's DRAFT-stamped result sheet.

The engines already ship PDF renderers that write to a path; this module
wraps them for HTTP:

* heavy imports (reportlab, matplotlib) are lazy, so the app boots without
  paying for them, exactly like borelog_report/pdf_renderer.py;
* the drawing runs in a worker thread (asyncio.to_thread) because it is
  CPU-bound, so the event loop keeps serving during a render;
* the temp file is created with delete=False so the renderer can write to
  the path, then removed in a finally block -- a crash never leaks it.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app import database
from app.lab_data_service import _fetch_project_test, _load_jsonb
from app.lab_engine import adapters

_RENDERERS = None


def _renderers():
    global _RENDERERS
    if _RENDERERS is None:
        from app.lab_engine import atterberg, grain_size, particle_density

        _RENDERERS = {
            "PSD": grain_size.render_test_pdf,
            "PARTICLE_DENSITY": particle_density.render_test_pdf,
            "ATTERBERG": atterberg.render_test_pdf,
        }
    return _RENDERERS


async def render_revision_pdf(project_id: str, test_id: str) -> bytes:
    """Recalculate from the stored raw snapshot and render it.

    Rendering is never done from a stale stored calculation: the sheet must
    show what the raw readings actually produce, which is also what the
    calculation snapshot stores. If the raw readings cannot calculate, the
    caller gets the engine's message as a ValueError (404/400 at the route).
    """
    renderers = _renderers()

    async with database.pool.acquire() as connection:
        test = await _fetch_project_test(connection, project_id, test_id)

        if test["test_type"] not in renderers:
            raise ValueError(
                "No result-sheet renderer for this test type; available for "
                + ", ".join(sorted(renderers))
                + "."
            )

        revision = await connection.fetchrow(
            """
            SELECT "raw_input_snapshot"
            FROM "lab"."test_revision"
            WHERE "test_id" = $1 AND "revision_no" = $2
            """,
            test["test_id"],
            test["current_revision"],
        )
        if revision is None:
            raise ValueError("This test has no stored revision to render.")

        method = await connection.fetchrow(
            """
            SELECT "validation_schema"
            FROM "lab"."method_definition"
            WHERE "method_definition_id" = $1
            """,
            test["method_definition_id"],
        )
        if method is None:
            # The test row carries a method_definition_id FK, so this only
            # happens if the definition was deactivated or deleted between
            # the two reads. Say so rather than TypeError on the row access.
            raise ValueError("The test method definition is missing.")

    config = _load_jsonb(method["validation_schema"]) or {}
    raw = _load_jsonb(revision["raw_input_snapshot"]) or {}

    if not raw or not (raw.get("data") or {}).get("rows"):
        raise ValueError(
            "This revision predates server-side calculation and stores no "
            "raw readings. Re-enter the readings in Results Entry to "
            "generate a result sheet."
        )

    record = adapters.engine_input(
        test["test_type"],
        raw,
        project_id=project_id,
        test_row=dict(test),
        method_config=config,
    )
    result = adapters.run_engine(test["test_type"], record)

    def _draw() -> bytes:
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pdf", delete=False
            ) as handle:
                temp = Path(handle.name)
            renderers[test["test_type"]](result, temp)
            return temp.read_bytes()
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    return await asyncio.to_thread(_draw)
