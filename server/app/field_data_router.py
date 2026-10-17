from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user, get_current_admin
from app.schemas.field_data import (
    BoreholeRecordCreate,
    BoreholeRecordUpdate,
    SPTBulkCreate,
    SPTRecordUpdate,
    SPTReject,
    RockBulkCreate,
    RockRecordUpdate,
    RockReject,
)
from app.field_data_service import (
    DuplicateRecordError,
    RockIntervalOverlapError,
    loca_belongs_to_project,
    get_borehole_records,
    create_borehole_record,
    update_borehole_record,
    get_spt_records,
    create_spt_records_bulk,
    update_spt_record,
    delete_spt_record,
    get_pending_spt_records,
    approve_spt_record,
    reject_spt_record,
    get_rock_records,
    create_rock_records_bulk,
    update_rock_record,
    delete_rock_record,
    get_pending_rock_records,
    approve_rock_record,
    reject_rock_record,
    get_project_samples,
    delete_borehole_record,
)


router = APIRouter(
    prefix="/api/portfolio/projects/{project_id}/locas/{loca_id}/field-data",
    tags=["Field Data"],
)


async def _require_loca(project_id: str, loca_id: str):
    if not await loca_belongs_to_project(project_id, loca_id):
        raise HTTPException(
            status_code=404,
            detail="This location does not belong to the selected project.",
        )


# ---------------------------------------------------------------------------
# Borehole / Drilling
# ---------------------------------------------------------------------------

@router.get("/borehole")
async def borehole_records(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    rows = await get_borehole_records(project_id, loca_id)

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "records": [
            {
                "depth_from": row["depth_from"],
                "depth_to": row["depth_to"],
                "soil_description": row["soil_description"],
                "sand_clay": row["sand_clay"],
                "avg_n_value": (
                    # AVG(Numeric) is already exact; float() would only
                    # re-introduce binary error on an average of clean
                    # decimals (e.g. 5.5, 5.5 -> 5.5). Keep the Decimal.
                    row["avg_n_value"]
                    if row["avg_n_value"] is not None
                    else None
                ),
                "created_by": row["created_by"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


@router.post("/borehole", status_code=201)
async def add_borehole(
    project_id: str,
    loca_id: str,
    payload: BoreholeRecordCreate,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    try:
        created = await create_borehole_record(
            project_id=project_id,
            loca_id=loca_id,
            depth_from=payload.depth_from,
            depth_to=payload.depth_to,
            soil_description=payload.soil_description,
            sand_clay=payload.sand_clay,
            user=current_user,
        )
    except DuplicateRecordError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "message": "Borehole record created successfully",
        "record": {
            "depth_from": created["depth_from"],
            "depth_to": created["depth_to"],
            "soil_description": created["soil_description"],
            "sand_clay": created["sand_clay"],
            "avg_n_value": None,
            "created_by": current_user.get("username"),
        },
    }


@router.patch("/borehole/{depth_from}")
async def update_borehole(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    payload: BoreholeRecordUpdate,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    updated = await update_borehole_record(
        project_id=project_id,
        loca_id=loca_id,
        original_depth_from=depth_from,
        depth_from=payload.depth_from,
        depth_to=payload.depth_to,
        soil_description=payload.soil_description,
        sand_clay=payload.sand_clay,
        user=current_user,
    )

    if updated is None:
        raise HTTPException(status_code=404, detail="Borehole record not found.")

    return {
        "message": "Borehole record updated successfully",
        "record": {
            "depth_from": updated["depth_from"],
            "depth_to": updated["depth_to"],
            "soil_description": updated["soil_description"],
            "sand_clay": updated["sand_clay"],
        },
    }

@router.delete("/borehole/{depth_from}")
async def delete_borehole(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    result = await delete_borehole_record(
        project_id=project_id,
        loca_id=loca_id,
        depth_from=depth_from,
        user=current_user,
    )

    if result == "DELETE 0":
        raise HTTPException(
            status_code=404,
            detail="Borehole record not found.",
        )

    return {
        "message": "Borehole record deleted successfully",
    }

# ---------------------------------------------------------------------------
# SPT
# ---------------------------------------------------------------------------

@router.get("/spt")
async def spt_records(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    rows = await get_spt_records(project_id, loca_id)

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "records": [
            {
                "spt_depth": row["spt_depth"],
                "blows_15": row["blows_15"],
                "blows_30": row["blows_30"],
                "blows_45": row["blows_45"],
                "n_value": row["n_value"],
                "status": row["status"],
                # The attachment anchor. Stable across depth corrections,
                # so a photo stays with its record. Exposed for the
                # attachment badge rather than as a visible column.
                "sample_id": row["sample_id"],
                "attachment_count": row["attachment_count"],
                "list_no": row["list_no"],
            }
            for row in rows
        ],
    }


@router.post("/spt/bulk", status_code=201)
async def add_spt_bulk(
    project_id: str,
    loca_id: str,
    payload: SPTBulkCreate,
    current_user: dict = Depends(get_current_user),
):
    """Submit the populated rows of the SPT entry grid. Blank rows are
    never sent by the frontend, so they never create records or consume
    a Sample ID. Each saved row is PENDING until admin approval."""

    await _require_loca(project_id, loca_id)

    try:
        created = await create_spt_records_bulk(
            project_id=project_id,
            loca_id=loca_id,
            rows=payload.records,
            user=current_user,
        )
    except DuplicateRecordError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "message": f"{len(created)} SPT record(s) submitted for approval",
        "records": created,
    }


@router.patch("/spt/{spt_depth}")
async def update_spt(
    project_id: str,
    loca_id: str,
    spt_depth: Decimal,
    payload: SPTRecordUpdate,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    updated = await update_spt_record(
        project_id=project_id,
        loca_id=loca_id,
        original_spt_depth=spt_depth,
        spt_depth=payload.spt_depth,
        blows_15=payload.blows_15,
        blows_30=payload.blows_30,
        blows_45=payload.blows_45,
        user=current_user,
    )

    if updated is None:
        raise HTTPException(status_code=404, detail="SPT record not found.")

    return {
        "message": "SPT record updated successfully",
        "record": {
            "spt_depth": updated["spt_depth"],
            "blows_15": updated["blows_15"],
            "blows_30": updated["blows_30"],
            "blows_45": updated["blows_45"],
            "n_value": updated["n_value"],
        },
    }

@router.delete("/spt/{spt_depth}")
async def delete_spt(
    project_id: str,
    loca_id: str,
    spt_depth: Decimal,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    result = await delete_spt_record(
        project_id=project_id,
        loca_id=loca_id,
        spt_depth=spt_depth,
        user=current_user,
    )

    if result == "DELETE 0":
        raise HTTPException(
            status_code=404,
            detail="SPT record not found.",
        )

    return {
        "message": "SPT record deleted successfully",
    }


# ---------------------------------------------------------------------------
# SPT admin approval
# ---------------------------------------------------------------------------

@router.get("/spt/pending")
async def spt_pending(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)

    rows = await get_pending_spt_records(project_id, loca_id)

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "records": [dict(row) for row in rows],
    }


@router.post("/spt/{spt_depth}/approve")
async def spt_approve(
    project_id: str,
    loca_id: str,
    spt_depth: Decimal,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)

    updated = await approve_spt_record(project_id, loca_id, spt_depth, current_user)

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Pending SPT record not found at this depth.",
        )

    return {"message": "SPT record approved", "sample_id": updated["sample_id"]}


@router.post("/spt/{spt_depth}/reject")
async def spt_reject(
    project_id: str,
    loca_id: str,
    spt_depth: Decimal,
    payload: SPTReject,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)

    updated = await reject_spt_record(
        project_id, loca_id, spt_depth, current_user, payload.reason
    )

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Pending SPT record not found at this depth.",
        )

    return {"message": "SPT record rejected", "sample_id": updated["sample_id"]}


# ---------------------------------------------------------------------------
# Rock (Field Data > Rock) - same workflow as SPT
# ---------------------------------------------------------------------------

def _rock_json(row) -> dict:
    return {
        "sample_id": row["sample_id"],
        "depth_from": row["depth_from"],
        "depth_to": row["depth_to"],
        "recovery": row["recovery"],
        "rqd": row["rqd"],
        "rock_type": row["rock_type"],
        "lift_no": row["lift_no"],
        "pieces": row.get("pieces", []),
        # Position in the depth-ordered result. Derived server-side, so the
        # number on screen is always the truth of the current ordering.
        "list_no": row.get("list_no"),
    }


@router.get("/rock")
async def rock_records(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    rows = await get_rock_records(project_id, loca_id)

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "records": [
            {
                **_rock_json(row),
                "status": row["status"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


@router.post("/rock/bulk", status_code=201)
async def add_rock_bulk(
    project_id: str,
    loca_id: str,
    payload: RockBulkCreate,
    current_user: dict = Depends(get_current_user),
):
    """Submit the populated rows of the Rock entry grid. Each saved row gets
    a Sample ID and is PENDING until admin approval."""

    await _require_loca(project_id, loca_id)

    try:
        created = await create_rock_records_bulk(
            project_id=project_id,
            loca_id=loca_id,
            rows=payload.records,
            user=current_user,
        )
    except (DuplicateRecordError, RockIntervalOverlapError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "message": f"{len(created)} Rock record(s) submitted for approval",
        "records": created,
    }


@router.patch("/rock/{depth_from}")
async def update_rock(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    payload: RockRecordUpdate,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    try:
        updated = await update_rock_record(
            project_id=project_id,
            loca_id=loca_id,
            original_depth_from=depth_from,
            row=payload,
            user=current_user,
        )
    except (DuplicateRecordError, RockIntervalOverlapError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if updated is None:
        raise HTTPException(status_code=404, detail="Rock record not found.")

    return {
        "message": "Rock record updated successfully",
        "record": updated,
    }


@router.delete("/rock/{depth_from}")
async def delete_rock(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    result = await delete_rock_record(
        project_id=project_id,
        loca_id=loca_id,
        depth_from=depth_from,
        user=current_user,
    )

    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Rock record not found.")

    return {"message": "Rock record deleted successfully"}


# ---------------------------------------------------------------------------
# Rock admin approval
# ---------------------------------------------------------------------------

@router.get("/rock/pending")
async def rock_pending(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)

    rows = await get_pending_rock_records(project_id, loca_id)

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "records": [dict(row) for row in rows],
    }


@router.post("/rock/{depth_from}/approve")
async def rock_approve(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)

    updated = await approve_rock_record(project_id, loca_id, depth_from, current_user)

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Pending Rock record not found at this depth.",
        )

    return {"message": "Rock record approved", "sample_id": updated["sample_id"]}


@router.post("/rock/{depth_from}/reject")
async def rock_reject(
    project_id: str,
    loca_id: str,
    depth_from: Decimal,
    payload: RockReject,
    current_user: dict = Depends(get_current_admin),
):
    await _require_loca(project_id, loca_id)

    updated = await reject_rock_record(
        project_id, loca_id, depth_from, current_user, payload.reason
    )

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Pending Rock record not found at this depth.",
        )

    return {"message": "Rock record rejected", "sample_id": updated["sample_id"]}


# ---------------------------------------------------------------------------
@router.get("/samples")
async def project_samples(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    rows = await get_project_samples(project_id)

    return {
        "project_id": project_id,
        "samples": [
            {
                "sample_id": row["sample_id"],
                "loca_id": row["loca_id"],
                "depth_from": row["depth_from"],
                "depth_to": row["depth_to"],
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# Groundwater
#
# No AGS4 group/column mapping for Groundwater was supplied or could be
# confirmed from the existing codebase or schema. Per the task's explicit
# instruction not to invent a mapping, this endpoint reports the module as
# unavailable instead of returning guessed or fabricated data.
# ---------------------------------------------------------------------------

@router.get("/groundwater")
async def groundwater_records(
    project_id: str,
    loca_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _require_loca(project_id, loca_id)

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "available": False,
        "reason": (
            "Groundwater data mapping has not been configured for this "
            "database yet."
        ),
        "records": [],
    }
