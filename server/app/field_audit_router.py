"""Admin-only Field Data audit endpoints (Field Data -> Overview)."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_admin
from app.field_data_service import loca_belongs_to_project
from app.field_audit_service import (
    list_borehole_entries,
    get_borehole_history,
    list_sample_entries,
    get_sample_history,
)


router = APIRouter(
    prefix="/api/portfolio/projects/{project_id}/locas/{loca_id}/field-data/audit",
    tags=["Field Data Audit"],
)


async def _require_loca(project_id: str, loca_id: str):
    if not await loca_belongs_to_project(project_id, loca_id):
        raise HTTPException(
            status_code=404,
            detail="This location does not belong to the selected project.",
        )


@router.get("/borehole")
async def audit_borehole_entries(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)
    return {"entries": await list_borehole_entries(project_id, loca_id)}


@router.get("/borehole/{depth_from}")
async def audit_borehole_history(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)
    result = await get_borehole_history(project_id, loca_id, depth_from)
    if result is None:
        raise HTTPException(status_code=404, detail="Borehole record not found.")
    return result


@router.get("/samples")
async def audit_sample_entries(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)
    return {"entries": await list_sample_entries(project_id, loca_id)}


@router.get("/samples/{sample_id}")
async def audit_sample_history(
    project_id: str,
    loca_id: str,
    sample_id: str,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)
    result = await get_sample_history(project_id, loca_id, sample_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sample not found.")
    return result
