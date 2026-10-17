"""Transactional persistence for one normalized CSV field table."""

from __future__ import annotations

from typing import Any, Dict

import asyncpg

from app import database
from app.spreadsheet_import.datasets import get_dataset, normalize_rows
from app.spreadsheet_import.field_service import (
    ImportConflictError,
    ProjectNotFoundError,
    _write_attribution,
)
from app.spreadsheet_import.models import FieldDataset
from app.spreadsheet_import.validation import validate_field_table


async def import_field_table_to_location(
    project_id: str,
    loca_id: str,
    dataset: FieldDataset,
    rows: list[Dict[str, Any]],
    created_by: int | None = None,
) -> Dict[str, Any]:
    """Append one validated field table to an existing location atomically."""
    # get_dataset also rejects an unknown dataset for direct callers; the
    # HTTP route's Pydantic model already makes that unreachable there.
    spec = get_dataset(dataset)
    rows = normalize_rows(dataset, rows)
    validate_field_table(dataset, rows)
    values = [spec.values(project_id, loca_id, row) for row in rows]

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            location_exists = await connection.fetchval(
                'SELECT 1 FROM "ags42"."LOCA"'
                ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
                project_id,
                loca_id,
            )
            if not location_exists:
                raise ProjectNotFoundError(
                    f"Location {loca_id} does not exist in project "
                    f"{project_id}."
                )

            if values:
                try:
                    await connection.executemany(spec.insert_sql(), values)
                except asyncpg.UniqueViolationError as error:
                    raise ImportConflictError(
                        f"One or more {dataset} rows already exist in "
                        f"location {loca_id}."
                    ) from error

                # Attribution travels in the same transaction, so a failed
                # insert cannot leave rows without an author.
                await _write_attribution(
                    connection, spec, project_id, loca_id, rows, created_by
                )

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "dataset": dataset,
        "rows": len(rows),
        "table": spec.table,
    }
