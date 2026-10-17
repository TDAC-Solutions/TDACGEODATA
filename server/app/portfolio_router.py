import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.lab_data import (
    LabTestCreate,
    LabTestBulkCreate,
    LabCalculateRequest,
    LabRevisionSave,
    LabReviewAction,
)
from app.lab_data_service import (
    DuplicateLabTestError,
    create_lab_test,
    create_lab_tests_bulk,
    get_project_lab_tests,
    get_approved_results,
    get_review_queue,
    get_active_methods,
    get_lab_test,
    save_lab_revision,
    calculate_lab_test,
    start_new_revision,
    transition_lab_test,
)
from app.auth.dependencies import get_current_user
from app import database
from app.qr_service import attach_qr_codes
from app.portfolio_service import (
    get_portfolio_summary,
    get_project_locas,
    get_project,
    create_project,
    create_project_loca,
    create_project_metadata,
    get_project_id_preview,
    update_project,
    allocate_project_id,
    get_project_metadata,
    update_project_overview,
)
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    LocaCreate,
    ProjectOverviewUpdate
)
from app.field_data_service import (
    get_project_samples,
    get_project_sample_tests,
    get_soil_records,
    get_sampling_records,
    loca_belongs_to_project,
)

router = APIRouter(
    prefix="/api/portfolio",
    tags=["Portfolio"],
)


@router.get("/summary")
async def portfolio_summary(
    current_user: dict = Depends(get_current_user),
):
    return await get_portfolio_summary()

@router.get("/projects/next-id")
async def get_next_project_id(
    current_user: dict = Depends(get_current_user),
):
    try:
        project_id = await get_project_id_preview()

        return {
            "project_id": project_id
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to generate project ID: {exc}",
        )

@router.post("/projects")
async def create_project_record(
    project: ProjectCreate,
    current_user: dict = Depends(get_current_user),
):
    project_number = project.project_id
    if project_number.upper() == "AUTO":
        project_number = await allocate_project_id()
    try:
        # One transaction for PROJ and PROJ_METADATA. They previously each
        # acquired their own connection and committed independently, so a
        # metadata failure left a bare project row that the client believed
        # had metadata.
        #
        # Both inserts have to stay INSIDE this block. The metadata insert
        # once sat one indent level out, which meant the acquire() block
        # closed and handed the connection back to the pool before it ran:
        # the PROJ row had already committed, the insert then died with
        # "connection has been released back to the pool", and the caller
        # saw a 500 for a project that was actually half-saved. Keeping
        # them nested is what makes them commit together or not at all.
        async with database.pool.acquire() as connection:
            async with connection.transaction():
                created_project = await create_project(
                    connection=connection,
                    project_number=project_number,
                    project_name=project.project_name,
                    country_region=project.project_location,
                    client=project.project_client,
                    consultant_name=project.consultant_name,
                    contractor_name=project.contractor_name,
                )

                if project.metadata is not None:
                    await create_project_metadata(
                        connection=connection,
                        project_id=project_number,
                        road_reference=project.metadata.road_reference,
                        chainage_text=project.metadata.chainage_text,
                        structure_reference=(
                            project.metadata.structure_reference
                        ),
                        selected_boreholes=(
                            project.metadata.selected_boreholes
                        ),
                        project_type=project.metadata.project_type,
                        report_type=project.metadata.report_type,
                        report_title=project.metadata.report_title,
                        report_volume_title=(
                            project.metadata.report_volume_title
                        ),
                        document_reference=(
                            project.metadata.document_reference
                        ),
                        revision=project.metadata.revision,
                        report_date=project.metadata.report_date,
                        issue_status=project.metadata.issue_status,
                        tdac_company_name=(
                            project.metadata.tdac_company_name
                        ),
                        groundwater_basis=(
                            project.metadata.groundwater_basis
                        ),
                        design_standard_basis=(
                            project.metadata.design_standard_basis
                        ),
                        factor_of_safety_basis=(
                            project.metadata.factor_of_safety_basis
                        ),
                        load_combination_basis=(
                            project.metadata.load_combination_basis
                        ),
                        construction_verification_requirement=(
                            project.metadata.
                            construction_verification_requirement
                        ),
                        pile_load_test_requirement=(
                            project.metadata.pile_load_test_requirement
                        ),
                    )

    except Exception as error:
        error_text = str(error)

        if "duplicate key" in error_text.lower():
            raise HTTPException(
                status_code=409,
                detail="A project with this project number already exists.",
            )

        print(f"Project creation error: {error}")

        raise HTTPException(
            status_code=500,
            detail="Unable to create project.",
        )

    return {
        "message": "Project created successfully",
        "project": {
            "project_number": created_project["PROJ_ID"],
            "project_name": created_project["PROJ_NAME"],
            "country_region": created_project["PROJ_LOC"],
            "client": created_project["PROJ_CLNT"],
        },
    }

@router.patch("/projects/{project_id}/overview")
async def update_project_overview_endpoint(
    project_id: str,
    project: ProjectOverviewUpdate,
    current_user: dict = Depends(get_current_user),
):
    try:
        updated_project = await update_project_overview(
            project_id=project_id,
            project_name=project.project_name,
            project_location=project.project_location,
            project_client=project.project_client,
            consultant_name=project.consultant_name,
            contractor_name=project.contractor_name,
            road_reference=project.road_reference,
            chainage_text=project.chainage_text,
            structure_reference=project.structure_reference,
            selected_boreholes=project.selected_boreholes,
            report_type=project.report_type,
            report_title=project.report_title,
            report_volume_title=project.report_volume_title,
            document_reference=project.document_reference,
            revision=project.revision,
            report_date=project.report_date,
            issue_status=project.issue_status,
            tdac_company_name=project.tdac_company_name,
            groundwater_basis=project.groundwater_basis,
            design_standard_basis=project.design_standard_basis,
            factor_of_safety_basis=project.factor_of_safety_basis,
            load_combination_basis=project.load_combination_basis,
            construction_verification_requirement=(
                project.construction_verification_requirement
            ),
            pile_load_test_requirement=(
                project.pile_load_test_requirement
            ),
        )

        if updated_project is None:
            raise HTTPException(
                status_code=404,
                detail="Project not found.",
            )

        return dict(updated_project)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to update project overview: {exc}",
        )
    
@router.get("/projects/{project_id}")
async def project_record(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    project = await get_project(project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )

    return {
        "project_id": project["PROJ_ID"],
        "project_name": project["PROJ_NAME"],
        "project_location": project["PROJ_LOC"],
        "project_client": project["PROJ_CLNT"],
        "consultant_name": project["PROJ_ENG"],
        "contractor_name": project["PROJ_CONT"],
        "project_type": project["PROJECT_TYPE"],
    }

@router.get("/projects/{project_id}/metadata")
async def get_project_metadata_endpoint(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        metadata = await get_project_metadata(project_id)

        if metadata is None:
            raise HTTPException(
                status_code=404,
                detail="Project metadata not found.",
            )

        return dict(metadata)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load project metadata: {exc}",
        )
    
@router.patch("/projects/{project_id}")
async def update_project_record(
    project_id: str,
    project: ProjectUpdate,
    current_user: dict = Depends(get_current_user),
):
    updated_project = await update_project(
        project_id=project_id,
        project_name=project.project_name,
        project_location=project.project_location,
        project_client=project.project_client,
    )

    if updated_project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )

    return {
        "message": "Project updated successfully",
        "project": {
            "project_id": updated_project["PROJ_ID"],
            "project_name": updated_project["PROJ_NAME"],
            "project_location": updated_project["PROJ_LOC"],
            "project_client": updated_project["PROJ_CLNT"],
        },
    }

def _loca_to_response(loca) -> dict:
    # Single canonical LOCA -> API shape. Both the list endpoint and the
    # create response go through here, so a field can never be added to one
    # and forgotten in the other.
    #
    # numeric columns come back as Decimal. They are narrowed to float here
    # so the JSON body carries a plain number and the client can do
    # arithmetic on it without a string in the way. A null stays null: an
    # unsurveyed borehole must read as "not known", not as zero metres.
    def number(value):
        return float(value) if value is not None else None

    return {
        "loca_id": loca["LOCA_ID"],
        "loca_type": loca["LOCA_TYPE"],
        "final_depth": number(loca["LOCA_FDEP"]),
        "start_date": loca["LOCA_STAR"],
        "end_date": loca["LOCA_ENDD"],
        "ground_level": number(loca["LOCA_GL"]),
        "easting": number(loca["LOCA_NATE"]),
        "northing": number(loca["LOCA_NATN"]),
        "latitude": loca["LOCA_LAT"],
        "longitude": loca["LOCA_LON"],
        "groundwater_depth": number(loca.get("groundwater_depth")),
        "project_id": loca["PROJ_ID"],
    }

@router.get("/projects/{project_id}/locas")
async def project_locas(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    locas = await get_project_locas(project_id)

    return {
        "project_id": project_id,
        "locas": [_loca_to_response(loca) for loca in locas],
    }

@router.post("/projects/{project_id}/locas")
async def create_project_loca_record(
    project_id: str,
    loca: LocaCreate,
    current_user: dict = Depends(get_current_user),
):
    try:
        created_loca = await create_project_loca(
            project_id=project_id,
            loca_id=loca.loca_id,
            loca_type=loca.loca_type,
            start_date=loca.start_date,
            end_date=loca.end_date,
            final_depth=loca.final_depth,
            ground_level=loca.ground_level,
            easting=loca.easting,
            northing=loca.northing,
            latitude=loca.latitude,
            longitude=loca.longitude,
            groundwater_depth=loca.groundwater_depth,
        )
    except Exception as error:
        error_text = str(error)

        if "duplicate key" in error_text.lower():
            raise HTTPException(
                status_code=500,
                detail="A location with this ID already exists.",
            )

        print(f"Location creation error: {error}")

        raise HTTPException(
            status_code=500,
            detail="Unable to create location.",
        )

    return {
        "message":"Location created successfully",
        "loca": _loca_to_response(created_loca),
    }

@router.get("/projects/{project_id}/samples")
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
                "spec_ref": row.get("spec_ref"),
                "depth_from": row["depth_from"],
                "depth_to": row.get("depth_to"),
                "sample_type": row.get("sample_type"),
            }
            for row in rows
        ],
    }

# ---------------------------------------------------------------------------
# Sample Register (Lab Data > Sample Register)
#
# The register that used to sit in Field Data > Sampling / Coring, moved to
# Lab Data, which is project-scoped. Rather than have the client call the
# per-location /soil and /sampling endpoints once per borehole, both halves come
# back in one request here. Same rows, same APPROVED-only rule, same columns --
# the only difference is that loca_id now travels with each record instead of
# being fixed by the URL.
#
# The optional loca_id lets the client narrow server-side rather than fetching
# every borehole and filtering in the browser.
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/sample-register")
async def sample_register(
    project_id: str,
    loca_id: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    # A location filter is only honoured if that location really belongs to
    # this project, so a location from elsewhere cannot be read through it.
    # Same guard as the field-data routes.
    if loca_id is not None and not await loca_belongs_to_project(
        project_id, loca_id
    ):
        raise HTTPException(
            status_code=404,
            detail="This location does not belong to the selected project.",
        )

    # Both halves in parallel: they are independent reads.
    soil_rows, rock_rows = await asyncio.gather(
        get_soil_records(project_id, loca_id),
        get_sampling_records(project_id, loca_id),
    )

    return {
        "project_id": project_id,
        "loca_id": loca_id,
        "soil": [
            {
                "loca_id": row["loca_id"],
                "sample_id": row["sample_id"],
                "depth_from": row["depth_from"],
                "blows_15": row["blows_15"],
                "blows_30": row["blows_30"],
                "blows_45": row["blows_45"],
                "n_value": row["n_value"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
            }
            for row in soil_rows
        ],
        "rock": [
            {
                "loca_id": row["loca_id"],
                "sample_id": row["sample_id"],
                "depth_from": row["depth_from"],
                "depth_to": row["depth_to"],
                "rock_description": row["rock_description"],
                "recovery": row["recovery"],
                "rqd": row["rqd"],
                "remark": row["remark"],
                "lift_no": row["lift_no"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
            }
            for row in rock_rows
        ],
    }


@router.post("/projects/{project_id}/lab/tests", status_code=201)
async def create_project_lab_test(
    project_id: str,
    payload: LabTestCreate,
    current_user: dict = Depends(get_current_user),
):
    try:
        created = await create_lab_test(
            project_id=project_id,
            loca_id=payload.loca_id,
            samp_id=payload.samp_id,
            specimen_ref=payload.specimen_ref,
            test_type=payload.test_type,
            method_definition_id=payload.method_definition_id,
            laboratory=payload.laboratory,
            technician=payload.technician,
            test_started_at=payload.test_started_at,
            test_completed_at=payload.test_completed_at,
            created_by=current_user["username"],
        )

    except DuplicateLabTestError as exc:
        # The request itself is valid; it conflicts with an existing row.
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return {
        "message": "Laboratory test created successfully",
        "test": {
            "test_id": str(created["test_id"]),
            "project_id": project_id,
            "loca_id": created["loca_id"],
            "samp_id": created["samp_id"],
            "spec_ref": created["spec_ref"],
            "test_type": created["test_type"],
            "method_definition_id": str(
                created["method_definition_id"]
            ),
            "laboratory": created["laboratory"],
            "technician": created["technician"],
            "status": created["status"],
            "current_revision": created["current_revision"],
            "row_version": created["row_version"],
        },
    }

@router.post("/projects/{project_id}/lab/tests/bulk", status_code=201)
async def create_project_lab_tests_bulk(
    project_id: str,
    payload: LabTestBulkCreate,
    current_user: dict = Depends(get_current_user),
):
    """Register several tests against one sample in a single transaction.

    One HTTP call from the multi-select register form, one transaction on
    the server. Declared here, before any /lab/tests/{test_id} route, so a
    literal path segment can never be shadowed by a path parameter.
    """
    try:
        created = await create_lab_tests_bulk(
            project_id=project_id,
            tests=payload.tests,
            created_by=current_user["username"],
        )
    except DuplicateLabTestError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return {
        "message": (
            f"{len(created)} laboratory test(s) created successfully"
        ),
        "tests": [
            {
                "test_id": str(row["test_id"]),
                "project_id": project_id,
                "loca_id": row["loca_id"],
                "samp_id": row["samp_id"],
                "spec_ref": row["spec_ref"],
                "test_type": row["test_type"],
                "method_definition_id": str(row["method_definition_id"]),
                "laboratory": row["laboratory"],
                "technician": row["technician"],
                "status": row["status"],
                "current_revision": row["current_revision"],
                "row_version": row["row_version"],
            }
            for row in created
        ],
    }


@router.get("/projects/{project_id}/lab/tests")
async def project_lab_tests(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    rows = await get_project_lab_tests(project_id)

    return {
        "project_id": project_id,
        "tests": [
            {
                "test_id": str(row["test_id"]),
                "loca_id": row["loca_id"],
                "samp_id": row["samp_id"],
                "samp_top": row["samp_top"],
                "samp_base": row["samp_base"],
                "spec_ref": row["spec_ref"],
                "test_type": row["test_type"],
                "laboratory": row["laboratory"],
                "technician": row["technician"],
                "test_started_at": row["test_started_at"],
                "test_completed_at": row["test_completed_at"],
                "status": row["status"],
                "current_revision": row["current_revision"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }

@router.get("/projects/{project_id}/lab/results")
async def project_lab_results(
    project_id: str,
    sample: str | None = None,
    depth_from: float | None = None,
    depth_to: float | None = None,
    test_type: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    rows = await get_approved_results(
        project_id=project_id,
        sample=sample,
        depth_from=depth_from,
        depth_to=depth_to,
        test_type=test_type,
    )

    return {
        "project_id": project_id,
        "results": rows,
    }

@router.get("/projects/{project_id}/lab/review-queue")
async def project_lab_review_queue(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    rows = await get_review_queue(project_id)

    return {
        "project_id": project_id,
        "queue": rows,
    }


@router.get("/projects/{project_id}/lab/tests/{test_id}")
async def project_lab_test(
    project_id: str,
    test_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        test = await get_lab_test(project_id, test_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "project_id": project_id,
        "test": test,
    }


@router.put("/projects/{project_id}/lab/tests/{test_id}/revision")
async def save_project_lab_revision(
    project_id: str,
    test_id: str,
    payload: LabRevisionSave,
    current_user: dict = Depends(get_current_user),
):
    try:
        test = await save_lab_revision(
            project_id=project_id,
            test_id=test_id,
            raw_input_snapshot=payload.raw_input_snapshot,
            calculation_output_snapshot=payload.calculation_output_snapshot,
            validation_snapshot=payload.validation_snapshot,
            revision_reason=payload.revision_reason,
            actor=current_user["username"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "message": "Revision saved",
        "test": test,
    }


@router.post("/projects/{project_id}/lab/tests/{test_id}/calculate")
async def calculate_project_lab_test(
    project_id: str,
    test_id: str,
    payload: LabCalculateRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Dry-run the server calculation engine without persisting anything.

    Used by the Results Entry "Calculate (server)" button so the technician
    sees the authoritative numbers -- the same ones a save will store --
    before deciding to save. For a test type without a server engine this
    returns a clear message instead of a client-shaped guess.
    """
    try:
        raw, calculation_snapshot, validation_snapshot = await calculate_lab_test(
            project_id,
            test_id,
            payload.raw_input_snapshot if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "project_id": project_id,
        "test_id": test_id,
        "raw_input_snapshot": raw,
        "calculation_output_snapshot": calculation_snapshot,
        "validation_snapshot": validation_snapshot,
    }


@router.get("/projects/{project_id}/lab/tests/{test_id}/result-pdf")
async def lab_test_result_pdf(
    project_id: str,
    test_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Method result sheet (DRAFT-stamped) rendered from the stored revision.

    The renderer recalculates from the stored raw readings -- the same
    authority as a save -- so the sheet can never disagree with the stored
    calculation snapshot. Lazy imports keep reportlab/matplotlib off the
    boot path; the CPU-bound draw runs off the event loop.
    """
    from fastapi.responses import Response

    try:
        from app.lab_engine.pdf import render_revision_pdf

        content = await render_revision_pdf(project_id, test_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="{test_id}_result.pdf"'
            ),
            "Cache-Control": "private, no-store",
        },
    )


async def _apply_review_action(
    project_id: str,
    test_id: str,
    action: str,
    current_user: dict,
    payload: LabReviewAction | None,
):
    try:
        test = await transition_lab_test(
            project_id=project_id,
            test_id=test_id,
            action=action,
            actor=current_user["username"],
            actor_role=current_user.get("role_name") or "lab",
            reason=payload.reason if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "message": f"Test {action} completed",
        "test": test,
    }


@router.post("/projects/{project_id}/lab/tests/{test_id}/new-revision")
async def new_lab_revision(
    project_id: str,
    test_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Supersede a finished (APPROVED/PUBLISHED) or returned revision and open a
    fresh editable one. The old revision stays as the immutable released
    record; the new one starts with the readings carried forward and an
    empty calculated snapshot, so it must flow through calculate/save again
    before QA.
    """
    try:
        revision = await start_new_revision(
            project_id,
            test_id,
            current_user["username"],
        )
    except ValueError as exc:
        # No such test, or the test's status rules out a new revision.
        raise HTTPException(status_code=400, detail=str(exc))

    # Every other lab mutation answers with the {message, test} envelope;
    # returning the bare payload here made the client's body.test undefined.
    return {
        "message": "New revision started",
        "test": revision,
    }


@router.post("/projects/{project_id}/lab/tests/{test_id}/submit")
async def submit_project_lab_test(
    project_id: str,
    test_id: str,
    payload: LabReviewAction | None = None,
    current_user: dict = Depends(get_current_user),
):
    return await _apply_review_action(
        project_id, test_id, "submit", current_user, payload
    )


@router.post("/projects/{project_id}/lab/tests/{test_id}/check")
async def check_project_lab_test(
    project_id: str,
    test_id: str,
    payload: LabReviewAction | None = None,
    current_user: dict = Depends(get_current_user),
):
    return await _apply_review_action(
        project_id, test_id, "check", current_user, payload
    )


@router.post("/projects/{project_id}/lab/tests/{test_id}/approve")
async def approve_project_lab_test(
    project_id: str,
    test_id: str,
    payload: LabReviewAction | None = None,
    current_user: dict = Depends(get_current_user),
):
    return await _apply_review_action(
        project_id, test_id, "approve", current_user, payload
    )


@router.post("/projects/{project_id}/lab/tests/{test_id}/return")
async def return_project_lab_test(
    project_id: str,
    test_id: str,
    payload: LabReviewAction | None = None,
    current_user: dict = Depends(get_current_user),
):
    return await _apply_review_action(
        project_id, test_id, "return", current_user, payload
    )


@router.post("/projects/{project_id}/lab/tests/{test_id}/publish")
async def publish_project_lab_test(
    project_id: str,
    test_id: str,
    payload: LabReviewAction | None = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Release an APPROVED revision: writes the released values to the AGS
    publication record and moves the test to PUBLISHED. Separate from approve
    on purpose - approval is a decision, publish is the release.
    """
    return await _apply_review_action(
        project_id, test_id, "publish", current_user, payload
    )


@router.get("/lab/methods")
async def lab_methods(
    current_user: dict = Depends(get_current_user),
):
    rows = await get_active_methods()

    return {
        "methods": rows,
    }

@router.get("/projects/{project_id}/sample-tests")
async def project_sample_tests(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    rows = await get_project_sample_tests(project_id)

    return {
        "project_id": project_id,
        "samples": [
            {
                "sample_id": row["sample_id"],
                "loca_id": row["loca_id"],
                "test_id": (
                    str(row["test_id"])
                    if row["test_id"] is not None
                    else None
                ),
                "test_type": row["test_type"],
                "spec_ref": row["spec_ref"],
                "current_revision": row["current_revision"],
                "status": (
                    row["status"]
                    if row["status"] is not None
                    else "NOT_TESTED"
                ),
            }
            for row in rows
        ],
    }


@router.get("/projects/{project_id}/sample-register/qr")
async def sample_register_qr(
    project_id: str,
    scope: str = "all",
    loca_id: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """QR codes for the samples the client asked for.

    scope:
      all   every approved sample (soil + rock)
      soil  approved SPT samples only
      rock  approved Rock records only

    loca_id narrows server-side exactly as /sample-register does, so the QR
    set can never drift from the filtered register above it. A location from
    another project is a 404, the same guard the register uses.

    Every sample carries the exact `payload` string embedded in its QR plus
    an SVG data URI to render, so what a scanner reads is always what the
    server produced.
    """

    if scope not in ("all", "soil", "rock"):
        raise HTTPException(
            status_code=400,
            detail="scope must be one of: all, soil, rock",
        )

    if loca_id is not None and not await loca_belongs_to_project(
        project_id, loca_id
    ):
        raise HTTPException(
            status_code=404,
            detail="This location does not belong to the selected project.",
        )

    # The same two reads the register makes, so the QR set and the visible
    # register cannot disagree about which samples exist.
    soil_rows, rock_rows = await asyncio.gather(
        get_soil_records(project_id, loca_id),
        get_sampling_records(project_id, loca_id),
    )

    samples: list[dict] = []

    if scope in ("all", "soil"):
        for row in soil_rows:
            samples.append(
                {
                    "kind": "soil",
                    "sample_id": row["sample_id"],
                    "loca_id": row["loca_id"],
                    "depth_from": row["depth_from"],
                    "depth_to": None,
                }
            )

    if scope in ("all", "rock"):
        for row in rock_rows:
            samples.append(
                {
                    "kind": "rock",
                    "sample_id": row["sample_id"],
                    "loca_id": row["loca_id"],
                    "depth_from": row["depth_from"],
                    "depth_to": row["depth_to"],
                }
            )

    # Deterministic order, so re-printing produces the same sheet.
    samples.sort(key=lambda row: (row["loca_id"], row["depth_from"] or 0))

    coded = attach_qr_codes(project_id, samples)

    return {
        "project_id": project_id,
        "scope": scope,
        "loca_id": loca_id,
        "count": len(coded),
        "samples": coded,
    }
