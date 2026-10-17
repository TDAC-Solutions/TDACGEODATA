"""
Admin-only Field Data audit (read side).

Nothing new is stored for the history itself: field-level changes are the
rows the edit paths in field_data_service already write to the EXISTING
tdac.audit_log (one row per changed field: field / old / new, plus who and
when from the audit_log columns).

Borehole entries have no ID column in ags42.GEOL. They are identified the
way the rest of the app already does it - (PROJ_ID, LOCA_ID, GEOL_TOP). That
depth can be edited, so each audit event records key_before / key_after and
the history of an entry is resolved by following those keys backwards.

Sample entries are identified by the existing Sample ID
(tdac.SPT_RECORD_STATUS for SPT samples, tdac.SAMPLING_RECORD_ID for coring
samples), which never changes.
"""

from decimal import Decimal

from app import database
from app.field_data_service import _norm_value


def _ts(value):
    return value.isoformat() if value is not None else None


def _change(event) -> dict:
    meta = event["meta"] or {}
    return {
        "field": meta.get("field"),
        "old_value": meta.get("old"),
        "new_value": meta.get("new"),
        "edited_by": event["username"],
        "edited_at": _ts(event["timestamp"]),
    }


async def _load_meta(connection, where: str, *args):
    import json

    rows = await connection.fetch(
        f"""
        SELECT id, "timestamp", user_id, username, role, action, meta
        FROM tdac.audit_log
        WHERE {where}
        ORDER BY "timestamp" DESC, id DESC
        """,
        *args,
    )
    out = []
    for row in rows:
        item = dict(row)
        if isinstance(item["meta"], str):
            item["meta"] = json.loads(item["meta"])
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Borehole
# ---------------------------------------------------------------------------

async def list_borehole_entries(project_id: str, loca_id: str):
    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                g."GEOL_TOP" AS depth_from,
                g."GEOL_BASE" AS depth_to,
                g."GEOL_DESC" AS soil_description,
                g."GEOL_GEOL" AS sand_clay,
                cu.username AS created_by,
                bm."CREATED_AT" AS created_at
            FROM "ags42"."GEOL" g
            LEFT JOIN "tdac"."BOREHOLE_RECORD_META" bm
                ON bm."PROJ_ID" = g."PROJ_ID"
               AND bm."LOCA_ID" = g."LOCA_ID"
               AND bm."DEPTH_FROM" = g."GEOL_TOP"
            LEFT JOIN "tdac".users cu ON cu.id = bm."CREATED_BY"
            WHERE g."PROJ_ID" = $1 AND g."LOCA_ID" = $2
            ORDER BY g."GEOL_TOP"
            """,
            project_id,
            loca_id,
        )

    return [
        {**dict(r), "created_at": _ts(r["created_at"])} for r in rows
    ]


async def get_borehole_history(project_id: str, loca_id: str, depth_from: Decimal):
    async with database.pool.acquire() as connection:
        entry = await connection.fetchrow(
            """
            SELECT
                g."GEOL_TOP" AS depth_from,
                g."GEOL_BASE" AS depth_to,
                g."GEOL_DESC" AS soil_description,
                g."GEOL_GEOL" AS sand_clay,
                cu.username AS created_by,
                bm."CREATED_AT" AS created_at
            FROM "ags42"."GEOL" g
            LEFT JOIN "tdac"."BOREHOLE_RECORD_META" bm
                ON bm."PROJ_ID" = g."PROJ_ID"
               AND bm."LOCA_ID" = g."LOCA_ID"
               AND bm."DEPTH_FROM" = g."GEOL_TOP"
            LEFT JOIN "tdac".users cu ON cu.id = bm."CREATED_BY"
            WHERE g."PROJ_ID" = $1 AND g."LOCA_ID" = $2 AND g."GEOL_TOP" = $3
            ORDER BY g."GEOL_BASE"
            LIMIT 1
            """,
            project_id,
            loca_id,
            depth_from,
        )

        if entry is None:
            return None

        events = await _load_meta(
            connection,
            "action LIKE 'BOREHOLE\\_%' "
            "AND meta->>'project_id' = $1 AND meta->>'loca_id' = $2",
            project_id,
            loca_id,
        )

    # Follow the entry's depth key backwards through its edits.
    key = _norm_value(entry["depth_from"])
    matched_batches: set = set()
    changes = []
    created_event = None

    for event in events:
        meta = event["meta"] or {}
        batch = meta.get("batch")
        action = event["action"]

        if batch is not None and batch in matched_batches:
            if action == "BOREHOLE_EDITED":
                changes.append(_change(event))
            continue

        if meta.get("key_after") != key:
            continue

        if action == "BOREHOLE_DELETED":
            break  # an earlier, deleted entry that used this depth
        if action == "BOREHOLE_CREATED":
            created_event = event
            break
        if action == "BOREHOLE_EDITED":
            changes.append(_change(event))
            if batch is not None:
                matched_batches.add(batch)
            key = meta.get("key_before") or key

    created_by = entry["created_by"]
    created_at = _ts(entry["created_at"])
    if created_by is None and created_event is not None:
        created_by = created_event["username"]
        created_at = _ts(created_event["timestamp"])

    last = changes[0] if changes else None

    return {
        "entry": {
            "depth_from": entry["depth_from"],
            "depth_to": entry["depth_to"],
            "soil_description": entry["soil_description"],
            "sand_clay": entry["sand_clay"],
        },
        "created_by": created_by,
        "created_at": created_at,
        "last_edited_by": last["edited_by"] if last else None,
        "last_edited_at": last["edited_at"] if last else None,
        "changes": changes,
        "events": [],
    }


# ---------------------------------------------------------------------------
# Sample
# ---------------------------------------------------------------------------

async def list_sample_entries(project_id: str, loca_id: str):
    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT * FROM (
                SELECT
                    sr."SAMPLE_ID" AS sample_id,
                    'SPT' AS source,
                    sr."DEPTH_FROM" AS depth_from,
                    sr."STATUS" AS status,
                    cu.username AS created_by,
                    sr."CREATED_AT" AS created_at
                FROM "tdac"."SPT_RECORD_STATUS" sr
                LEFT JOIN "tdac".users cu ON cu.id = sr."CREATED_BY"
                WHERE sr."PROJ_ID" = $1 AND sr."LOCA_ID" = $2
                UNION ALL
                SELECT
                    sri."SAMPLE_ID",
                    'CORE',
                    sri."DEPTH_FROM",
                    NULL,
                    cu.username,
                    sri."CREATED_AT"
                FROM "tdac"."SAMPLING_RECORD_ID" sri
                LEFT JOIN "tdac".users cu ON cu.id = sri."CREATED_BY"
                WHERE sri."PROJ_ID" = $1 AND sri."LOCA_ID" = $2
                UNION ALL
                SELECT
                    rr."SAMPLE_ID",
                    'ROCK',
                    rr."DEPTH_FROM",
                    rr."STATUS",
                    cu.username,
                    rr."CREATED_AT"
                FROM "tdac"."ROCK_RECORD" rr
                LEFT JOIN "tdac".users cu ON cu.id = rr."CREATED_BY"
                WHERE rr."PROJ_ID" = $1 AND rr."LOCA_ID" = $2
            ) s
            ORDER BY s.depth_from, s.sample_id
            """,
            project_id,
            loca_id,
        )

    return [{**dict(r), "created_at": _ts(r["created_at"])} for r in rows]


async def get_sample_history(project_id: str, loca_id: str, sample_id: str):
    async with database.pool.acquire() as connection:
        spt = await connection.fetchrow(
            """
            SELECT
                i."ISPT_TOP" AS depth_from,
                i."ISPT_INC1" AS blows_15,
                i."ISPT_INC2" AS blows_30,
                i."ISPT_INC3" AS blows_45,
                i."ISPT_NVAL" AS n_value,
                sr."STATUS" AS status,
                cu.username AS created_by,
                sr."CREATED_AT" AS created_at
            FROM "tdac"."SPT_RECORD_STATUS" sr
            LEFT JOIN "ags42"."ISPT" i
                ON i."PROJ_ID" = sr."PROJ_ID"
               AND i."LOCA_ID" = sr."LOCA_ID"
               AND i."ISPT_TOP" = sr."DEPTH_FROM"
            LEFT JOIN "tdac".users cu ON cu.id = sr."CREATED_BY"
            WHERE sr."PROJ_ID" = $1 AND sr."LOCA_ID" = $2 AND sr."SAMPLE_ID" = $3
            """,
            project_id,
            loca_id,
            sample_id,
        )

        source = "SPT"
        core = None
        rock = None
        if spt is None:
            rock = await connection.fetchrow(
                """
                SELECT
                    c."CORE_TOP" AS depth_from,
                    c."CORE_BASE" AS depth_to,
                    c."CORE_PREC" AS recovery,
                    c."CORE_RQD" AS rqd,
                    g."GEOL_DESC" AS rock_type,
                    rr."LIFT_NO" AS lift_no,
                    rr."STATUS" AS status,
                    cu.username AS created_by,
                    rr."CREATED_AT" AS created_at
                FROM "tdac"."ROCK_RECORD" rr
                LEFT JOIN "ags42"."CORE" c
                    ON c."PROJ_ID" = rr."PROJ_ID"
                   AND c."LOCA_ID" = rr."LOCA_ID"
                   AND c."CORE_TOP" = rr."DEPTH_FROM"
                LEFT JOIN "ags42"."GEOL" g
                    ON g."PROJ_ID" = c."PROJ_ID"
                   AND g."LOCA_ID" = c."LOCA_ID"
                   AND g."GEOL_TOP" = c."CORE_TOP"
                   AND g."GEOL_BASE" = c."CORE_BASE"
                LEFT JOIN "tdac".users cu ON cu.id = rr."CREATED_BY"
                WHERE rr."PROJ_ID" = $1 AND rr."LOCA_ID" = $2
                  AND rr."SAMPLE_ID" = $3
                """,
                project_id,
                loca_id,
                sample_id,
            )
            if rock is not None:
                source = "ROCK"

        if spt is None and rock is None:
            source = "CORE"
            core = await connection.fetchrow(
                """
                SELECT
                    c."CORE_TOP" AS depth_from,
                    c."CORE_BASE" AS depth_to,
                    geol.geol_desc AS rock_description,
                    c."CORE_PREC" AS recovery,
                    c."CORE_RQD" AS rqd,
                    c."CORE_REM" AS remark,
                    cu.username AS created_by,
                    sri."CREATED_AT" AS created_at
                FROM "tdac"."SAMPLING_RECORD_ID" sri
                LEFT JOIN "ags42"."CORE" c
                    ON c."PROJ_ID" = sri."PROJ_ID"
                   AND c."LOCA_ID" = sri."LOCA_ID"
                   AND c."CORE_TOP" = sri."DEPTH_FROM"
                LEFT JOIN LATERAL (
                    SELECT g."GEOL_DESC" AS geol_desc
                    FROM "ags42"."GEOL" g
                    WHERE g."PROJ_ID" = sri."PROJ_ID"
                      AND g."LOCA_ID" = sri."LOCA_ID"
                      AND g."GEOL_TOP" <= sri."DEPTH_FROM"
                      AND g."GEOL_BASE" > sri."DEPTH_FROM"
                    ORDER BY g."GEOL_TOP"
                    LIMIT 1
                ) geol ON TRUE
                LEFT JOIN "tdac".users cu ON cu.id = sri."CREATED_BY"
                WHERE sri."PROJ_ID" = $1 AND sri."LOCA_ID" = $2
                  AND sri."SAMPLE_ID" = $3
                """,
                project_id,
                loca_id,
                sample_id,
            )
            if core is None:
                return None

        events = await _load_meta(
            connection,
            "meta->>'sample_id' = $1 AND meta->>'project_id' = $2"
            " AND meta->>'loca_id' = $3",
            sample_id,
            project_id,
            loca_id,
        )

    base = spt if source == "SPT" else (rock if source == "ROCK" else core)
    entry = {k: v for k, v in dict(base).items() if k not in ("created_by", "created_at")}

    changes = [_change(e) for e in events if e["action"] == "SAMPLE_EDITED"]
    workflow = [
        {
            "action": e["action"],
            "by": e["username"],
            "at": _ts(e["timestamp"]),
            "detail": (e["meta"] or {}).get("reason"),
        }
        for e in events
        if e["action"] != "SAMPLE_EDITED"
    ]
    last = changes[0] if changes else None

    return {
        "sample_id": sample_id,
        "source": source,
        "entry": entry,
        "created_by": base["created_by"],
        "created_at": _ts(base["created_at"]),
        "last_edited_by": last["edited_by"] if last else None,
        "last_edited_at": last["edited_at"] if last else None,
        "changes": changes,
        "events": workflow,
    }
