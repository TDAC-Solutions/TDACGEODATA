"""
Field-workbook database access.

Both field import flows land here (see app/spreadsheet_import/router.py):

  import_project_from_workbook -> PROJ + first LOCA + GEOL/CORE/ISPT rows
  import_loca_from_workbook    -> one extra LOCA + its GEOL/CORE/ISPT rows

Only values the application already reads are committed (see
schemas/field_data.py); the workbook's derived "thickness" / "layer average"
columns and styled empty padding rows are never stored.

  Borelog -> GEOL (GEOL_TOP, GEOL_BASE, GEOL_DESC, GEOL_GEOL)
  Rock    -> CORE (CORE_TOP, CORE_BASE, CORE_PREC, CORE_RQD, CORE_REM)
  SPT     -> ISPT (ISPT_TOP, ISPT_INC1..INC3, ISPT_NVAL)
  Info    -> PROJ (PROJ_LOC, PROJ_CLNT) + LOCA (LOCA_STAR, LOCA_ENDD,
             LOCA_FDEP, LOCA_TYPE)

Every child-table INSERT carries PROJ_ID because GEOL/CORE/ISPT enforce
NOT NULL PROJ_ID plus a composite foreign key to LOCA(PROJ_ID, LOCA_ID),
and each has a uniqueness constraint that makes ON CONFLICT DO NOTHING a
safe idempotent re-import. executemany batches each table into one network
round trip; a full input sheet is 3 statements, not 40+.
"""

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app import database
from app.field_data_service import _allocate_sample_ids
from app.spreadsheet_import.datasets import FIELD_DATASETS, DatasetSpec
from app.spreadsheet_import.validation import validate_field_workbook


class ImportConflictError(Exception):
    """The project or location already exists."""


class ProjectNotFoundError(Exception):
    """The referenced project does not exist."""


# Excel sheet rows -> AGS child-table columns live in FIELD_DATASETS
# (app.spreadsheet_import.datasets). The duplicate guard below and the
# INSERTs in _insert_field_rows both read that one registry, so the source
# and database column orders cannot drift apart.


def _cell_key(value: Any) -> tuple:
    """One comparable key per cell so DB rows and workbook rows can be
    matched regardless of which side stored them.

    Numbers normalize through Decimal so 5.8, 5.80 and 5.800 all compare
    equal — NUMERIC keeps trailing zeros, the parsed sheet does not, and
    neither is a real difference. NULL sorts apart from any value.
    """
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float, Decimal)):
        return ("num", str(Decimal(str(value)).normalize()))
    return ("text", str(value))


async def _find_duplicate_loca(
    connection, project_id: str, workbook: Dict[str, Any]
) -> Optional[str]:
    """Return the borehole id in this project already carrying exactly
    the workbook's field rows, if there is one.

    The unique constraints key on (PROJ_ID, LOCA_ID, depth), so the same
    sheet re-imported under a different borehole number inserts a full
    second copy of every layer, SPT blow and core run — the project ends
    up with two identical holes. Comparing the row multisets per table
    before writing catches that: the import is refused and the user is
    pointed at the borehole that already holds this data.
    """
    candidates: Optional[set] = None

    for spec in FIELD_DATASETS.values():
        incoming = workbook.get(spec.name) or []
        if not incoming:
            continue

        wanted = Counter(
            tuple(_cell_key(row.get(col)) for col in spec.source_columns)
            for row in incoming
        )

        rows = await connection.fetch(
            'SELECT "LOCA_ID", '
            + ", ".join(f'"{col}"' for col in spec.db_columns)
            + f' FROM "ags42"."{spec.table}" WHERE "PROJ_ID" = $1',
            project_id,
        )
        by_loca: Dict[str, Counter] = defaultdict(Counter)
        for record in rows:
            by_loca[record["LOCA_ID"]][
                tuple(_cell_key(record[col]) for col in spec.db_columns)
            ] += 1

        matches = {loca for loca, seen in by_loca.items() if seen == wanted}
        candidates = matches if candidates is None else candidates & matches

        if candidates is not None and not candidates:
            return None

    if not candidates:
        return None
    return min(candidates)



async def _insert_field_rows(connection, loca_id: str, project_id: str,
                             workbook: Dict[str, Any],
                             created_by: int | None = None) -> Dict[str, int]:
    """Insert GEOL/CORE/ISPT rows for one location. Returns row counts.

    One bulk statement per non-empty table; a full input sheet is 3 network
    round trips, not 40+. Each INSERT's SQL, column order, and bound values
    come from the shared dataset registry (see FIELD_DATASETS).
    """
    counts: Dict[str, int] = {}
    for spec in FIELD_DATASETS.values():
        rows = workbook.get(spec.name) or []
        if rows:
            await connection.executemany(
                spec.insert_sql(on_conflict=True),
                [spec.values(project_id, loca_id, row) for row in rows],
            )

            await _write_attribution(
                connection, spec, project_id, loca_id, rows, created_by
            )

        counts[spec.count_key] = len(rows)
    return counts


async def _write_attribution(
    connection,
    spec: DatasetSpec,
    project_id: str,
    loca_id: str,
    rows: List[Dict[str, Any]],
    created_by: int | None,
) -> None:
    """Record who imported each row.

    The AGS tables carry no attribution column. Each dataset has a side
    table that does - BOREHOLE_RECORD_META, SAMPLING_RECORD_ID and
    SPT_RECORD_STATUS - and the Borehole / Sampling / SPT tabs read
    created_by from there. Writing GEOL/CORE/ISPT without these left every
    imported row showing a dash under Created By.

    CORE and ISPT are keyed by SAMPLE_ID, so a Sample ID is allocated per
    row through the same tdac.SAMPLE_ID_COUNTER the manual entry path uses.
    That keeps one generator for the whole system and leaves imported SPT
    rows referenceable by the approval queue.
    """
    if spec.name == "borelog":
        await connection.executemany(
            """
            INSERT INTO "tdac"."BOREHOLE_RECORD_META"
                ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "CREATED_BY", "CREATED_AT")
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT DO NOTHING
            """,
            [
                (project_id, loca_id, row.get("depth_from"), created_by)
                for row in rows
            ],
        )
        return

    # One allocation for the whole block instead of one round trip per row.
    sample_ids = await _allocate_sample_ids(connection, project_id, len(rows))

    if spec.name == "rock_profile":
        await connection.executemany(
            """
            INSERT INTO "tdac"."SAMPLING_RECORD_ID"
                ("SAMPLE_ID", "PROJ_ID", "LOCA_ID", "DEPTH_FROM",
                 "CREATED_BY", "CREATED_AT")
            VALUES ($1, $2, $3, $4, $5, now())
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    sample_id,
                    project_id,
                    loca_id,
                    row.get("depth_from"),
                    created_by,
                )
                for sample_id, row in zip(sample_ids, rows)
            ],
        )
    elif spec.name == "spt":
        # PENDING, not APPROVED: an import is not an approval, so these must
        # still pass through the review queue.
        await connection.executemany(
            """
            INSERT INTO "tdac"."SPT_RECORD_STATUS"
                ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
                 "STATUS", "CREATED_BY", "CREATED_AT")
            VALUES ($1, $2, $3, $4, 'PENDING', $5, now())
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    project_id,
                    loca_id,
                    row.get("spt_depth"),
                    sample_id,
                    created_by,
                )
                for sample_id, row in zip(sample_ids, rows)
            ],
        )


async def import_project_from_workbook(
    project_id: str,
    project_name: str,
    project_location,
    project_client,
    consultant_name: str | None,
    contractor_name: str | None,
    borehole_id: str,
    borehole_type: str,
    start_date,
    end_date,
    final_depth,
    metadata: Dict[str, Any] | None,
    workbook: Dict[str, Any],
    created_by: int | None = None,
) -> Dict[str, Any]:
    """Create a project + its first borehole + all field rows, atomically."""
    validate_field_workbook(workbook)
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            existing = await connection.fetchval(
                'SELECT 1 FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1',
                project_id,
            )
            if existing:
                raise ImportConflictError(
                    f"Project {project_id} already exists."
                )

            await connection.execute(
                """
                INSERT INTO "ags42"."PROJ" (
                    "PROJ_ID", "PROJ_NAME", "PROJ_LOC", "PROJ_CLNT",
                    "PROJ_ENG", "PROJ_CONT"
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                project_id, project_name, project_location, project_client,
                consultant_name, contractor_name,
            )

            if metadata is not None:
                await connection.execute(
                    """
                    INSERT INTO "tdac"."PROJ_METADATA" (
                        "PROJ_ID", "ROAD_REFERENCE", "CHAINAGE_TEXT",
                        "STRUCTURE_REFERENCE", "SELECTED_BOREHOLES",
                        "PROJECT_TYPE", "REPORT_TYPE", "REPORT_TITLE",
                        "REPORT_VOLUME_TITLE", "DOCUMENT_REFERENCE",
                        "REVISION", "REPORT_DATE", "ISSUE_STATUS",
                        "TDAC_COMPANY_NAME", "GROUNDWATER_BASIS",
                        "DESIGN_STANDARD_BASIS", "FACTOR_OF_SAFETY_BASIS",
                        "LOAD_COMBINATION_BASIS",
                        "CONSTRUCTION_VERIFICATION_REQUIREMENT",
                        "PILE_LOAD_TEST_REQUIREMENT"
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18, $19, $20
                    )
                    """,
                    project_id,
                    metadata.get("road_reference"),
                    metadata.get("chainage_text"),
                    metadata.get("structure_reference"),
                    metadata.get("selected_boreholes"),
                    metadata.get("project_type"),
                    metadata.get("report_type"),
                    metadata.get("report_title"),
                    metadata.get("report_volume_title"),
                    metadata.get("document_reference"),
                    metadata.get("revision"),
                    metadata.get("report_date"),
                    metadata.get("issue_status"),
                    metadata.get("tdac_company_name"),
                    metadata.get("groundwater_basis"),
                    metadata.get("design_standard_basis"),
                    metadata.get("factor_of_safety_basis"),
                    metadata.get("load_combination_basis"),
                    metadata.get("construction_verification_requirement"),
                    metadata.get("pile_load_test_requirement"),
                )

            await connection.execute(
                """
                INSERT INTO "ags42"."LOCA" (
                    "LOCA_ID", "LOCA_TYPE", "LOCA_STAR", "LOCA_ENDD",
                    "LOCA_FDEP", "PROJ_ID"
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                borehole_id, borehole_type, start_date, end_date,
                final_depth, project_id,
            )

            counts = await _insert_field_rows(
                connection, borehole_id, project_id, workbook, created_by
            )

    return {"project_id": project_id, "borehole_id": borehole_id, **counts}


async def import_loca_from_workbook(
    project_id: str,
    borehole_id: str,
    borehole_type: str,
    start_date,
    end_date,
    final_depth,
    workbook: Dict[str, Any],
    created_by: int | None = None,
) -> Dict[str, Any]:
    """Add one location + its field rows to an existing project, atomically."""
    validate_field_workbook(workbook)
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            project_exists = await connection.fetchval(
                'SELECT 1 FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1',
                project_id,
            )
            if not project_exists:
                raise ProjectNotFoundError(
                    f"Project {project_id} does not exist."
                )

            loca_exists = await connection.fetchval(
                'SELECT 1 FROM "ags42"."LOCA"'
                ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
                project_id, borehole_id,
            )
            if loca_exists:
                raise ImportConflictError(
                    f"Location {borehole_id} already exists in project"
                    f" {project_id}."
                )

            duplicate_loca = await _find_duplicate_loca(
                connection, project_id, workbook
            )
            if duplicate_loca:
                raise ImportConflictError(
                    f"This workbook's rows are already stored under"
                    f" {duplicate_loca} in project {project_id}. Re-importing"
                    f" them as {borehole_id} would duplicate every layer,"
                    " SPT record and core run."
                )

            await connection.execute(
                """
                INSERT INTO "ags42"."LOCA" (
                    "LOCA_ID", "LOCA_TYPE", "LOCA_STAR", "LOCA_ENDD",
                    "LOCA_FDEP", "PROJ_ID"
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                borehole_id, borehole_type, start_date, end_date,
                final_depth, project_id,
            )

            counts = await _insert_field_rows(
                connection, borehole_id, project_id, workbook, created_by
            )

    return {"project_id": project_id, "borehole_id": borehole_id, **counts}
