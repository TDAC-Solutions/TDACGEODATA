"""
Field Data database access.

GEOL, ISPT, and CORE all carry both "PROJ_ID" and "LOCA_ID" columns.
Every query in this module filters directly on BOTH columns on the table
being queried/written — never on "LOCA_ID" alone — so the same "LOCA_ID"
can safely exist under different projects without records leaking across
projects.

The confirmed column mapping (see app/schemas/field_data.py) is used
exactly as specified. Nothing here invents a database column or table
that was not part of that mapping.
"""

from datetime import datetime, timezone
from decimal import Decimal

import asyncpg

from app import database
from app.attachments.service import delete_sample_attachments
from app.rock_metrics import compute_rock_metrics, pieces_to_cm


class DuplicateRecordError(Exception):
    """Raised when creating a record whose (PROJ_ID, LOCA_ID, top-depth)
    key already exists."""


class RockIntervalOverlapError(Exception):
    """A cored run that overlaps a soil stratum.

    A cored interval cannot physically sit inside a soil layer, but the Rock
    form only ever checked for a clash at the exact same top depth, so a run
    from 5 to 10 m was accepted alongside a stratum from 3 to 6.5 m. The log
    then drew the two on top of each other and the soil layer disappeared.
    """


def _compute_spt_n(blows_15, blows_30, blows_45):
    """SPTN = Below 30 + Below 45 (blows_30 + blows_45). Computed/validated
    here (not trusted from the client). It is a plain sum - never averaged
    or divided - and Below 15 is not part of it. None unless both Below 30
    and Below 45 are provided."""

    if blows_30 is None or blows_45 is None:
        return None
    return blows_30 + blows_45


async def _allocate_sample_ids(
    connection, project_id: str, count: int
) -> list[str]:
    """Allocate N contiguous sample ids in one statement.

    The single-id version costs a full INSERT ... ON CONFLICT ... RETURNING
    per row, so importing a 500-row SPT workbook issued 500 of them before a
    single attribution row was written. One statement takes the whole
    block, and the ids stay unique and contiguous within the project.
    """
    if count <= 0:
        return []

    row = await connection.fetchrow(
        """
        INSERT INTO "tdac"."SAMPLE_ID_COUNTER" ("PROJ_ID", "LAST_NUMBER")
        VALUES ($1, $2)
        ON CONFLICT ("PROJ_ID")
        DO UPDATE SET "LAST_NUMBER" =
            "tdac"."SAMPLE_ID_COUNTER"."LAST_NUMBER" + $2
        RETURNING "LAST_NUMBER"
        """,
        project_id,
        count,
    )

    end = int(row["LAST_NUMBER"])
    start = end - count + 1
    return [f"{project_id}-{n}" for n in range(start, end + 1)]


async def _allocate_sample_id(connection, project_id: str) -> str:
    """Allocate the next Sample ID number for this project using the
    existing tdac.SAMPLE_ID_COUNTER generator. Shared by Sampling/Coring
    (CORE) and SPT so there is exactly one Sample ID generator/counter in
    the system, per project (e.g. 301-1, 301-2; a different project
    starts at 1)."""

    counter_row = await connection.fetchrow(
        """
        INSERT INTO "tdac"."SAMPLE_ID_COUNTER"
            ("PROJ_ID", "LAST_NUMBER")
        VALUES ($1, 1)
        ON CONFLICT ("PROJ_ID")
        DO UPDATE
        SET "LAST_NUMBER" =
            "tdac"."SAMPLE_ID_COUNTER"."LAST_NUMBER" + 1
        RETURNING "LAST_NUMBER"
        """,
        project_id,
    )

    return f"{project_id}-{counter_row['LAST_NUMBER']}"


async def _log_audit(connection, user: dict, action: str, meta: dict):
    """Reuse the existing tdac.audit_log table for approval-workflow
    events."""

    import json

    await connection.execute(
        """
        INSERT INTO tdac.audit_log (user_id, username, role, action, meta)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """,
        user.get("id"),
        user.get("username"),
        user.get("role_name"),
        action,
        json.dumps(meta, default=str),
    )


def _norm_value(value):
    """Normalise a value for audit storage/comparison so Decimal('5.50')
    and Decimal('5.5') are the same value and JSON stays stable.

    Lists are walked because Rock pieces are audited as a list of Decimals,
    which json.dumps cannot encode on its own.
    """

    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, (list, tuple)):
        return [_norm_value(item) for item in value]
    return value


async def _log_field_changes(
    connection,
    user: dict,
    action: str,
    entity_meta: dict,
    before: dict,
    after: dict,
) -> int:
    """Write ONE existing tdac.audit_log row per changed field
    (field / old / new + who + when via the audit_log columns). All rows of
    one edit share a `batch` id. Returns the number of changed fields."""

    import uuid

    batch = uuid.uuid4().hex
    count = 0
    for field, new_raw in after.items():
        old = _norm_value(before.get(field))
        new = _norm_value(new_raw)
        if old == new:
            continue
        await _log_audit(
            connection,
            user,
            action,
            {**entity_meta, "batch": batch, "field": field, "old": old, "new": new},
        )
        count += 1
    return count


async def loca_belongs_to_project(project_id: str, loca_id: str) -> bool:
    async with database.pool.acquire() as connection:
        row = await connection.fetchval(
            """
            SELECT 1
            FROM "ags42"."LOCA"
            WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2
            """,
            project_id,
            loca_id,
        )

    return row is not None


# ---------------------------------------------------------------------------
# Borehole / Drilling  (GEOL, with Average N value derived from ISPT)
# ---------------------------------------------------------------------------

async def get_borehole_records(project_id: str, loca_id: str):
    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                g."GEOL_TOP" AS depth_from,
                g."GEOL_BASE" AS depth_to,
                g."GEOL_DESC" AS soil_description,
                g."GEOL_GEOL" AS sand_clay,
                spt_avg."avg_n_value" AS avg_n_value,
                cu.username AS created_by,
                bm."CREATED_AT" AS created_at
            FROM "ags42"."GEOL" g
            LEFT JOIN "tdac"."BOREHOLE_RECORD_META" bm
                ON bm."PROJ_ID" = g."PROJ_ID"
               AND bm."LOCA_ID" = g."LOCA_ID"
               AND bm."DEPTH_FROM" = g."GEOL_TOP"
            LEFT JOIN "tdac".users cu ON cu.id = bm."CREATED_BY"
            LEFT JOIN LATERAL (
                SELECT AVG(i."ISPT_NVAL") AS avg_n_value
                FROM "ags42"."ISPT" i
                WHERE i."PROJ_ID" = g."PROJ_ID"
                  AND i."LOCA_ID" = g."LOCA_ID"
                  AND i."ISPT_TOP" >= g."GEOL_TOP"
                  AND i."ISPT_TOP" < g."GEOL_BASE"
            ) spt_avg ON TRUE
            WHERE g."PROJ_ID" = $1
              AND g."LOCA_ID" = $2
            ORDER BY g."GEOL_TOP"
            """,
            project_id,
            loca_id,
        )

    return rows


async def create_borehole_record(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    depth_to,
    soil_description,
    sand_clay,
    user: dict | None = None,
):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            existing = await connection.fetchval(
                """
                SELECT 1
                FROM "ags42"."GEOL"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "GEOL_TOP" = $3
                """,
                project_id,
                loca_id,
                depth_from,
            )

            if existing:
                raise DuplicateRecordError(
                    f"A borehole/drilling record already exists at depth {depth_from}."
                )

            try:
                row = await connection.fetchrow(
                    """
                    INSERT INTO "ags42"."GEOL"
                        ("PROJ_ID", "LOCA_ID", "GEOL_TOP", "GEOL_BASE", "GEOL_DESC", "GEOL_GEOL")
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING
                        "GEOL_TOP" AS depth_from,
                        "GEOL_BASE" AS depth_to,
                        "GEOL_DESC" AS soil_description,
                        "GEOL_GEOL" AS sand_clay
                    """,
                    project_id,
                    loca_id,
                    depth_from,
                    depth_to,
                    soil_description,
                    sand_clay,
                )
            except asyncpg.UniqueViolationError as exc:
                raise DuplicateRecordError(
                    f"A borehole/drilling record already exists at depth {depth_from}."
                ) from exc

            if user is not None:
                await connection.execute(
                    """
                    INSERT INTO "tdac"."BOREHOLE_RECORD_META"
                        ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "CREATED_BY", "CREATED_AT")
                    VALUES ($1, $2, $3, $4, now())
                    ON CONFLICT ("PROJ_ID", "LOCA_ID", "DEPTH_FROM")
                    DO UPDATE SET "CREATED_BY" = EXCLUDED."CREATED_BY",
                                  "CREATED_AT" = EXCLUDED."CREATED_AT"
                    """,
                    project_id,
                    loca_id,
                    depth_from,
                    user.get("id"),
                )

                await _log_audit(
                    connection,
                    user,
                    "BOREHOLE_CREATED",
                    {
                        "entity": "BOREHOLE",
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "key_before": None,
                        "key_after": _norm_value(depth_from),
                        "values": {
                            "depth_from": _norm_value(row["depth_from"]),
                            "depth_to": _norm_value(row["depth_to"]),
                            "soil_description": row["soil_description"],
                            "sand_clay": row["sand_clay"],
                        },
                    },
                )

    return row


async def update_borehole_record(
    project_id: str,
    loca_id: str,
    original_depth_from: Decimal,
    depth_from: Decimal,
    depth_to,
    soil_description,
    sand_clay,
    user: dict | None = None,
):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            before = await connection.fetchrow(
                """
                SELECT
                    "GEOL_TOP" AS depth_from,
                    "GEOL_BASE" AS depth_to,
                    "GEOL_DESC" AS soil_description,
                    "GEOL_GEOL" AS sand_clay
                FROM "ags42"."GEOL"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "GEOL_TOP" = $3
                ORDER BY "GEOL_BASE"
                LIMIT 1
                FOR UPDATE
                """,
                project_id,
                loca_id,
                original_depth_from,
            )

            if before is None:
                return None

            row = await connection.fetchrow(
                """
                UPDATE "ags42"."GEOL"
                SET
                    "GEOL_TOP" = $4,
                    "GEOL_BASE" = $5,
                    "GEOL_DESC" = $6,
                    "GEOL_GEOL" = $7
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "GEOL_TOP" = $3
                RETURNING
                    "GEOL_TOP" AS depth_from,
                    "GEOL_BASE" AS depth_to,
                    "GEOL_DESC" AS soil_description,
                    "GEOL_GEOL" AS sand_clay
                """,
                project_id,
                loca_id,
                original_depth_from,
                depth_from,
                depth_to,
                soil_description,
                sand_clay,
            )

            if row is not None and depth_from != original_depth_from:
                # Keep the "Created By" row attached to the edited depth.
                await connection.execute(
                    """
                    UPDATE "tdac"."BOREHOLE_RECORD_META"
                    SET "DEPTH_FROM" = $4
                    WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                    """,
                    project_id,
                    loca_id,
                    original_depth_from,
                    depth_from,
                )

            if row is not None and user is not None:
                await _log_field_changes(
                    connection,
                    user,
                    "BOREHOLE_EDITED",
                    {
                        "entity": "BOREHOLE",
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "key_before": _norm_value(original_depth_from),
                        "key_after": _norm_value(depth_from),
                    },
                    dict(before),
                    dict(row),
                )

    return row


async def delete_borehole_record(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    user: dict | None = None,
):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            snapshot = await connection.fetch(
                """
                SELECT
                    "GEOL_TOP" AS depth_from,
                    "GEOL_BASE" AS depth_to,
                    "GEOL_DESC" AS soil_description,
                    "GEOL_GEOL" AS sand_clay
                FROM "ags42"."GEOL"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "GEOL_TOP" = $3
                """,
                project_id,
                loca_id,
                depth_from,
            )

            result = await connection.execute(
                """
                DELETE FROM "ags42"."GEOL"
                WHERE "PROJ_ID" = $1
                  AND "LOCA_ID" = $2
                  AND "GEOL_TOP" = $3
                """,
                project_id,
                loca_id,
                depth_from,
            )

            if result != "DELETE 0":
                await connection.execute(
                    """
                    DELETE FROM "tdac"."BOREHOLE_RECORD_META"
                    WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                    """,
                    project_id,
                    loca_id,
                    depth_from,
                )

                if user is not None:
                    await _log_audit(
                        connection,
                        user,
                        "BOREHOLE_DELETED",
                        {
                            "entity": "BOREHOLE",
                            "project_id": project_id,
                            "loca_id": loca_id,
                            "key_before": _norm_value(depth_from),
                            "key_after": _norm_value(depth_from),
                            "values": [
                                {k: _norm_value(v) for k, v in dict(r).items()}
                                for r in snapshot
                            ],
                        },
                    )

    return result


# ---------------------------------------------------------------------------
# SPT (ISPT)
# ---------------------------------------------------------------------------

async def get_spt_records(project_id: str, loca_id: str):
    """Records created by the current submitter/approval workflow, with
    STATUS from tdac.SPT_RECORD_STATUS.

    SAMPLE_ID is now selected. It used to be withheld from this table, but
    it is the stable identity for a record: ISPT_TOP is editable, so anything
    anchored on depth would be orphaned by a depth correction. The UI shows
    it only as the attachment target, not as a column, so nothing the user
    read before changes.

    attachment_count is a LATERAL so each row costs one index probe into
    ix_attachments_sample rather than a correlated aggregate per row.
    """

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                i."ISPT_TOP" AS spt_depth,
                i."ISPT_INC1" AS blows_15,
                i."ISPT_INC2" AS blows_30,
                i."ISPT_INC3" AS blows_45,
                i."ISPT_NVAL" AS n_value,
                sr."STATUS" AS status,
                sr."SAMPLE_ID" AS sample_id,
                COALESCE(att.c, 0) AS attachment_count
            FROM "ags42"."ISPT" i
            LEFT JOIN "tdac"."SPT_RECORD_STATUS" sr
                ON sr."PROJ_ID" = i."PROJ_ID"
               AND sr."LOCA_ID" = i."LOCA_ID"
               AND sr."DEPTH_FROM" = i."ISPT_TOP"
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS c
                FROM "tdac"."attachments" a
                WHERE a."project_id" = i."PROJ_ID"
                  AND a."sample_id" = sr."SAMPLE_ID"
                  AND a."entity_kind" = 'sample'
            ) att ON TRUE
            WHERE i."PROJ_ID" = $1
              AND i."LOCA_ID" = $2
            ORDER BY i."ISPT_TOP"
            """,
            project_id,
            loca_id,
        )

    # List Number is the row's position in depth order. Derived here, never
    # accepted from the client, so it can never be forged by a stale
    # submission and can never disagree with the order the table is drawn in.
    return [
        {**dict(row), "list_no": index + 1}
        for index, row in enumerate(rows)
    ]


async def create_spt_records_bulk(
    project_id: str,
    loca_id: str,
    rows: list,
    user: dict,
):
    """Save only populated rows from the SPT entry grid. Blank rows never
    reach this function (the frontend filters them), so they never create
    DB records or consume a Sample ID. Each row: computes/validates SPTN
    on the backend, allocates a Sample ID from the existing project
    counter, records the creator + creation time, and starts life as
    PENDING for admin approval."""

    created = []

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            for row in rows:
                if row.spt_depth is None:
                    continue

                existing = await connection.fetchval(
                    """
                    SELECT 1
                    FROM "ags42"."ISPT"
                    WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "ISPT_TOP" = $3
                    """,
                    project_id,
                    loca_id,
                    row.spt_depth,
                )
                if existing:
                    raise DuplicateRecordError(
                        f"An SPT record already exists at depth {row.spt_depth}."
                    )

                n_value = _compute_spt_n(
                    row.blows_15, row.blows_30, row.blows_45
                )

                # The existence pre-check above does not close the race: two
                # concurrent submissions of the same depth both see nothing
                # and both insert. The second then raised a bare
                # UniqueViolationError, which surfaced as a 500 instead of
                # the 409 the caller expects, so the contract differed
                # depending on timing.
                try:
                    await connection.execute(
                        """
                        INSERT INTO "ags42"."ISPT"
                            ("PROJ_ID", "LOCA_ID", "ISPT_TOP", "ISPT_INC1", "ISPT_INC2", "ISPT_INC3", "ISPT_NVAL")
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        project_id,
                        loca_id,
                        row.spt_depth,
                        row.blows_15,
                        row.blows_30,
                        row.blows_45,
                        n_value,
                    )
                except asyncpg.UniqueViolationError as exc:
                    raise DuplicateRecordError(
                        f"An SPT record already exists at depth {row.spt_depth}."
                    ) from exc

                sample_id = await _allocate_sample_id(connection, project_id)

                # An admin's own submission IS the approval, so the record
                # starts APPROVED with the submitter stamped as approver.
                # Re-queueing it would ask the admin to rubber-stamp their own
                # entry. A non-admin's submission starts PENDING, as before.
                is_admin = user.get("role_name") == "admin"
                initial_status = "APPROVED" if is_admin else "PENDING"

                # Approver fields are computed here rather than in SQL.
                # An earlier version wrote
                #     VALUES (..., $7, CASE WHEN $7 IS NULL THEN NULL ELSE now() END)
                # which PostgreSQL rejects at PREPARE time with
                # AmbiguousParameterError "could not determine data type of
                # parameter $7": $7 would have to be bigint for APPROVED_BY and
                # untyped inside the CASE, and inference cannot reconcile the
                # two. The failure happens before any row is written, so the
                # whole submit 500s. Binding each value exactly once, with its
                # type already known from the column it lands in, avoids the
                # inference step entirely and matches every other INSERT here.
                approver_id = user.get("id") if is_admin else None
                approved_at = datetime.now(timezone.utc) if is_admin else None

                await connection.execute(
                    """
                    INSERT INTO "tdac"."SPT_RECORD_STATUS"
                        ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
                         "STATUS", "CREATED_BY", "APPROVED_BY", "APPROVED_AT")
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    project_id,
                    loca_id,
                    row.spt_depth,
                    sample_id,
                    initial_status,
                    user.get("id"),
                    approver_id,
                    approved_at,
                )

                await _log_audit(
                    connection,
                    user,
                    "SPT_SUBMITTED",
                    {
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "spt_depth": row.spt_depth,
                        "sample_id": sample_id,
                        "auto_approved": is_admin,
                    },
                )

                created.append(
                    {
                        "spt_depth": row.spt_depth,
                        "blows_15": row.blows_15,
                        "blows_30": row.blows_30,
                        "blows_45": row.blows_45,
                        "n_value": n_value,
                        "status": initial_status,
                    }
                )

    return created


async def update_spt_record(
    project_id: str,
    loca_id: str,
    original_spt_depth: Decimal,
    spt_depth: Decimal,
    blows_15,
    blows_30,
    blows_45,
    user: dict | None = None,
):
    n_value = _compute_spt_n(blows_15, blows_30, blows_45)

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            before = await connection.fetchrow(
                """
                SELECT
                    "ISPT_TOP" AS spt_depth,
                    "ISPT_INC1" AS blows_15,
                    "ISPT_INC2" AS blows_30,
                    "ISPT_INC3" AS blows_45,
                    "ISPT_NVAL" AS n_value
                FROM "ags42"."ISPT"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "ISPT_TOP" = $3
                FOR UPDATE
                """,
                project_id,
                loca_id,
                original_spt_depth,
            )

            if before is None:
                return None

            row = await connection.fetchrow(
                """
                UPDATE "ags42"."ISPT"
                SET
                    "ISPT_TOP" = $4,
                    "ISPT_INC1" = $5,
                    "ISPT_INC2" = $6,
                    "ISPT_INC3" = $7,
                    "ISPT_NVAL" = $8
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "ISPT_TOP" = $3
                RETURNING
                    "ISPT_TOP" AS spt_depth,
                    "ISPT_INC1" AS blows_15,
                    "ISPT_INC2" AS blows_30,
                    "ISPT_INC3" AS blows_45,
                    "ISPT_NVAL" AS n_value
                """,
                project_id,
                loca_id,
                original_spt_depth,
                spt_depth,
                blows_15,
                blows_30,
                blows_45,
                n_value,
            )

            # The Sample ID and the status BEFORE the edit are read here: the ID
            # keys the audit trail, and the previous status is what lets an
            # admin's own edit be recognised as a genuine approval when it
            # lifts a PENDING/REJECTED record, rather than logged as an
            # anonymous edit.
            sample_id = await connection.fetchval(
                """
                SELECT "SAMPLE_ID"
                FROM "tdac"."SPT_RECORD_STATUS"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                original_spt_depth,
            )

            previous_status = await connection.fetchval(
                """
                SELECT "STATUS"
                FROM "tdac"."SPT_RECORD_STATUS"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                original_spt_depth,
            )

            # Who edited decides what happens to the status row.
            #
            # A non-admin's edit always returns the record to PENDING: an
            # APPROVED row quietly edited by an engineer would otherwise keep
            # its stale approval and never re-enter the queue.
            #
            # An ADMIN's edit is itself the approval, so it lands APPROVED
            # with the editing admin stamped as approver. Re-queueing it would
            # ask the admin to approve their own work, which is a no-op that
            # leaves the record stuck in the queue.
            is_admin = user is not None and user.get("role_name") == "admin"

            if row is not None:
                if is_admin and user is not None:
                    await connection.execute(
                        """
                        UPDATE "tdac"."SPT_RECORD_STATUS"
                        SET "DEPTH_FROM" = $4,
                            "STATUS" = 'APPROVED',
                            "APPROVED_BY" = $5,
                            "APPROVED_AT" = now(),
                            "REJECT_REASON" = NULL
                        WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                        """,
                        project_id,
                        loca_id,
                        original_spt_depth,
                        spt_depth,
                        user.get("id"),
                    )

                    # Only a real state CHANGE is a workflow event. Editing an
                    # already-APPROVED record keeps it approved; that is an
                    # edit, not a new decision, and logging it as an approval
                    # would pad the review history with events that decided
                    # nothing.
                    if (
                        sample_id
                        and previous_status is not None
                        and previous_status != "APPROVED"
                    ):
                        await _log_audit(
                            connection,
                            user,
                            "SPT_APPROVED",
                            {
                                "project_id": project_id,
                                "loca_id": loca_id,
                                "spt_depth": spt_depth,
                                "sample_id": sample_id,
                                "reason": "admin self-edit",
                            },
                        )
                else:
                    # Clearing the decision fields keeps the status row
                    # aligned with the ISPT row (the key may have moved) and
                    # forces a fresh sign-off.
                    await connection.execute(
                        """
                        UPDATE "tdac"."SPT_RECORD_STATUS"
                        SET "DEPTH_FROM" = $4,
                            "STATUS" = 'PENDING',
                            "APPROVED_BY" = NULL,
                            "APPROVED_AT" = NULL,
                            "REJECT_REASON" = NULL
                        WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                        """,
                        project_id,
                        loca_id,
                        original_spt_depth,
                        spt_depth,
                    )

            if row is not None and user is not None and sample_id:
                await _log_field_changes(
                    connection,
                    user,
                    "SAMPLE_EDITED",
                    {
                        "entity": "SAMPLE",
                        "source": "SPT",
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "sample_id": sample_id,
                    },
                    dict(before),
                    dict(row),
                )

    return row


async def delete_spt_record(
    project_id: str,
    loca_id: str,
    spt_depth: Decimal,
    user: dict | None = None,
):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            sample_id = await connection.fetchval(
                """
                SELECT "SAMPLE_ID"
                FROM "tdac"."SPT_RECORD_STATUS"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                spt_depth,
            )

            snapshot = await connection.fetchrow(
                """
                SELECT
                    "ISPT_TOP" AS spt_depth,
                    "ISPT_INC1" AS blows_15,
                    "ISPT_INC2" AS blows_30,
                    "ISPT_INC3" AS blows_45,
                    "ISPT_NVAL" AS n_value
                FROM "ags42"."ISPT"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "ISPT_TOP" = $3
                """,
                project_id,
                loca_id,
                spt_depth,
            )

            result = await connection.execute(
                """
                DELETE FROM "ags42"."ISPT"
                WHERE "PROJ_ID" = $1
                  AND "LOCA_ID" = $2
                  AND "ISPT_TOP" = $3
                """,
                project_id,
                loca_id,
                spt_depth,
            )

            await connection.execute(
                """
                DELETE FROM "tdac"."SPT_RECORD_STATUS"
                WHERE "PROJ_ID" = $1
                  AND "LOCA_ID" = $2
                  AND "DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                spt_depth,
            )

            # Attachment metadata for this sample goes in the same
            # transaction. Doing it afterwards would mean a failure here
            # leaves metadata pointing at a record that no longer exists.
            # The SharePoint files themselves are left alone, matching the
            # project-level rule: never remove from the client's document
            # store on a single click.
            if result != "DELETE 0" and sample_id:
                await delete_sample_attachments(
                    connection, project_id, sample_id
                )

            if result != "DELETE 0" and user is not None and sample_id:
                await _log_audit(
                    connection,
                    user,
                    "SAMPLE_DELETED",
                    {
                        "entity": "SAMPLE",
                        "source": "SPT",
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "sample_id": sample_id,
                        "values": {
                            k: _norm_value(v) for k, v in dict(snapshot).items()
                        },
                    },
                )

    return result


# ---------------------------------------------------------------------------
# SPT admin approval workflow
# ---------------------------------------------------------------------------

async def get_pending_spt_records(project_id: str, loca_id: str):
    """Pending SPT rows, enriched with the author and time of the edit that
    put each row back in the queue.

    The original submitter alone is not enough for a reviewer: a row that was
    APPROVED, quietly edited, and re-queued looks identical to a fresh
    submission unless the editor is named. The LATERAL pulls the most recent
    SAMPLE_EDITED event for the row's Sample ID, which is the same audit trail
    the Audit System panel reads, so the two views can never disagree.
    """
    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                sr."SAMPLE_ID" AS sample_id,
                i."ISPT_TOP" AS spt_depth,
                i."ISPT_INC1" AS blows_15,
                i."ISPT_INC2" AS blows_30,
                i."ISPT_INC3" AS blows_45,
                i."ISPT_NVAL" AS n_value,
                sr."STATUS" AS status,
                u.username AS created_by,
                sr."CREATED_AT" AS created_at,
                last_edit.last_edited_by,
                last_edit.last_edited_at
            FROM "tdac"."SPT_RECORD_STATUS" sr
            JOIN "ags42"."ISPT" i
                ON i."PROJ_ID" = sr."PROJ_ID"
               AND i."LOCA_ID" = sr."LOCA_ID"
               AND i."ISPT_TOP" = sr."DEPTH_FROM"
            LEFT JOIN tdac.users u ON u.id = sr."CREATED_BY"
            LEFT JOIN LATERAL (
                SELECT
                    ae.username AS last_edited_by,
                    ae."timestamp" AS last_edited_at
                FROM tdac.audit_log ae
                WHERE ae.action = 'SAMPLE_EDITED'
                  AND ae.meta->>'sample_id' = sr."SAMPLE_ID"
                  AND ae.meta->>'project_id' = sr."PROJ_ID"
                  AND ae.meta->>'loca_id' = sr."LOCA_ID"
                ORDER BY ae."timestamp" DESC, ae.id DESC
                LIMIT 1
            ) last_edit ON TRUE
            WHERE sr."PROJ_ID" = $1
              AND sr."LOCA_ID" = $2
              AND sr."STATUS" = 'PENDING'
            ORDER BY sr."CREATED_AT"
            """,
            project_id,
            loca_id,
        )

    # Same derivation as the approved list: the queue is ordered by
    # CREATED_AT, so the List Number reads as "position in the queue".
    return [
        {**dict(row), "list_no": index + 1}
        for index, row in enumerate(rows)
    ]


async def approve_spt_record(project_id: str, loca_id: str, spt_depth: Decimal, admin_user: dict):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE "tdac"."SPT_RECORD_STATUS"
                SET "STATUS" = 'APPROVED',
                    "APPROVED_BY" = $4,
                    "APPROVED_AT" = now()
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                  AND "STATUS" = 'PENDING'
                RETURNING "SAMPLE_ID" AS sample_id, "STATUS" AS status
                """,
                project_id,
                loca_id,
                spt_depth,
                admin_user.get("id"),
            )

            if row is None:
                return None

            await _log_audit(
                connection,
                admin_user,
                "SPT_APPROVED",
                {
                    "project_id": project_id,
                    "loca_id": loca_id,
                    "spt_depth": spt_depth,
                    "sample_id": row["sample_id"],
                },
            )

    return row


async def reject_spt_record(project_id: str, loca_id: str, spt_depth: Decimal, admin_user: dict, reason):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE "tdac"."SPT_RECORD_STATUS"
                SET "STATUS" = 'REJECTED',
                    "APPROVED_BY" = $4,
                    "APPROVED_AT" = now(),
                    "REJECT_REASON" = $5
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                  AND "STATUS" = 'PENDING'
                RETURNING "SAMPLE_ID" AS sample_id, "STATUS" AS status
                """,
                project_id,
                loca_id,
                spt_depth,
                admin_user.get("id"),
                reason,
            )

            if row is None:
                return None

            await _log_audit(
                connection,
                admin_user,
                "SPT_REJECTED",
                {
                    "project_id": project_id,
                    "loca_id": loca_id,
                    "spt_depth": spt_depth,
                    "sample_id": row["sample_id"],
                    "reason": reason,
                },
            )

    return row


async def get_soil_records(project_id: str, loca_id: str | None = None):
    """Sampling & Coring -> Soil. SPT is the source of truth: only
    APPROVED SPT records are shown, carrying the same Sample ID that was
    generated when the row was submitted. No separate Sample ID is
    generated here.

    loca_id narrows to one location; omitting it returns the whole project,
    for the Lab Data > Sample Register. See get_sampling_records for why.
    """

    loca_filter = 'AND sr."LOCA_ID" = $2' if loca_id is not None else ""

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            f"""
            SELECT
                sr."LOCA_ID" AS loca_id,
                sr."SAMPLE_ID" AS sample_id,
                i."ISPT_TOP" AS depth_from,
                i."ISPT_INC1" AS blows_15,
                i."ISPT_INC2" AS blows_30,
                i."ISPT_INC3" AS blows_45,
                i."ISPT_NVAL" AS n_value,
                cu.username AS created_by,
                sr."CREATED_AT" AS created_at
            FROM "tdac"."SPT_RECORD_STATUS" sr
            JOIN "ags42"."ISPT" i
                ON i."PROJ_ID" = sr."PROJ_ID"
               AND i."LOCA_ID" = sr."LOCA_ID"
               AND i."ISPT_TOP" = sr."DEPTH_FROM"
            LEFT JOIN "tdac".users cu ON cu.id = sr."CREATED_BY"
            WHERE sr."PROJ_ID" = $1
              {loca_filter}
              AND sr."STATUS" = 'APPROVED'
            ORDER BY sr."LOCA_ID", i."ISPT_TOP"
            """,
            *([project_id, loca_id] if loca_id is not None else [project_id]),
        )

    return rows

# ---------------------------------------------------------------------------
# Sampling / Coring (CORE, with Rock Description derived from GEOL)
# ---------------------------------------------------------------------------

async def _resolve_rock_description(connection, project_id: str, loca_id: str, depth_from: Decimal):
    """Look up the GEOL interval (if any) that overlaps depth_from, scoped
    by PROJ_ID + LOCA_ID. Returns (geol_top, geol_desc) or (None, None)."""

    geol_row = await connection.fetchrow(
        """
        SELECT g."GEOL_TOP", g."GEOL_DESC"
        FROM "ags42"."GEOL" g
        WHERE g."PROJ_ID" = $1
          AND g."LOCA_ID" = $2
          AND g."GEOL_TOP" <= $3
          AND g."GEOL_BASE" > $3
        ORDER BY g."GEOL_TOP"
        LIMIT 1
        """,
        project_id,
        loca_id,
        depth_from,
    )

    if geol_row is None:
        return None, None

    return geol_row["GEOL_TOP"], geol_row["GEOL_DESC"]


# ---------------------------------------------------------------------------
# Rock (Field Data > Rock).
#
# Same workflow as SPT: submit -> PENDING -> admin Approve / Reject, same
# Sample ID generator, same creator/approver stamps, same audit trail.
#
#   Run Depth From -> ags42.CORE.CORE_TOP
#   Run Depth To   -> ags42.CORE.CORE_BASE
#   Recovery %     -> ags42.CORE.CORE_PREC
#   RQD            -> ags42.CORE.CORE_RQD
#   Type of Rock   -> ags42.GEOL.GEOL_DESC (interval CORE_TOP .. CORE_BASE)
#   Lift No / Length of pieces (cm) -> tdac.ROCK_RECORD (no AGS column)
#
# tdac.ROCK_RECORD is keyed (PROJ_ID, LOCA_ID, DEPTH_FROM = CORE_TOP), so
# several runs at one location are separate rows. It also holds the Sample ID
# and approval state, mirroring tdac.SPT_RECORD_STATUS.
# ---------------------------------------------------------------------------

# One Rock record = its tdac row + the CORE run + the GEOL interval the
# workflow created for it (same top AND base, so it can never pick up a
# different Borehole / Drilling interval).
_ROCK_FROM = """
            FROM "tdac"."ROCK_RECORD" rr
            JOIN "ags42"."CORE" c
                ON c."PROJ_ID" = rr."PROJ_ID"
               AND c."LOCA_ID" = rr."LOCA_ID"
               AND c."CORE_TOP" = rr."DEPTH_FROM"
            LEFT JOIN "ags42"."GEOL" g
                ON g."PROJ_ID" = c."PROJ_ID"
               AND g."LOCA_ID" = c."LOCA_ID"
               AND g."GEOL_TOP" = c."CORE_TOP"
               AND g."GEOL_BASE" = c."CORE_BASE"
"""

_ROCK_SELECT = """
                c."CORE_TOP" AS depth_from,
                c."CORE_BASE" AS depth_to,
                c."CORE_PREC" AS recovery,
                c."CORE_RQD" AS rqd,
                g."GEOL_DESC" AS rock_type,
                rr."LIFT_NO" AS lift_no
"""


async def _insert_rock_geol(
    connection,
    project_id: str,
    loca_id: str,
    depth_from,
    depth_to,
    rock_type,
    user: dict | None,
):
    """Type of Rock -> GEOL_DESC. The run becomes a geology interval, so it
    also shows in Borehole / Drilling, with Created By recorded in the same
    BOREHOLE_RECORD_META table Borehole rows use."""

    await connection.execute(
        """
        INSERT INTO "ags42"."GEOL"
            ("PROJ_ID", "LOCA_ID", "GEOL_TOP", "GEOL_BASE", "GEOL_DESC")
        VALUES ($1, $2, $3, $4, $5)
        """,
        project_id,
        loca_id,
        depth_from,
        depth_to,
        rock_type,
    )

    if user is not None:
        await connection.execute(
            """
            INSERT INTO "tdac"."BOREHOLE_RECORD_META"
                ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "CREATED_BY", "CREATED_AT")
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT ("PROJ_ID", "LOCA_ID", "DEPTH_FROM")
            DO UPDATE SET "CREATED_BY" = EXCLUDED."CREATED_BY",
                          "CREATED_AT" = EXCLUDED."CREATED_AT"
            """,
            project_id,
            loca_id,
            depth_from,
            user.get("id"),
        )


async def _replace_rock_pieces(
    connection,
    project_id: str,
    loca_id: str,
    depth_from,
    sample_id: str,
    pieces_cm: list[Decimal],
):
    """Make this run's pieces exactly `pieces_cm`, numbered from 1 in order.

    The pieces belong to the run, not to the Sample ID: they are keyed the
    same way ROCK_RECORD is, so an edit that moves the run's top depth moves
    its pieces in the same transaction and a delete can never orphan them.
    """

    await connection.execute(
        """
        DELETE FROM "tdac"."ROCK_PIECE"
        WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
        """,
        project_id,
        loca_id,
        depth_from,
    )

    if not pieces_cm:
        return

    await connection.executemany(
        """
        INSERT INTO "tdac"."ROCK_PIECE"
            ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
             "BLOCK_NO", "LENGTH_CM")
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        [
            (project_id, loca_id, depth_from, sample_id, block_no, length)
            for block_no, length in enumerate(pieces_cm, start=1)
        ],
    )


async def _get_rock_pieces(
    connection, project_id: str, loca_id: str, depth_from
) -> list[Decimal]:
    rows = await connection.fetch(
        """
        SELECT "LENGTH_CM"
        FROM "tdac"."ROCK_PIECE"
        WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
        ORDER BY "BLOCK_NO"
        """,
        project_id,
        loca_id,
        depth_from,
    )
    return [row["LENGTH_CM"] for row in rows]


async def _rock_interval_overlap(
    connection,
    project_id: str,
    loca_id: str,
    depth_from,
    depth_to,
    exclude_tops=(),
):
    """The soil stratum a cored run would sit inside, or None.

    Intervals are half-open, so 5-10 m and 10-12 m touch but do not overlap.
    `exclude_tops` drops the run's own geology row, which the Rock workflow
    writes for its own Type of Rock and which would otherwise always clash
    with itself.
    """

    return await connection.fetchrow(
        """
        SELECT "GEOL_TOP", "GEOL_BASE", "GEOL_DESC"
        FROM "ags42"."GEOL"
        WHERE "PROJ_ID" = $1
          AND "LOCA_ID" = $2
          AND "GEOL_TOP" < $4
          AND "GEOL_BASE" > $3
          AND NOT ("GEOL_TOP" = ANY($5::numeric[]))
        ORDER BY "GEOL_TOP"
        LIMIT 1
        """,
        project_id,
        loca_id,
        depth_from,
        depth_to,
        list(exclude_tops),
    )


def _overlap_message(row, depth_from, depth_to) -> str:
    description = row["GEOL_DESC"] or "an unclassified stratum"
    return (
        f"This run ({depth_from} to {depth_to} m) overlaps "
        f'{description} ({row["GEOL_TOP"]} to {row["GEOL_BASE"]} m). '
        "A cored run cannot sit inside a soil layer - adjust the depths, or "
        "remove the soil layer it covers."
    )


async def _rock_depth_taken(connection, project_id: str, loca_id: str, depth_from):
    """Name what already occupies this top depth, or None if it is free.
    CORE and GEOL are both keyed by their top depth in this app."""

    if await connection.fetchval(
        """
        SELECT 1 FROM "ags42"."CORE"
        WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "CORE_TOP" = $3
        """,
        project_id,
        loca_id,
        depth_from,
    ):
        return "A coring record"

    if await connection.fetchval(
        """
        SELECT 1 FROM "ags42"."GEOL"
        WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "GEOL_TOP" = $3
        """,
        project_id,
        loca_id,
        depth_from,
    ):
        return "A Borehole / Drilling record"

    return None


async def get_rock_records(project_id: str, loca_id: str):
    """Rock records created by the Rock workflow, with STATUS."""

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            f"""
            SELECT
                {_ROCK_SELECT},
                rr."STATUS" AS status,
                rr."SAMPLE_ID" AS sample_id,
                cu.username AS created_by,
                rr."CREATED_AT" AS created_at
            {_ROCK_FROM}
            LEFT JOIN "tdac".users cu ON cu.id = rr."CREATED_BY"
            WHERE rr."PROJ_ID" = $1
              AND rr."LOCA_ID" = $2
            ORDER BY c."CORE_TOP"
            """,
            project_id,
            loca_id,
        )

        return await _attach_rock_pieces(connection, rows, project_id, loca_id)


async def _attach_rock_pieces(connection, rows, project_id: str, loca_id: str):
    """Give each run its pieces, in Block Number order.

    One query for the whole page rather than one per row, so opening Field
    Data > Rock does not fan out into a request per run. Every caller is
    already scoped to one project and location, so those are the only extra
    keys needed.
    """

    if not rows:
        return []

    depths = [row["depth_from"] for row in rows]
    pieces = await connection.fetch(
        """
        SELECT "DEPTH_FROM", "LENGTH_CM"
        FROM "tdac"."ROCK_PIECE"
        WHERE "PROJ_ID" = $1
          AND "LOCA_ID" = $2
          AND "DEPTH_FROM" = ANY($3::numeric[])
        ORDER BY "DEPTH_FROM", "BLOCK_NO"
        """,
        project_id,
        loca_id,
        depths,
    )

    grouped: dict[Decimal, list[Decimal]] = {}
    for piece in pieces:
        grouped.setdefault(piece["DEPTH_FROM"], []).append(piece["LENGTH_CM"])

    return [
        {
            **dict(row),
            "pieces": grouped.get(row["depth_from"], []),
            "list_no": index + 1,
        }
        for index, row in enumerate(rows)
    ]


async def create_rock_records_bulk(
    project_id: str,
    loca_id: str,
    rows: list,
    user: dict,
):
    """Submit Rock runs. Each row: checks the depth is free, writes CORE +
    GEOL, allocates a Sample ID from the existing project counter, records
    creator + time, and starts PENDING for admin approval (an admin's own
    submission is the approval, exactly like SPT)."""

    created = []

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            for row in rows:
                # Derived, never submitted: a stored percentage can only ever
                # be one the pieces support.
                pieces_cm = pieces_to_cm(row.pieces, row.piece_unit)
                metrics = compute_rock_metrics(
                    pieces_cm, row.depth_from, row.depth_to
                )

                clash = await _rock_interval_overlap(
                    connection,
                    project_id,
                    loca_id,
                    row.depth_from,
                    row.depth_to,
                )
                if clash:
                    raise RockIntervalOverlapError(
                        _overlap_message(clash, row.depth_from, row.depth_to)
                    )

                taken = await _rock_depth_taken(
                    connection, project_id, loca_id, row.depth_from
                )
                if taken:
                    raise DuplicateRecordError(
                        f"{taken} already exists at depth {row.depth_from}."
                    )

                try:
                    await connection.execute(
                        """
                        INSERT INTO "ags42"."CORE"
                            ("PROJ_ID", "LOCA_ID", "CORE_TOP", "CORE_BASE",
                             "CORE_PREC", "CORE_RQD")
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        project_id,
                        loca_id,
                        row.depth_from,
                        row.depth_to,
                        metrics.recovery,
                        metrics.rqd,
                    )
                    await _insert_rock_geol(
                        connection,
                        project_id,
                        loca_id,
                        row.depth_from,
                        row.depth_to,
                        row.rock_type,
                        user,
                    )
                except asyncpg.UniqueViolationError as exc:
                    raise DuplicateRecordError(
                        f"A record already exists at depth {row.depth_from}."
                    ) from exc

                # The one shared Sample ID generator (SPT + coring + Rock).
                sample_id = await _allocate_sample_id(connection, project_id)

                is_admin = user.get("role_name") == "admin"
                initial_status = "APPROVED" if is_admin else "PENDING"
                approver_id = user.get("id") if is_admin else None
                approved_at = datetime.now(timezone.utc) if is_admin else None

                await connection.execute(
                    """
                    INSERT INTO "tdac"."ROCK_RECORD"
                        ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
                         "STATUS", "LIFT_NO",
                         "CREATED_BY", "APPROVED_BY", "APPROVED_AT")
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    project_id,
                    loca_id,
                    row.depth_from,
                    sample_id,
                    initial_status,
                    row.lift_no,
                    user.get("id"),
                    approver_id,
                    approved_at,
                )

                await _replace_rock_pieces(
                    connection,
                    project_id,
                    loca_id,
                    row.depth_from,
                    sample_id,
                    pieces_cm,
                )

                await _log_audit(
                    connection,
                    user,
                    "ROCK_SUBMITTED",
                    {
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "depth_from": row.depth_from,
                        "sample_id": sample_id,
                        "auto_approved": is_admin,
                    },
                )

                created.append(
                    {
                        "sample_id": sample_id,
                        "depth_from": row.depth_from,
                        "depth_to": row.depth_to,
                        "recovery": metrics.recovery,
                        "rqd": metrics.rqd,
                        "rock_type": row.rock_type,
                        "lift_no": row.lift_no,
                        "pieces": pieces_cm,
                        "status": initial_status,
                    }
                )

    return created


async def update_rock_record(
    project_id: str,
    loca_id: str,
    original_depth_from: Decimal,
    row,
    user: dict | None = None,
):
    """Edit a Rock run. Same status rule as SPT: a non-admin edit returns the
    record to PENDING; an admin's own edit is the approval. Every changed
    field is written to the existing audit_log as SAMPLE_EDITED."""

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            before = await connection.fetchrow(
                f"""
                SELECT
                    {_ROCK_SELECT},
                    rr."SAMPLE_ID" AS sample_id,
                    rr."STATUS" AS status
                {_ROCK_FROM}
                WHERE rr."PROJ_ID" = $1
                  AND rr."LOCA_ID" = $2
                  AND rr."DEPTH_FROM" = $3
                FOR UPDATE OF rr, c
                """,
                project_id,
                loca_id,
                original_depth_from,
            )

            if before is None:
                return None

            # Read the pieces as they stand before the rewrite, so an edit
            # audits the real old list rather than reporting them as new.
            before_pieces = await _get_rock_pieces(
                connection, project_id, loca_id, original_depth_from
            )

            # The run writes its own GEOL row for its Type of Rock, so both
            # its current and its proposed top depth are excluded from the
            # overlap check; otherwise every edit would clash with itself.
            clash = await _rock_interval_overlap(
                connection,
                project_id,
                loca_id,
                row.depth_from,
                row.depth_to,
                exclude_tops={original_depth_from, row.depth_from},
            )
            if clash:
                raise RockIntervalOverlapError(
                    _overlap_message(clash, row.depth_from, row.depth_to)
                )

            if row.depth_from != original_depth_from:
                taken = await _rock_depth_taken(
                    connection, project_id, loca_id, row.depth_from
                )
                if taken:
                    raise DuplicateRecordError(
                        f"{taken} already exists at depth {row.depth_from}."
                    )

            old_base = before["depth_to"]

            # Same rule as create: the percentages follow the pieces.
            pieces_cm = pieces_to_cm(row.pieces, row.piece_unit)
            metrics = compute_rock_metrics(
                pieces_cm, row.depth_from, row.depth_to
            )

            await connection.execute(
                """
                UPDATE "ags42"."CORE"
                SET "CORE_TOP" = $5,
                    "CORE_BASE" = $6,
                    "CORE_PREC" = $7,
                    "CORE_RQD" = $8
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2
                  AND "CORE_TOP" = $3 AND "CORE_BASE" = $4
                """,
                project_id,
                loca_id,
                original_depth_from,
                old_base,
                row.depth_from,
                row.depth_to,
                metrics.recovery,
                metrics.rqd,
            )

            # Keep the geology interval the workflow created in step with the
            # run. If someone removed it from Borehole / Drilling, restore it.
            geol_result = await connection.execute(
                """
                UPDATE "ags42"."GEOL"
                SET "GEOL_TOP" = $5,
                    "GEOL_BASE" = $6,
                    "GEOL_DESC" = $7
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2
                  AND "GEOL_TOP" = $3 AND "GEOL_BASE" = $4
                """,
                project_id,
                loca_id,
                original_depth_from,
                old_base,
                row.depth_from,
                row.depth_to,
                row.rock_type,
            )
            if geol_result == "UPDATE 0":
                await _insert_rock_geol(
                    connection,
                    project_id,
                    loca_id,
                    row.depth_from,
                    row.depth_to,
                    row.rock_type,
                    user,
                )
            elif row.depth_from != original_depth_from:
                await connection.execute(
                    """
                    UPDATE "tdac"."BOREHOLE_RECORD_META"
                    SET "DEPTH_FROM" = $4
                    WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                    """,
                    project_id,
                    loca_id,
                    original_depth_from,
                    row.depth_from,
                )

            sample_id = before["sample_id"]
            previous_status = before["status"]
            is_admin = user is not None and user.get("role_name") == "admin"

            if is_admin and user is not None:
                await connection.execute(
                    """
                    UPDATE "tdac"."ROCK_RECORD"
                    SET "DEPTH_FROM" = $4,
                        "LIFT_NO" = $5,
                        "STATUS" = 'APPROVED',
                        "APPROVED_BY" = $6,
                        "APPROVED_AT" = now(),
                        "REJECT_REASON" = NULL
                    WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                    """,
                    project_id,
                    loca_id,
                    original_depth_from,
                    row.depth_from,
                    row.lift_no,
                    user.get("id"),
                )

                # After the move, so the pieces re-key onto the new depth.
                await _replace_rock_pieces(
                    connection,
                    project_id,
                    loca_id,
                    row.depth_from,
                    sample_id,
                    pieces_cm,
                )

                if previous_status != "APPROVED":
                    await _log_audit(
                        connection,
                        user,
                        "ROCK_APPROVED",
                        {
                            "project_id": project_id,
                            "loca_id": loca_id,
                            "depth_from": row.depth_from,
                            "sample_id": sample_id,
                            "reason": "admin self-edit",
                        },
                    )
            else:
                await connection.execute(
                    """
                    UPDATE "tdac"."ROCK_RECORD"
                    SET "DEPTH_FROM" = $4,
                        "LIFT_NO" = $5,
                        "STATUS" = 'PENDING',
                        "APPROVED_BY" = NULL,
                        "APPROVED_AT" = NULL,
                        "REJECT_REASON" = NULL
                    WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                    """,
                    project_id,
                    loca_id,
                    original_depth_from,
                    row.depth_from,
                    row.lift_no,
                )

                await _replace_rock_pieces(
                    connection,
                    project_id,
                    loca_id,
                    row.depth_from,
                    sample_id,
                    pieces_cm,
                )

            after = {
                "depth_from": row.depth_from,
                "depth_to": row.depth_to,
                "recovery": metrics.recovery,
                "rqd": metrics.rqd,
                "rock_type": row.rock_type,
                "lift_no": row.lift_no,
                "pieces": pieces_cm,
            }

            if user is not None and sample_id:
                await _log_field_changes(
                    connection,
                    user,
                    "SAMPLE_EDITED",
                    {
                        "entity": "SAMPLE",
                        "source": "ROCK",
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "sample_id": sample_id,
                    },
                    {**{k: before[k] for k in after if k in before},
                     "pieces": before_pieces},
                    after,
                )

    return {**after, "sample_id": sample_id}


async def delete_rock_record(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    user: dict | None = None,
):
    """Delete a Rock run created by the Rock workflow: its CORE row, the GEOL
    interval it created, its tdac row and its attachment metadata. Legacy
    CORE rows without a tdac.ROCK_RECORD row are never touched."""

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            snapshot = await connection.fetchrow(
                f"""
                SELECT
                    {_ROCK_SELECT},
                    rr."SAMPLE_ID" AS sample_id
                {_ROCK_FROM}
                WHERE rr."PROJ_ID" = $1
                  AND rr."LOCA_ID" = $2
                  AND rr."DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                depth_from,
            )

            if snapshot is None:
                return "DELETE 0"

            sample_id = snapshot["sample_id"]

            await connection.execute(
                """
                DELETE FROM "ags42"."GEOL"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2
                  AND "GEOL_TOP" = $3 AND "GEOL_BASE" = $4
                """,
                project_id,
                loca_id,
                depth_from,
                snapshot["depth_to"],
            )
            await connection.execute(
                """
                DELETE FROM "tdac"."BOREHOLE_RECORD_META"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                depth_from,
            )
            await connection.execute(
                """
                DELETE FROM "ags42"."CORE"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2
                  AND "CORE_TOP" = $3 AND "CORE_BASE" = $4
                """,
                project_id,
                loca_id,
                depth_from,
                snapshot["depth_to"],
            )
            # Pieces first: they hang off the run and must not outlive it.
            await connection.execute(
                """
                DELETE FROM "tdac"."ROCK_PIECE"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                depth_from,
            )

            result = await connection.execute(
                """
                DELETE FROM "tdac"."ROCK_RECORD"
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                """,
                project_id,
                loca_id,
                depth_from,
            )

            if result != "DELETE 0" and sample_id:
                await delete_sample_attachments(connection, project_id, sample_id)

            if result != "DELETE 0" and user is not None and sample_id:
                await _log_audit(
                    connection,
                    user,
                    "SAMPLE_DELETED",
                    {
                        "entity": "SAMPLE",
                        "source": "ROCK",
                        "project_id": project_id,
                        "loca_id": loca_id,
                        "sample_id": sample_id,
                        "values": {
                            k: _norm_value(v)
                            for k, v in dict(snapshot).items()
                            if k != "sample_id"
                        },
                    },
                )

    return result


# ---------------------------------------------------------------------------
# Rock admin approval
# ---------------------------------------------------------------------------

async def get_pending_rock_records(project_id: str, loca_id: str):
    """Pending Rock rows with the author/time of the edit that re-queued each
    one (latest SAMPLE_EDITED audit event for its Sample ID), as for SPT."""

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            f"""
            SELECT
                rr."SAMPLE_ID" AS sample_id,
                {_ROCK_SELECT},
                rr."STATUS" AS status,
                u.username AS created_by,
                rr."CREATED_AT" AS created_at,
                last_edit.last_edited_by,
                last_edit.last_edited_at
            {_ROCK_FROM}
            LEFT JOIN tdac.users u ON u.id = rr."CREATED_BY"
            LEFT JOIN LATERAL (
                SELECT
                    ae.username AS last_edited_by,
                    ae."timestamp" AS last_edited_at
                FROM tdac.audit_log ae
                WHERE ae.action = 'SAMPLE_EDITED'
                  AND ae.meta->>'sample_id' = rr."SAMPLE_ID"
                  AND ae.meta->>'project_id' = rr."PROJ_ID"
                  AND ae.meta->>'loca_id' = rr."LOCA_ID"
                ORDER BY ae."timestamp" DESC, ae.id DESC
                LIMIT 1
            ) last_edit ON TRUE
            WHERE rr."PROJ_ID" = $1
              AND rr."LOCA_ID" = $2
              AND rr."STATUS" = 'PENDING'
            ORDER BY rr."CREATED_AT"
            """,
            project_id,
            loca_id,
        )

        return await _attach_rock_pieces(connection, rows, project_id, loca_id)


async def approve_rock_record(project_id: str, loca_id: str, depth_from: Decimal, admin_user: dict):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE "tdac"."ROCK_RECORD"
                SET "STATUS" = 'APPROVED',
                    "APPROVED_BY" = $4,
                    "APPROVED_AT" = now()
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                  AND "STATUS" = 'PENDING'
                RETURNING "SAMPLE_ID" AS sample_id, "STATUS" AS status
                """,
                project_id,
                loca_id,
                depth_from,
                admin_user.get("id"),
            )

            if row is None:
                return None

            await _log_audit(
                connection,
                admin_user,
                "ROCK_APPROVED",
                {
                    "project_id": project_id,
                    "loca_id": loca_id,
                    "depth_from": depth_from,
                    "sample_id": row["sample_id"],
                },
            )

    return row


async def reject_rock_record(project_id: str, loca_id: str, depth_from: Decimal, admin_user: dict, reason):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE "tdac"."ROCK_RECORD"
                SET "STATUS" = 'REJECTED',
                    "APPROVED_BY" = $4,
                    "APPROVED_AT" = now(),
                    "REJECT_REASON" = $5
                WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2 AND "DEPTH_FROM" = $3
                  AND "STATUS" = 'PENDING'
                RETURNING "SAMPLE_ID" AS sample_id, "STATUS" AS status
                """,
                project_id,
                loca_id,
                depth_from,
                admin_user.get("id"),
                reason,
            )

            if row is None:
                return None

            await _log_audit(
                connection,
                admin_user,
                "ROCK_REJECTED",
                {
                    "project_id": project_id,
                    "loca_id": loca_id,
                    "depth_from": depth_from,
                    "sample_id": row["sample_id"],
                    "reason": reason,
                },
            )

    return row


async def get_sampling_records(project_id: str, loca_id: str | None = None):
    """Sampling & Coring > Rock (VIEW ONLY).

    Only APPROVED records from the Field Data > Rock workflow are returned,
    with the Sample ID generated when the Rock run was submitted. Legacy CORE
    rows that did not come through the Rock workflow have no tdac.ROCK_RECORD
    row and are not listed. Nothing here creates, edits or deletes data and
    no Sample ID is generated.

    loca_id narrows to one location. Omitting it returns the whole project,
    which is what the Lab Data > Sample Register reads: it is project-scoped,
    and one query beats one request per borehole. The filter is applied in SQL
    rather than by fetching everything and discarding rows, so a filtered call
    stays as cheap as an unfiltered one.
    """

    loca_filter = 'AND rr."LOCA_ID" = $2' if loca_id is not None else ""

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            f"""
            SELECT
                rr."LOCA_ID" AS loca_id,
                c."CORE_TOP" AS depth_from,
                c."CORE_BASE" AS depth_to,
                g."GEOL_DESC" AS rock_description,
                c."CORE_PREC" AS recovery,
                c."CORE_RQD" AS rqd,
                c."CORE_REM" AS remark,
                rr."LIFT_NO" AS lift_no,
                rr."SAMPLE_ID" AS sample_id,
                cu.username AS created_by,
                rr."CREATED_AT" AS created_at
            {_ROCK_FROM}
            LEFT JOIN "tdac".users cu ON cu.id = rr."CREATED_BY"
            WHERE rr."PROJ_ID" = $1
              {loca_filter}
              AND rr."STATUS" = 'APPROVED'
            ORDER BY rr."LOCA_ID", c."CORE_TOP"
            """,
            *([project_id, loca_id] if loca_id is not None else [project_id]),
        )

    return rows



async def sync_approved_samples_to_samp(connection, project_id: str):
    """Materialise approved field samples into ags42."SAMP".

    Field Data (SPT and Rock) writes ags42.ISPT / ags42.CORE + GEOL and keeps
    its approval state in tdac.SPT_RECORD_STATUS / tdac.ROCK_RECORD; the
    spreadsheet import writes ags42.CORE plus tdac.SAMPLING_RECORD_ID.
    Nothing ever wrote ags42."SAMP" -- yet every Lab Data read (Sample
    Register, the sample picker, and lab_data_service._load_project_and_sample
    for registration) reads it. So approved samples were invisible to the
    whole laboratory, and Test Register refused every sample with "does not
    belong to this project".

    This is the missing writer. It is deliberately idempotent and cheap:
    each INSERT is guarded by NOT EXISTS on the Sample ID already generated
    by the workflow (the same id the lab key uses) and ON CONFLICT DO
    NOTHING, so it can run before any project-scoped lab read, any number of
    times, without duplicating rows. The connection is the caller's, so in
    the registration path the sync shares the registration transaction.

    SPT samples are the 45 cm drive below the recorded penetration depth,
    matching SptTest.test_depth in the borelog report. Rock and imported
    coring samples span their CORE run.
    """

    # SPT: tdac.SPT_RECORD_STATUS is the approval ledger for ags42.ISPT.
    # Imported SPT rows start PENDING and only become visible here once an
    # admin approves them through the review queue.
    await connection.execute(
        """
        INSERT INTO "ags42"."SAMP"
            ("PROJ_ID", "LOCA_ID", "SAMP_ID", "SAMP_TOP", "SAMP_BASE",
             "SAMP_REF", "SAMP_TYPE")
        SELECT
            sr."PROJ_ID",
            sr."LOCA_ID",
            sr."SAMPLE_ID",
            sr."DEPTH_FROM",
            sr."DEPTH_FROM" + 0.45,
            sr."SAMPLE_ID",
            'SPT'
        FROM "tdac"."SPT_RECORD_STATUS" sr
        WHERE sr."PROJ_ID" = $1
          AND sr."STATUS" = 'APPROVED'
          AND NOT EXISTS (
              SELECT 1 FROM "ags42"."SAMP" s
              WHERE s."PROJ_ID" = sr."PROJ_ID"
                AND s."LOCA_ID" = sr."LOCA_ID"
                AND s."SAMP_ID" = sr."SAMPLE_ID"
          )
        ON CONFLICT DO NOTHING
        """,
        project_id,
    )

    # Rock: only runs an admin approved. The CORE run supplies the span.
    await connection.execute(
        """
        INSERT INTO "ags42"."SAMP"
            ("PROJ_ID", "LOCA_ID", "SAMP_ID", "SAMP_TOP", "SAMP_BASE",
             "SAMP_REF", "SAMP_TYPE")
        SELECT
            rr."PROJ_ID",
            rr."LOCA_ID",
            rr."SAMPLE_ID",
            c."CORE_TOP",
            c."CORE_BASE",
            rr."SAMPLE_ID",
            'CORE'
        FROM "tdac"."ROCK_RECORD" rr
        JOIN "ags42"."CORE" c
            ON c."PROJ_ID" = rr."PROJ_ID"
           AND c."LOCA_ID" = rr."LOCA_ID"
           AND c."CORE_TOP" = rr."DEPTH_FROM"
        WHERE rr."PROJ_ID" = $1
          AND rr."STATUS" = 'APPROVED'
          AND NOT EXISTS (
              SELECT 1 FROM "ags42"."SAMP" s
              WHERE s."PROJ_ID" = rr."PROJ_ID"
                AND s."LOCA_ID" = rr."LOCA_ID"
                AND s."SAMP_ID" = rr."SAMPLE_ID"
          )
        ON CONFLICT DO NOTHING
        """,
        project_id,
    )

    # Imported coring samples: the spreadsheet import writes CORE +
    # SAMPLING_RECORD_ID and has no approval state at all, so these are
    # taken as logged data (the same way the Sample Register treats them
    # once a Sample ID exists). Excluding them would leave every imported
    # rock profile invisible to the laboratory, which is the exact dead end
    # this sync exists to close.
    await connection.execute(
        """
        INSERT INTO "ags42"."SAMP"
            ("PROJ_ID", "LOCA_ID", "SAMP_ID", "SAMP_TOP", "SAMP_BASE",
             "SAMP_REF", "SAMP_TYPE")
        SELECT
            sri."PROJ_ID",
            sri."LOCA_ID",
            sri."SAMPLE_ID",
            c."CORE_TOP",
            c."CORE_BASE",
            sri."SAMPLE_ID",
            'CORE'
        FROM "tdac"."SAMPLING_RECORD_ID" sri
        JOIN "ags42"."CORE" c
            ON c."PROJ_ID" = sri."PROJ_ID"
           AND c."LOCA_ID" = sri."LOCA_ID"
           AND c."CORE_TOP" = sri."DEPTH_FROM"
        WHERE sri."PROJ_ID" = $1
          AND NOT EXISTS (
              SELECT 1 FROM "ags42"."SAMP" s
              WHERE s."PROJ_ID" = sri."PROJ_ID"
                AND s."LOCA_ID" = sri."LOCA_ID"
                AND s."SAMP_ID" = sri."SAMPLE_ID"
          )
        ON CONFLICT DO NOTHING
        """,
        project_id,
    )


async def get_project_samples(project_id: str):
    async with database.pool.acquire() as connection:
        # The Lab Data sample picker is only as fresh as ags42."SAMP", so
        # pull the approval ledger's newly approved samples in first. Own
        # transaction: this path is a read, but the sync is a set of writes.
        async with connection.transaction():
            await sync_approved_samples_to_samp(connection, project_id)

        rows = await connection.fetch(
            """
            SELECT
                s."SAMP_ID" AS sample_id,
                s."LOCA_ID" AS loca_id,
                s."SAMP_REF" AS spec_ref,
                s."SAMP_TOP" AS depth_from,
                s."SAMP_BASE" AS depth_to,
                s."SAMP_TYPE" AS sample_type
            FROM "ags42"."SAMP" s
            WHERE s."PROJ_ID" = $1
            ORDER BY
                s."LOCA_ID",
                s."SAMP_TOP"
            """,
            project_id,
        )

    return rows


async def get_project_sample_tests(project_id: str):
    async with database.pool.acquire() as connection:
        # Same freshness contract as get_project_samples: the register join
        # must see samples that were approved since the last sync.
        async with connection.transaction():
            await sync_approved_samples_to_samp(connection, project_id)

        rows = await connection.fetch(
            """
            SELECT
                s."SAMP_ID" AS sample_id,
                s."LOCA_ID" AS loca_id,
                t."test_id",
                t."test_type",
                t."spec_ref",
                t."current_revision",
                t."status"
            FROM "ags42"."SAMP" s
            LEFT JOIN "lab"."test" t
                ON t."samp_id" = s."SAMP_ID"
                AND t."loca_id" = s."LOCA_ID"
            WHERE s."PROJ_ID" = $1
            ORDER BY
                s."LOCA_ID",
                s."SAMP_TOP",
                t."created_at"
            """,
            project_id,
        )

    return rows