"""The borelog report's data source: Postgres, not a workbook.

The v6 script read three sheets (`Borelog`, `SPT_Data`, `Rock profile`) plus a
`ProjectInfo` key/value block. Every one of those values already lives in the
tables this server writes to, so this module reads them directly:

    sheet                     table
    -----------------------   -----------------------------------------
    Borelog                   ags42."GEOL"
    SPT_Data                  ags42."ISPT"
    Rock profile              ags42."CORE" joined to tdac."ROCK_RECORD"
    ProjectInfo (keys)        ags42."PROJ", ags42."LOCA", ags42."WSTG",
                              tdac."PROJ_METADATA"

Nothing is invented: no default description, no fallback depth, no invented
water strike. A location with no data yields empty tuples and the report says
so.

Both cross-project filters ("PROJ_ID" *and* "LOCA_ID") appear on every query,
matching the invariant documented at the top of app/field_data_service.py -- the
same "LOCA_ID" can exist under two projects, and records must not leak.

The queries run on a single pooled connection acquired once, rather than one
acquire per statement: the report is read on every Field Data -> Overview
render, so the round trip through the pool is worth not paying four times.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from app import database
from app.borelog_report.layout import Layer, ReportData, ReportHeader, SptTest


class ReportDataNotFound(ValueError):
    """The project or the location is not there. The router turns this into a
    404 with the message intact."""


def _to_float(value: Any) -> Optional[float]:
    """NUMERIC columns arrive as Decimal; the report works in float metres."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _format_date(value: Any) -> str:
    """A date as the report prints it: dd.mm.yyyy."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%d.%m.%Y")
    return _to_text(value)


async def fetch_report_data(project_id: str, loca_id: str) -> ReportData:
    """Assemble one borehole's report from the database."""
    async with database.pool.acquire() as connection:
        project = await connection.fetchrow(
            """
            SELECT
                p."PROJ_NAME",
                p."PROJ_LOC",
                p."PROJ_CLNT",
                pm."PROJECT_TYPE"
            FROM "ags42"."PROJ" p
            LEFT JOIN "tdac"."PROJ_METADATA" pm
                ON pm."PROJ_ID" = p."PROJ_ID"
            WHERE p."PROJ_ID" = $1
            """,
            project_id,
        )
        if project is None:
            raise ReportDataNotFound(f"Project {project_id} was not found.")

        loca = await connection.fetchrow(
            """
            SELECT
                l."LOCA_ID",
                l."LOCA_FDEP",
                l."LOCA_STAR",
                l."LOCA_ENDD",
                (
                    SELECT w."WSTG_DPTH"
                    FROM "ags42"."WSTG" w
                    WHERE w."PROJ_ID" = l."PROJ_ID"
                      AND w."LOCA_ID" = l."LOCA_ID"
                    ORDER BY w."WSTG_DPTH"
                    LIMIT 1
                ) AS groundwater_depth
            FROM "ags42"."LOCA" l
            WHERE l."PROJ_ID" = $1
              AND l."LOCA_ID" = $2
            """,
            project_id,
            loca_id,
        )
        if loca is None:
            raise ReportDataNotFound(
                f"Location {loca_id} was not found in project {project_id}."
            )

        geol_rows = await connection.fetch(
            """
            SELECT
                g."GEOL_TOP"  AS depth_from,
                g."GEOL_BASE" AS depth_to,
                g."GEOL_DESC" AS description
            FROM "ags42"."GEOL" g
            WHERE g."PROJ_ID" = $1
              AND g."LOCA_ID" = $2
            ORDER BY g."GEOL_TOP", g."GEOL_BASE"
            """,
            project_id,
            loca_id,
        )

        # SPT runs. tdac.SPT_RECORD_STATUS is the approval ledger for ISPT
        # rows: every manual and imported run gets a row there (PENDING until
        # an admin approves it). Without the join the report published
        # unapproved and rejected N-values into a client-facing document.
        # Rows with no ledger row are legacy/imported values that predate the
        # approval workflow -- there is nothing to withhold for them, so they
        # stay in, matching how the Sample Register treats them.
        spt_rows = await connection.fetch(
            """
            SELECT
                i."ISPT_TOP"  AS spt_depth,
                i."ISPT_INC1" AS blows_15,
                i."ISPT_INC2" AS blows_30,
                i."ISPT_INC3" AS blows_45,
                i."ISPT_NVAL" AS n_value
            FROM "ags42"."ISPT" i
            LEFT JOIN "tdac"."SPT_RECORD_STATUS" sr
                ON sr."PROJ_ID" = i."PROJ_ID"
               AND sr."LOCA_ID" = i."LOCA_ID"
               AND sr."DEPTH_FROM" = i."ISPT_TOP"
            WHERE i."PROJ_ID" = $1
              AND i."LOCA_ID" = $2
              AND (sr."STATUS" IS NULL OR sr."STATUS" = 'APPROVED')
            ORDER BY i."ISPT_TOP"
            """,
            project_id,
            loca_id,
        )

        # Rock runs, driven by ags42.CORE so the spreadsheet import's coring
        # profile is visible too. The import writes CORE + GEOL and never a
        # tdac.ROCK_RECORD row, so an inner join on ROCK_RECORD silently
        # dropped every imported run from the report. A CORE row is included
        # when either its own ROCK_RECORD is APPROVED, or it has no
        # ROCK_RECORD at all and carries real coring measurements (legacy /
        # imported data). "Type of Rock" prefers the run's own GEOL interval;
        # when the import wrote no interval for the run, it falls back to the
        # imported GEOL interval that covers it.
        rock_rows = await connection.fetch(
            """
            SELECT
                c."CORE_TOP"  AS depth_from,
                c."CORE_BASE" AS depth_to,
                c."CORE_PREC" AS recovery,
                c."CORE_RQD"  AS rqd,
                c."CORE_REM"  AS remark,
                COALESCE(g."GEOL_DESC", cover."GEOL_DESC") AS description
            FROM "ags42"."CORE" c
            LEFT JOIN "tdac"."ROCK_RECORD" rr
                ON rr."PROJ_ID" = c."PROJ_ID"
               AND rr."LOCA_ID" = c."LOCA_ID"
               AND rr."DEPTH_FROM" = c."CORE_TOP"
            LEFT JOIN "ags42"."GEOL" g
                ON g."PROJ_ID" = c."PROJ_ID"
               AND g."LOCA_ID" = c."LOCA_ID"
               AND g."GEOL_TOP" = c."CORE_TOP"
               AND g."GEOL_BASE" = c."CORE_BASE"
            LEFT JOIN LATERAL (
                SELECT g2."GEOL_DESC"
                FROM "ags42"."GEOL" g2
                WHERE g2."PROJ_ID" = c."PROJ_ID"
                  AND g2."LOCA_ID" = c."LOCA_ID"
                  AND g2."GEOL_TOP" <= c."CORE_TOP"
                  AND g2."GEOL_BASE" >= c."CORE_BASE"
                ORDER BY g2."GEOL_TOP" DESC
                LIMIT 1
            ) cover ON true
            WHERE c."PROJ_ID" = $1
              AND c."LOCA_ID" = $2
              AND (
                  rr."STATUS" = 'APPROVED'
                  OR (
                      rr."PROJ_ID" IS NULL
                      AND (c."CORE_PREC" IS NOT NULL OR c."CORE_RQD" IS NOT NULL)
                  )
              )
            ORDER BY c."CORE_TOP", c."CORE_BASE"
            """,
            project_id,
            loca_id,
        )

    return _assemble(project, loca, geol_rows, spt_rows, rock_rows)


def _assemble(project, loca, geol_rows, spt_rows, rock_rows) -> ReportData:
    """Merge soil and rock intervals into one depth-ordered log.

    The Rock workflow writes its run as a CORE row *and* a GEOL interval, so an
    approved run also appears in `geol_rows`. Keeping both would print the same
    interval twice -- once as soil and once as rock -- so any GEOL interval that
    exactly covers an approved rock run is dropped from the soil set and
    re-emitted as the rock row the PDF draws with its solid profile bar.
    """
    rock_intervals = {
        (row["depth_from"], row["depth_to"]) for row in rock_rows if row
    }

    layers: list[Layer] = []
    for row in geol_rows:
        depth_from = _to_float(row["depth_from"])
        depth_to = _to_float(row["depth_to"])
        if depth_from is None or depth_to is None:
            continue
        if (row["depth_from"], row["depth_to"]) in rock_intervals:
            continue
        layers.append(
            Layer(
                depth_from=depth_from,
                depth_to=depth_to,
                description=_to_text(row["description"]),
            )
        )

    for row in rock_rows:
        depth_from = _to_float(row["depth_from"])
        depth_to = _to_float(row["depth_to"])
        if depth_from is None or depth_to is None:
            continue
        layers.append(
            Layer(
                depth_from=depth_from,
                depth_to=depth_to,
                description=_to_text(row["description"]),
                is_rock=True,
                recovery=_to_float(row["recovery"]),
                rqd=_to_float(row["rqd"]),
                remark=_to_text(row["remark"]),
            )
        )

    layers.sort(key=lambda layer: (layer.depth_from, layer.depth_to))

    spt = tuple(
        SptTest(
            depth=depth,
            blows_15=_to_float(row["blows_15"]),
            blows_30=_to_float(row["blows_30"]),
            blows_45=_to_float(row["blows_45"]),
            n_value=_to_float(row["n_value"]),
        )
        for row in spt_rows
        if (depth := _to_float(row["spt_depth"])) is not None
    )

    return ReportData(
        header=_header(project, loca, layers),
        layers=tuple(layers),
        spt=spt,
    )


def _header(project, loca, layers: list[Layer]) -> ReportHeader:
    """The block v6 printed above the log, read from the same tables the rest
    of the app uses.

    Termination depth is the deepest of the two recorded facts -- the deepest
    logged interval and the location's declared final depth -- because a borehole
    drilled to 30 m whose last logged layer stops at 28 m still terminated at
    30 m, and a log must not be cut short at the last stratum that happens to
    carry a description.
    """
    candidates = [layer.depth_to for layer in layers]
    declared = _to_float(loca["LOCA_FDEP"])
    if declared is not None:
        candidates.append(declared)

    termination = max(candidates) if candidates else None

    project_name = _to_text(project["PROJ_NAME"])
    project_type = _to_text(project["PROJECT_TYPE"]) or project_name

    return ReportHeader(
        project_type=project_type or "GEOTECHNICAL INVESTIGATION",
        project_location=_to_text(project["PROJ_LOC"]),
        client_name=_to_text(project["PROJ_CLNT"]),
        borehole_number=_to_text(loca["LOCA_ID"]),
        boring_type="Rotary",
        drilling_start=_format_date(loca["LOCA_STAR"]),
        drilling_completion=_format_date(loca["LOCA_ENDD"]),
        water_table=_to_float(loca["groundwater_depth"]),
        termination_depth=termination,
    )