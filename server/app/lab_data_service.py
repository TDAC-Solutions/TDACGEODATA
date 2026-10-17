from datetime import datetime
from uuid import UUID, uuid4
import json
from hashlib import sha256

import asyncpg

from app import database
from app.field_data_service import sync_approved_samples_to_samp
from app.lab_engine import adapters as lab_engine_adapters
from app.lab_engine.common import InputError as EngineInputError


class DuplicateLabTestError(ValueError):
    """The same sample+type+specimen is already registered.

    A subclass of ValueError so existing callers keep their 400 behavior;
    the routers single it out to return 409, which is what a duplicate
    actually is (the request is valid, it conflicts with existing state).
    """


async def _load_project_and_sample(connection, project_id, loca_id, samp_id):
    """Project FILE_FSET plus the sample row. Two queries in total.

    FILE_FSET has to be resolved rather than read straight off PROJ. Both
    ags42."PROJ"."FILE_FSET" and ags42."SAMP"."FILE_FSET" are NULL in the
    seeded data even though the project does have a FILE row, and
    lab."test"."file_fset" is NOT NULL. Taking the column at face value
    therefore produced a 500 on every registration. The sample value wins,
    then the project column, then the project's FILE row, which is where
    the seeded FS-TDAC-901 actually lives.

    A project with no resolvable file set is refused here with a clear
    message instead of failing on the INSERT as a 500.
    """
    project = await connection.fetchrow(
        """
        SELECT
            p."PROJ_ID",
            p."FILE_FSET",
            (
                SELECT f."FILE_FSET"
                FROM "ags42"."FILE" f
                WHERE f."PROJ_ID" = p."PROJ_ID"
                ORDER BY f."FILE_FSET"
                LIMIT 1
            ) AS project_file_fset
        FROM "ags42"."PROJ" p
        WHERE p."PROJ_ID" = $1
        """,
        project_id,
    )

    if project is None:
        raise ValueError("Project does not exist.")

    # The sample was approved in Field Data, which writes its approval
    # ledger (tdac.SPT_RECORD_STATUS / tdac.ROCK_RECORD), not ags42."SAMP".
    # Sync inside this registration transaction so a sample approved moments
    # ago can be registered against without waiting for a Sample Register
    # refresh, and so an aborted registration leaves no half-synced state.
    await sync_approved_samples_to_samp(connection, project_id)

    sample = await connection.fetchrow(
        """
        SELECT
            "PROJ_ID",
            "LOCA_ID",
            "SAMP_ID",
            "SAMP_TOP",
            "SAMP_REF",
            "SAMP_TYPE",
            "SAMP_BASE",
            "FILE_FSET"
        FROM "ags42"."SAMP"
        WHERE "PROJ_ID" = $1
          AND "LOCA_ID" = $2
          AND "SAMP_ID" = $3
        """,
        project_id,
        loca_id,
        samp_id,
    )

    if sample is None:
        raise ValueError(
            "The selected sample does not belong to this project."
        )

    # btrim mirrors the CHECK on ags42."FILE"."FILE_FSET", which rejects a
    # blank string but NOT a whitespace-only one. Python treats "   " as
    # truthy, so an all-spaces file set would otherwise sail through the
    # or-chain below and be written to lab."test" unchallenged.
    file_fset = (
        sample["FILE_FSET"]
        or project["FILE_FSET"]
        or project["project_file_fset"]
    )

    if file_fset:
        file_fset = file_fset.strip() or None
    if not file_fset:
        # A project born in the UI (Create Project → Add Location → Sample)
        # never wrote an ags42."FILE" row — the only writers before were the
        # seed scripts and the spreadsheet import. lab."test"."file_fset" is
        # NOT NULL and part of the uniqueness key, so without one we dead-end
        # here. Rather than refusing, provision a deterministic file set in
        # the caller's transaction: same transaction means a rollback on a
        # later failure leaves no orphaned FILE row. The ON CONFLICT keeps
        # concurrent first-registrations from racing (each project has
        # exactly one FS-<id> file set). It is deliberately target-less:
        # an unquoted conflict target folds to lowercase, and the FILE key
        # columns are quoted mixed-case, so naming them raised
        # UndefinedColumnError on every UI-born project.
        file_fset = f"FS-{project_id}"
        await connection.execute(
            """
            INSERT INTO "ags42"."FILE" ("PROJ_ID", "FILE_FSET", "FILE_NAME", "FILE_TYPE")
            SELECT $1, $2, $3, 'AGS'
            WHERE NOT EXISTS (
                SELECT 1 FROM "ags42"."FILE" f WHERE f."PROJ_ID" = $1
            )
            ON CONFLICT DO NOTHING
            """,
            project_id,
            file_fset,
            f"{project_id} AGS Data",
        )

    return file_fset, sample


async def _insert_lab_test(
    connection,
    file_fset,
    sample,
    *,
    specimen_ref: str,
    test_type: str,
    method_definition_id: UUID,
    laboratory: str,
    technician: str | None,
    test_started_at: datetime | None,
    test_completed_at: datetime | None,
    created_by: str,
):
    """One INSERT. The caller has already validated the method and sample.

    The unique key on lab."test" is
    (file_fset, loca_id, samp_id, spec_ref, test_type, current_revision).
    A duplicate therefore still lands here as a UniqueViolationError even
    when the batch pre-check missed it, for example a concurrent submit
    from another session, and rolls the whole transaction back.
    """
    test_id = uuid4()

    try:
        return await connection.fetchrow(
            """
            INSERT INTO "lab"."test" (
                "test_id",
                "file_fset",
                "loca_id",
                "samp_id",
                "samp_top",
                "samp_ref",
                "samp_type",
                "spec_ref",
                "spec_depth",
                "spec_base",
                "test_type",
                "method_definition_id",
                "laboratory",
                "technician",
                "test_started_at",
                "test_completed_at",
                "source_type",
                "status",
                "current_revision",
                "row_version",
                "created_by",
                "updated_by"
            )
            VALUES (
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                $7,
                $8,
                $9,
                $10,
                $11,
                $12,
                $13,
                $14,
                $15,
                $16,
                'MANUAL',
                'DRAFT',
                1,
                1,
                $17,
                $17
            )
            RETURNING
                "test_id",
                "file_fset",
                "loca_id",
                "samp_id",
                "samp_top",
                "samp_ref",
                "samp_type",
                "spec_ref",
                "spec_depth",
                "spec_base",
                "test_type",
                "method_definition_id",
                "laboratory",
                "technician",
                "test_started_at",
                "test_completed_at",
                "source_type",
                "status",
                "current_revision",
                "row_version",
                "created_at",
                "created_by",
                "updated_at",
                "updated_by"
            """,
            test_id,
            file_fset,
            sample["LOCA_ID"],
            sample["SAMP_ID"],
            sample["SAMP_TOP"],
            sample["SAMP_REF"],
            sample["SAMP_TYPE"],
            specimen_ref,
            sample["SAMP_TOP"],
            sample["SAMP_BASE"],
            test_type,
            method_definition_id,
            laboratory,
            technician,
            test_started_at,
            test_completed_at,
            created_by,
        )
    except asyncpg.UniqueViolationError:
        raise DuplicateLabTestError(
            f"A {test_type} test with specimen reference {specimen_ref!r} "
            "is already registered for this sample and revision."
        )


async def create_lab_test(
    project_id: str,
    loca_id: str,
    samp_id: str,
    specimen_ref: str,
    test_type: str,
    method_definition_id: UUID,
    laboratory: str,
    technician: str | None,
    test_started_at: datetime | None,
    test_completed_at: datetime | None,
    created_by: str,
):
    """Register one laboratory test. Unchanged contract."""
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            file_fset, sample = await _load_project_and_sample(
                connection,
                project_id,
                loca_id,
                samp_id,
            )

            # Verify the selected laboratory method exists.
            method = await connection.fetchrow(
                """
                SELECT
                    "method_definition_id",
                    "test_type"
                FROM "lab"."method_definition"
                WHERE "method_definition_id" = $1
                  AND "active" = true
                """,
                method_definition_id,
            )

            if method is None:
                raise ValueError(
                    "The selected laboratory method does not exist "
                    "or is inactive."
                )

            if method["test_type"] != test_type:
                raise ValueError(
                    "The selected method does not match the test type."
                )

            return await _insert_lab_test(
                connection,
                file_fset,
                sample,
                specimen_ref=specimen_ref,
                test_type=test_type,
                method_definition_id=method_definition_id,
                laboratory=laboratory,
                technician=technician,
                test_started_at=test_started_at,
                test_completed_at=test_completed_at,
                created_by=created_by,
            )


async def create_lab_tests_bulk(
    project_id: str,
    tests: list,
    created_by: str,
):
    """Register several tests against one sample in a single transaction.

    Performance: 3 + N round trips for N tests (project, sample, all
    methods in one query, then N inserts) against 4*N for the per-test path.
    One transaction means a duplicate anywhere in the batch rolls every
    earlier insert back, so the sample is never half-registered.

    Pre-check scope: every test in a batch shares one specimen reference,
    so rejecting a duplicate test_type in the batch is equivalent to
    rejecting a duplicate on the full unique key. If specimen_ref ever
    becomes per-test, this check must widen to include it. The database
    index stays the ultimate guard either way.
    """
    if not tests:
        raise ValueError("No tests were selected.")

    # A multi-select batch targets ONE sample. A mixed batch is a client
    # bug, and catching it here means test #2 is never silently inserted
    # against test #1's sample.
    first = tests[0]

    for test in tests:
        if (
            test.loca_id != first.loca_id
            or test.samp_id != first.samp_id
        ):
            raise ValueError(
                "All tests in a batch must reference the same sample."
            )

    # Two identical types in one batch would collide on the unique key,
    # so only the first INSERT would succeed and the rest would fail the
    # whole batch. Catch it before any write, with the type named.
    seen: set[str] = set()

    for test in tests:
        if test.test_type in seen:
            raise ValueError(
                f"Test type {test.test_type} is selected more than once."
            )

        seen.add(test.test_type)

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            file_fset, sample = await _load_project_and_sample(
                connection,
                project_id,
                first.loca_id,
                first.samp_id,
            )

            # One round trip for every method id in the batch.
            method_rows = await connection.fetch(
                """
                SELECT
                    "method_definition_id",
                    "test_type"
                FROM "lab"."method_definition"
                WHERE "method_definition_id" = ANY($1::uuid[])
                  AND "active" = true
                """,
                [test.method_definition_id for test in tests],
            )

            method_by_id = {
                str(row["method_definition_id"]): row for row in method_rows
            }

            # Validate every method BEFORE any write, so an invalid
            # selection at position 4 cannot leave tests 1-3 committed.
            for test in tests:
                method = method_by_id.get(str(test.method_definition_id))

                if method is None:
                    raise ValueError(
                        f"The selected method for {test.test_type} does not "
                        "exist or is inactive."
                    )

                if method["test_type"] != test.test_type:
                    raise ValueError(
                        "The selected method does not match test type "
                        f"{test.test_type}."
                    )

            created = []

            for test in tests:
                created.append(
                    await _insert_lab_test(
                        connection,
                        file_fset,
                        sample,
                        specimen_ref=test.specimen_ref,
                        test_type=test.test_type,
                        method_definition_id=test.method_definition_id,
                        laboratory=test.laboratory,
                        technician=test.technician,
                        test_started_at=test.test_started_at,
                        test_completed_at=test.test_completed_at,
                        created_by=created_by,
                    )
                )

            return created

async def get_project_lab_tests(project_id: str):
    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                t."test_id",
                t."loca_id",
                t."samp_id",
                s."SAMP_TOP" AS samp_top,
                s."SAMP_BASE" AS samp_base,
                t."spec_ref",
                t."test_type",
                t."laboratory",
                t."technician",
                t."test_started_at",
                t."test_completed_at",
                t."status",
                t."current_revision",
                t."created_at"
            FROM "lab"."test" t
            INNER JOIN "ags42"."SAMP" s
                ON s."SAMP_ID" = t."samp_id"
               AND s."LOCA_ID" = t."loca_id"
               AND s."PROJ_ID" = $1
            WHERE t."samp_id" = s."SAMP_ID"
            ORDER BY t."created_at" DESC
            """,
            project_id,
        )

    return rows

async def get_approved_results(
    project_id: str,
    sample: str | None = None,
    depth_from: float | None = None,
    depth_to: float | None = None,
    test_type: str | None = None,
):
    """
    Released current revisions only (APPROVED or PUBLISHED), with the
    approved values (LL, PI) read from the revision's calculation snapshot.
    Superseded, draft and rejected records are never returned.
    """
    # NOTE: placeholder numbering. $1 is bound to project_id (the EXISTS
    # subquery below). The dynamic filters must therefore start at $2, so
    # every index is offset by +1 to match the *values passed after
    # project_id in the fetch call.
    conditions = ["t.status IN ('APPROVED', 'PUBLISHED')"]
    values = []

    def ph() -> int:
        return len(values) + 1  # +1 because $1 is reserved for project_id

    if sample:
        values.append(f"%{sample}%")
        conditions.append(
            f"(t.samp_id ILIKE ${ph()} "
            f"OR t.spec_ref ILIKE ${ph()})"
        )

    if depth_from is not None:
        values.append(depth_from)
        conditions.append(f"t.spec_depth >= ${ph()}")

    if depth_to is not None:
        values.append(depth_to)
        conditions.append(f"t.spec_depth <= ${ph()}")

    if test_type:
        values.append(test_type)
        conditions.append(f"t.test_type = ${ph()}")

    where = " AND ".join(conditions)

    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            f"""
            SELECT
                t.test_id,
                t.loca_id,
                t.samp_id,
                t.spec_ref,
                t.spec_depth,
                t.test_type,
                t.laboratory,
                t.status,
                r.calculation_output_snapshot AS calc
            FROM lab.test t
            LEFT JOIN lab.test_revision r
                ON r.test_id = t.test_id
               AND r.revision_no = t.current_revision
            WHERE {where}
              AND EXISTS (
                  SELECT 1
                  FROM ags42."SAMP" s
                  WHERE s."SAMP_ID" = t.samp_id
                    AND s."LOCA_ID" = t.loca_id
                    AND s."PROJ_ID" = $1
              )
            ORDER BY t.loca_id, t.spec_depth
            """,
            project_id,
            *values,
        )

    results = []

    for row in rows:
        # asyncpg returns jsonb as a str; parse it before reading keys.
        calc_raw = row["calc"]
        calc: dict = {}
        if calc_raw:
            try:
                parsed = json.loads(calc_raw) if isinstance(calc_raw, str) else calc_raw
                if isinstance(parsed, dict):
                    calc = parsed
            except (ValueError, TypeError):
                calc = {}

        # Released values may be stored either as flat keys (legacy seed) or
        # under the normalised "outputs" object written by Results Entry.
        # Both shapes are read here, with "outputs" taking priority, so this
        # matches _project_ags_rows exactly. The merged view is returned as
        # "outputs" so every reader sees one canonical shape and the client
        # never has to re-derive it.
        nested = calc.get("outputs")
        if not isinstance(nested, dict):
            nested = {}

        def released(key: str):
            if key in nested:
                return nested[key]

            return calc.get(key)

        merged_outputs = {
            key: value
            for key, value in calc.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        merged_outputs.update(
            {
                key: value
                for key, value in nested.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        )

        results.append(
            {
                "test_id": str(row["test_id"]),
                "proj_id": project_id,
                "loca_id": row["loca_id"],
                "sample_id": row["samp_id"],
                "spec_ref": row["spec_ref"],
                "depth": row["spec_depth"],
                "test_type": row["test_type"],
                "laboratory": row["laboratory"],
                "status": row["status"],
                "ll": released("liquid_limit"),
                "pi": released("plasticity_index"),
                "outputs": merged_outputs,
            }
        )

    return results

async def get_review_queue(project_id: str):
    """
    Tests waiting for independent review (SUBMITTED, CHECKED) and tests that
    are approved but not yet released (APPROVED), with unresolved issue counts
    from lab.validation_issue. Approved rows stay in the queue so the release
    step is reachable from the UI - approval alone does not publish.
    """
    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                t.test_id,
                t.loca_id,
                t.samp_id,
                t.spec_ref,
                t.test_type,
                t.created_by AS prepared_by,
                t.status,
                t.current_revision,
                (r.test_id IS NOT NULL) AS has_revision,
                m.method_code,
                m.method_version,
                COUNT(v.validation_issue_id) FILTER (
                    WHERE v.severity = 'WARNING'
                    AND v.resolved = false
                ) AS warnings,
                COUNT(v.validation_issue_id) FILTER (
                    WHERE v.severity IN ('ERROR', 'BLOCKER')
                    AND v.resolved = false
                ) AS blockers
            FROM lab.test t
            LEFT JOIN lab.test_revision r
                ON r.test_id = t.test_id
               AND r.revision_no = t.current_revision
            LEFT JOIN lab.method_definition m
                ON m.method_definition_id = t.method_definition_id
            LEFT JOIN lab.validation_issue v
                ON v.test_id = t.test_id
               AND v.revision_no = t.current_revision
            WHERE t.status IN ('SUBMITTED', 'CHECKED', 'APPROVED')
              AND EXISTS (
                  SELECT 1
                  FROM ags42."SAMP" s
                  WHERE s."SAMP_ID" = t.samp_id
                    AND s."LOCA_ID" = t.loca_id
                    AND s."PROJ_ID" = $1
              )
            GROUP BY
                t.test_id,
                t.loca_id,
                t.samp_id,
                t.spec_ref,
                t.test_type,
                t.created_by,
                t.status,
                t.current_revision,
                r.test_id,
                m.method_code,
                m.method_version,
                t.created_at
            ORDER BY
                CASE t.status
                    WHEN 'SUBMITTED' THEN 1
                    WHEN 'CHECKED' THEN 2
                    ELSE 3
                END,
                t.created_at
            """,
            project_id,
        )

    return [
        {
            "test_id": str(row["test_id"]),
            "loca_id": row["loca_id"],
            "sample_id": row["samp_id"],
            "spec_ref": row["spec_ref"],
            "test_type": row["test_type"],
            "prepared_by": row["prepared_by"],
            "status": row["status"],
            "current_revision": row["current_revision"],
            "has_revision": row["has_revision"],
            "method_code": row["method_code"],
            "method_version": row["method_version"],
            "warnings": row["warnings"],
            "blockers": row["blockers"],
        }
        for row in rows
    ]


async def get_active_methods():
    """
    Active method definitions, newest version per method_code.
    The Test Register and Results Entry method dropdowns read this -
    method_definition_id is required to create a lab test.
    """
    async with database.pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT DISTINCT ON (m.method_code)
                m.method_definition_id,
                m.method_code,
                m.method_version,
                m.test_type,
                m.method_name,
                m.standard_body,
                m.standard_reference,
                m.standard_edition,
                m.calculation_package,
                m.calculation_package_version,
                m.ags_mapping_profile,
                m.result_schema,
                m.active
            FROM lab.method_definition m
            WHERE m.active = true
            ORDER BY m.method_code, m.method_version DESC
            """,
        )

    return [
        {
            "method_definition_id": str(row["method_definition_id"]),
            "method_code": row["method_code"],
            "method_version": row["method_version"],
            "test_type": row["test_type"],
            "method_name": row["method_name"],
            "standard_body": row["standard_body"],
            "standard_reference": row["standard_reference"],
            "standard_edition": row["standard_edition"],
            "calculation_package": row["calculation_package"],
            "calculation_package_version": row["calculation_package_version"],
            "ags_group": json.loads(row["ags_mapping_profile"]).get("groups")
            if row["ags_mapping_profile"]
            else None,
            # The released output keys this method declares. Publication only
            # writes values the method definition actually owns.
            "result_outputs": json.loads(row["result_schema"]).get("outputs")
            if row["result_schema"]
            else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Revision persistence and review workflow
#
# Results Entry writes the raw readings, the calculation output and the
# validation findings into lab.test_revision as reproducible snapshots - the
# same shape get_approved_results already reads. Review actions advance
# lab.test.status and append lab.review_event, so the Historic Data and QA
# Approval tabs read real rows instead of empty states.
# ---------------------------------------------------------------------------

# action -> (allowed from-statuses, to-status, review event type)
#
# "publish" is a deliberate release step of its own: approval records the
# independent approval decision (APPROVED) and publish writes the released
# values to the AGS publication record and only then becomes PUBLISHED.
_TRANSITIONS = {
    "submit": ({"DRAFT", "CALCULATED", "RETURNED"}, "SUBMITTED", "SUBMITTED"),
    "check": ({"SUBMITTED"}, "CHECKED", "CHECKED"),
    "approve": ({"CHECKED"}, "APPROVED", "APPROVED"),
    "publish": ({"APPROVED"}, "PUBLISHED", "PUBLISHED"),
    "return": ({"SUBMITTED", "CHECKED"}, "RETURNED", "RETURNED"),
}

# A revision is editable only while the preparer still owns it. SUBMITTED and
# CHECKED revisions are frozen so a save can never reset a review in progress,
# and APPROVED/PUBLISHED revisions are locked for release.
_EDITABLE_STATUSES = {"DRAFT", "CALCULATED", "RETURNED"}

_LOCKED_STATUSES = {"APPROVED", "PUBLISHED", "SUPERSEDED", "VOID"}


def _jsonb(value):
    """Encode a Python object for an asyncpg jsonb parameter."""
    return None if value is None else json.dumps(value)


def _load_jsonb(value):
    """asyncpg returns jsonb as a str; decode it to a Python object."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


async def _fetch_project_test(connection, project_id: str, test_id: str):
    """Fetch a test only if its sample belongs to the given project."""
    try:
        test_uuid = UUID(test_id)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid laboratory test id.")

    test = await connection.fetchrow(
        """
        SELECT
            "test_id",
            "loca_id",
            "samp_id",
            "spec_ref",
            "spec_depth",
            "spec_base",
            "test_type",
            "status",
            "current_revision",
            "row_version",
            "method_definition_id",
            "created_by"
        FROM "lab"."test" t
        WHERE "test_id" = $1
          AND EXISTS (
              SELECT 1
              FROM "ags42"."SAMP" s
              WHERE s."SAMP_ID" = t."samp_id"
                AND s."LOCA_ID" = t."loca_id"
                AND s."PROJ_ID" = $2
          )
        """,
        test_uuid,
        project_id,
    )

    if test is None:
        raise ValueError("Laboratory test not found in this project.")

    return test


def _lab_test_payload(test, revision, issues, events=(), projections=None, method=None):
    """
    One laboratory test with everything the Results Entry and QA/Approval tabs
    need to render state that really exists in the database: the current
    revision snapshots, the open validation issues, the review event history,
    the AGS publication records and the pinned method's AGS groups / released
    output keys.
    """
    groups = None
    result_outputs = None

    if method is not None:
        profile = _load_jsonb(method["ags_mapping_profile"])
        if isinstance(profile, dict):
            groups = profile.get("groups")
        schema = _load_jsonb(method["result_schema"])
        if isinstance(schema, dict):
            result_outputs = schema.get("outputs")

    return {
        "test_id": str(test["test_id"]),
        "loca_id": test["loca_id"],
        "sample_id": test["samp_id"],
        "spec_ref": test["spec_ref"],
        "test_type": test["test_type"],
        "status": test["status"],
        "current_revision": test["current_revision"],
        "row_version": test["row_version"],
        "method_definition_id": str(test["method_definition_id"]),
        "method": (
            {
                "method_definition_id": str(method["method_definition_id"]),
                "method_code": method["method_code"],
                "method_version": method["method_version"],
                "method_name": method["method_name"],
                "standard_body": method["standard_body"],
                "standard_reference": method["standard_reference"],
                "standard_edition": method["standard_edition"],
                "calculation_package": method["calculation_package"],
                "calculation_package_version": method["calculation_package_version"],
            }
            if method is not None
            else None
        ),
        "ags_groups": groups,
        "result_outputs": result_outputs,
        "publication": [
            {
                "ags_group": row["ags_group"],
                "business_key": _load_jsonb(row["business_key"]) or {},
                "projected_row_count": row["projected_row_count"],
                "projected_row_hash": row["projected_row_hash"],
                "projection_status": row["projection_status"],
                "projected_at": row["projected_at"],
                "projected_by": row["projected_by"],
            }
            for row in (projections or [])
        ],
        "review_events": [
            {
                "event_type": row["event_type"],
                "from_status": row["from_status"],
                "to_status": row["to_status"],
                "actor": row["actor"],
                "actor_role": row["actor_role"],
                "reason": row["reason"],
                "event_at": row["event_at"],
            }
            for row in events
        ],
        "revision": (
            {
                "revision_no": revision["revision_no"],
                "raw_input_snapshot": _load_jsonb(revision["raw_input_snapshot"]) or {},
                "calculation_output_snapshot": _load_jsonb(
                    revision["calculation_output_snapshot"]
                ),
                "validation_snapshot": _load_jsonb(revision["validation_snapshot"]),
                "status": revision["status"],
                "created_at": revision["created_at"],
                "created_by": revision["created_by"],
            }
            if revision is not None
            else None
        ),
        "validation_issues": [
            {
                "validation_issue_id": str(row["validation_issue_id"]),
                "rule_code": row["rule_code"],
                "severity": row["severity"],
                "field_path": row["field_path"],
                "message": row["message"],
                "resolved": row["resolved"],
            }
            for row in issues
        ],
    }


async def _set_status(
    connection,
    test,
    to_status: str,
    event_type: str,
    actor: str,
    actor_role: str,
    reason: str | None,
):
    await connection.execute(
        """
        UPDATE "lab"."test"
        SET "status" = $1,
            "updated_at" = now(),
            "updated_by" = $2,
            "row_version" = "row_version" + 1
        WHERE "test_id" = $3
        """,
        to_status,
        actor,
        test["test_id"],
    )

    await connection.execute(
        """
        INSERT INTO "lab"."review_event" (
            "review_event_id",
            "test_id",
            "revision_no",
            "event_type",
            "from_status",
            "to_status",
            "actor",
            "actor_role",
            "reason",
            "correlation_id"
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        uuid4(),
        test["test_id"],
        test["current_revision"],
        event_type,
        test["status"],
        to_status,
        actor,
        actor_role,
        reason,
        str(uuid4()),
    )


async def get_lab_test(project_id: str, test_id: str):
    """
    One test plus its current revision snapshots, validation issues, review
    event history and AGS publication records. There is no invented state here:
    every list is either rows from the lab schema or empty.
    """
    async with database.pool.acquire() as connection:
        test = await _fetch_project_test(connection, project_id, test_id)

        revision = await connection.fetchrow(
            """
            SELECT
                "revision_no",
                "raw_input_snapshot",
                "calculation_output_snapshot",
                "validation_snapshot",
                "status",
                "created_at",
                "created_by"
            FROM "lab"."test_revision"
            WHERE "test_id" = $1
              AND "revision_no" = $2
            """,
            test["test_id"],
            test["current_revision"],
        )

        issues = await connection.fetch(
            """
            SELECT
                "validation_issue_id",
                "rule_code",
                "severity",
                "field_path",
                "message",
                "resolved"
            FROM "lab"."validation_issue"
            WHERE "test_id" = $1
              AND "revision_no" = $2
            ORDER BY "created_at"
            """,
            test["test_id"],
            test["current_revision"],
        )

        events = await connection.fetch(
            """
            SELECT
                "event_type",
                "from_status",
                "to_status",
                "actor",
                "actor_role",
                "reason",
                "event_at"
            FROM "lab"."review_event"
            WHERE "test_id" = $1
            ORDER BY "event_at"
            """,
            test["test_id"],
        )

        projections = await connection.fetch(
            """
            SELECT
                "ags_group",
                "business_key",
                "projected_row_count",
                "projected_row_hash",
                "projection_status",
                "projected_at",
                "projected_by"
            FROM "lab"."ags_projection"
            WHERE "test_id" = $1
              AND "revision_no" = $2
            ORDER BY "ags_group"
            """,
            test["test_id"],
            test["current_revision"],
        )

        method = await connection.fetchrow(
            """
            SELECT
                "method_definition_id",
                "method_code",
                "method_version",
                "method_name",
                "standard_body",
                "standard_reference",
                "standard_edition",
                "calculation_package",
                "calculation_package_version",
                "ags_mapping_profile",
                "result_schema"
            FROM "lab"."method_definition"
            WHERE "method_definition_id" = $1
            """,
            test["method_definition_id"],
        )

    return _lab_test_payload(test, revision, issues, events, projections, method)


async def calculate_lab_test(
    project_id: str,
    test_id: str,
    raw_input: dict | None,
):
    """
    Run the server engine for a test and return the snapshots the caller
    should persist: (raw_input_snapshot, calculation_output_snapshot,
    validation_snapshot).

    For the three engine-backed test types (PSD, PARTICLE_DENSITY, ATTERBERG)
    the server is the calculation authority: the calculation snapshot is
    recomputed from the raw readings, never trusted from the client. For
    every other test type the client-supplied snapshots pass through
    untouched.

    raw_input may be None, in which case the stored revision's raw snapshot
    is used (the "recalculate what is on file" path the PDF renderer and a
    saved revision share).
    """
    async with database.pool.acquire() as connection:
        test = await _fetch_project_test(connection, project_id, test_id)

        if test["test_type"] not in lab_engine_adapters.SUPPORTED_TESTS:
            raise ValueError(
                f"{test['test_type']} has no server calculation engine; "
                "the client snapshot is used as-is."
            )

        if raw_input is None:
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
                raise ValueError("No raw readings stored yet.")
            raw_input = _load_jsonb(revision["raw_input_snapshot"]) or {}

        if not isinstance(raw_input, dict):
            raise ValueError("The stored raw readings are not a valid snapshot.")

        method = await connection.fetchrow(
            """
            SELECT "validation_schema"
            FROM "lab"."method_definition"
            WHERE "method_definition_id" = $1
            """,
            test["method_definition_id"],
        )
        if method is None:
            raise ValueError("The test method definition is missing.")

        config = _load_jsonb(method["validation_schema"]) or {}

    try:
        record = lab_engine_adapters.engine_input(
            test["test_type"],
            raw_input,
            project_id=project_id,
            test_row=dict(test),
            method_config=config,
        )
        result = lab_engine_adapters.run_engine(test["test_type"], record)
    except EngineInputError as exc:
        # The engine refused the readings. The message is already written for
        # a technician (and humanized by the adapters), so it goes to the
        # caller verbatim and becomes a 400 at the route.
        raise ValueError(str(exc)) from None

    calculation_snapshot, validation_snapshot = (
        lab_engine_adapters.build_snapshots(test["test_type"], result)
    )

    return raw_input, calculation_snapshot, validation_snapshot


async def start_new_revision(project_id: str, test_id: str, actor: str):
    """Supersede the current revision and open a new editable one.

    Once a test reaches APPROVED or PUBLISHED the only path forward used to
    be "create a new test" — the unique key forbids re-registering the same
    sample+type, and save_lab_revision refuses to write. This function lets
    the laboratory iterate on the same test instead: the old revision stays
    PUBLISHED as the immutable released record, a new DRAFT revision opens
    with the readings carried forward (the calculation is NOT copied — the
    new revision must be recalculated before it can be QA'd again).
    """
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            test = await _fetch_project_test(connection, project_id, test_id)

            if test["status"] not in {"APPROVED", "PUBLISHED", "RETURNED"}:
                raise ValueError(
                    f"Cannot start a new revision from status "
                    f"'{test['status']}'. Only approved, published, or "
                    "returned revisions can be superseded."
                )

            previous_revision = test["current_revision"]
            new_no = previous_revision + 1

            # The old revision is the released record from here on; freeze it
            # so no later edit path can reopen it once current_revision moves.
            await connection.execute(
                """
                UPDATE "lab"."test_revision"
                SET "immutable" = true
                WHERE "test_id" = $1 AND "revision_no" = $2
                """,
                test["test_id"],
                previous_revision,
            )

            # Insert the new revision row FIRST: review_event's foreign key
            # references (test_id, revision_no) against lab.test_revision, so
            # the revision row must exist before the review event below
            # references it. The readings carry forward; the calculation
            # snapshot does not, so the status is DRAFT -- not CALCULATED --
            # until the save path recomputes it.
            inserted = await connection.execute(
                """
                INSERT INTO "lab"."test_revision" (
                    "test_id",
                    "revision_no",
                    "raw_input_snapshot",
                    "calculation_package",
                    "calculation_package_version",
                    "method_definition_id",
                    "revision_reason",
                    "status",
                    "immutable",
                    "created_by"
                )
                SELECT
                    "test_id",
                    $2,
                    "raw_input_snapshot",
                    "calculation_package",
                    "calculation_package_version",
                    "method_definition_id",
                    $3,
                    'DRAFT',
                    false,
                    $4
                FROM "lab"."test_revision"
                WHERE "test_id" = $1 AND "revision_no" = $5
                """,
                test["test_id"],
                new_no,
                f"New revision (supersedes rev {previous_revision})",
                actor,
                previous_revision,
            )

            # A legacy test can sit at APPROVED without any test_revision row
            # (the original register path wrote bare lab.test rows). The
            # INSERT..SELECT copies zero rows then, and the review event's
            # foreign key would reject the (test_id, new_no) it references,
            # aborting the whole supersession. Fall back to an empty revision
            # built from the method definition so the FK always resolves.
            if inserted == "INSERT 0 0":
                method = await connection.fetchrow(
                    """
                    SELECT "calculation_package", "calculation_package_version"
                    FROM "lab"."method_definition"
                    WHERE "method_definition_id" = $1
                    """,
                    test["method_definition_id"],
                )
                if method is None:
                    raise ValueError("The test method definition is missing.")

                await connection.execute(
                    """
                    INSERT INTO "lab"."test_revision" (
                        "test_id",
                        "revision_no",
                        "raw_input_snapshot",
                        "calculation_package",
                        "calculation_package_version",
                        "method_definition_id",
                        "revision_reason",
                        "status",
                        "immutable",
                        "created_by"
                    )
                    VALUES (
                        $1, $2, '{}'::jsonb, $3, $4, $5, $6, 'DRAFT', false, $7
                    )
                    """,
                    test["test_id"],
                    new_no,
                    method["calculation_package"],
                    method["calculation_package_version"],
                    test["method_definition_id"],
                    f"New revision (supersedes rev {previous_revision})",
                    actor,
                )

            # Flip the test row back to DRAFT at the new revision, then write
            # the review event directly against the row we just created (the
            # in-memory `test` dict above is stale after the UPDATE; a plain
            # _set_status would carry the old revision number into the event).
            await connection.execute(
                """
                UPDATE "lab"."test"
                SET "status" = 'DRAFT',
                    "current_revision" = $2,
                    "updated_at" = now(),
                    "updated_by" = $3,
                    "row_version" = "row_version" + 1
                WHERE "test_id" = $1
                """,
                test["test_id"],
                new_no,
                actor,
            )

            await connection.execute(
                """
                INSERT INTO "lab"."review_event" (
                    "review_event_id",
                    "test_id",
                    "revision_no",
                    "event_type",
                    "from_status",
                    "to_status",
                    "actor",
                    "actor_role",
                    "reason",
                    "correlation_id"
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                uuid4(),
                test["test_id"],
                new_no,
                "SUPERSEDED",   # valid per review_event_event_type_check
                test["status"],
                "DRAFT",
                actor,
                "lab",
                f"Superseded revision {previous_revision} -> revision {new_no}",
                str(uuid4()),
            )

    # get_lab_test acquires its own pooled connection; calling it while the
    # transaction above still held one deadlocked a small pool. Read the
    # superseded payload back only after the connection is released.
    return await get_lab_test(project_id, test_id)


async def _recalculate_inside_connection(
    connection,
    project_id: str,
    test,
    raw_input_snapshot: dict,
    method_row,
):
    """
    Server-side recompute for an engine-backed test, on the caller's
    connection (so it runs inside save_lab_revision's transaction; a second
    pool acquire there could deadlock under load).

    method_row is the method definition the caller already fetched (the
    revision INSERT needs its package columns anyway) -- re-querying it here
    would be a wasted round trip inside the same transaction.

    Raises ValueError with the engine's humanized message when the readings
    cannot calculate -- which aborts the save before any write, so a bad
    revision can never be persisted.
    """
    if method_row is None:
        raise ValueError("The test method definition is missing.")

    config = _load_jsonb(method_row["validation_schema"]) or {}
    raw = raw_input_snapshot if isinstance(raw_input_snapshot, dict) else {}

    try:
        record = lab_engine_adapters.engine_input(
            test["test_type"],
            raw,
            project_id=project_id,
            test_row=dict(test),
            method_config=config,
        )
        result = lab_engine_adapters.run_engine(test["test_type"], record)
    except EngineInputError as exc:
        raise ValueError(str(exc)) from None

    calculation_snapshot, validation_snapshot = (
        lab_engine_adapters.build_snapshots(test["test_type"], result)
    )

    return raw, calculation_snapshot, validation_snapshot


async def save_lab_revision(
    project_id: str,
    test_id: str,
    raw_input_snapshot: dict,
    calculation_output_snapshot: dict | None,
    validation_snapshot: dict | None,
    revision_reason: str | None,
    actor: str,
):
    """Persist a calculated draft for the test's current revision."""
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            test = await _fetch_project_test(connection, project_id, test_id)

            # Only a revision still owned by the preparer may be saved.
            # SUBMITTED/CHECKED revisions are frozen (a save must never reset a
            # review in progress) and APPROVED/PUBLISHED revisions are locked.
            if test["status"] not in _EDITABLE_STATUSES:
                if test["status"] in _LOCKED_STATUSES:
                    raise ValueError(
                        "This revision is locked; create a new revision to make changes."
                    )
                raise ValueError(
                    f"This revision is {test['status']} and is frozen for independent "
                    "review. Return it to the preparer before editing, or create a "
                    "new revision."
                )

            method = await connection.fetchrow(
                """
                SELECT "calculation_package", "calculation_package_version",
                       "validation_schema"
                FROM "lab"."method_definition"
                WHERE "method_definition_id" = $1
                """,
                test["method_definition_id"],
            )

            if method is None:
                raise ValueError("The test method definition is missing.")

            # Server is the calculation authority for engine-backed tests.
            # Whatever the client sent as calculation output is discarded and
            # recomputed from the raw readings; the client engine is a live
            # preview only. Non-engine test types keep the client snapshot.
            # The method row is passed in: it was already fetched for the
            # revision INSERT's package columns, and a second fetch inside
            # the same transaction is a wasted round trip.
            if test["test_type"] in lab_engine_adapters.SUPPORTED_TESTS:
                raw_input_snapshot, calculation_output_snapshot, validation_snapshot = (
                    await _recalculate_inside_connection(
                        connection,
                        project_id,
                        test,
                        raw_input_snapshot,
                        method,
                    )
                )

            revision_no = test["current_revision"]

            await connection.execute(
                """
                INSERT INTO "lab"."test_revision" (
                    "test_id",
                    "revision_no",
                    "raw_input_snapshot",
                    "calculation_output_snapshot",
                    "validation_snapshot",
                    "calculation_package",
                    "calculation_package_version",
                    "method_definition_id",
                    "revision_reason",
                    "status",
                    "immutable",
                    "created_by"
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'CALCULATED', false, $10)
                ON CONFLICT ("test_id", "revision_no") DO UPDATE SET
                    "raw_input_snapshot" = EXCLUDED."raw_input_snapshot",
                    "calculation_output_snapshot" = EXCLUDED."calculation_output_snapshot",
                    "validation_snapshot" = EXCLUDED."validation_snapshot",
                    "status" = EXCLUDED."status"
                """,
                test["test_id"],
                revision_no,
                _jsonb(raw_input_snapshot or {}),
                _jsonb(calculation_output_snapshot),
                _jsonb(validation_snapshot),
                method["calculation_package"],
                method["calculation_package_version"],
                test["method_definition_id"],
                revision_reason or "Calculated draft",
                actor,
            )

            # Refresh validation issues so the QA counts reflect this run.
            await connection.execute(
                """
                DELETE FROM "lab"."validation_issue"
                WHERE "test_id" = $1 AND "revision_no" = $2
                """,
                test["test_id"],
                revision_no,
            )

            for issue in (validation_snapshot or {}).get("issues", []):
                level = str(issue.get("level", "info")).upper()
                severity = (
                    level
                    if level in ("INFO", "WARNING", "ERROR", "BLOCKER")
                    else "INFO"
                )
                await connection.execute(
                    """
                    INSERT INTO "lab"."validation_issue" (
                        "validation_issue_id",
                        "test_id",
                        "revision_no",
                        "rule_code",
                        "severity",
                        "field_path",
                        "message",
                        "resolved"
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, false)
                    """,
                    uuid4(),
                    test["test_id"],
                    revision_no,
                    str(issue.get("rule_code") or "CALC"),
                    severity,
                    issue.get("field_path"),
                    str(issue.get("message") or "Validation issue"),
                )

            await _set_status(
                connection,
                test,
                "CALCULATED",
                event_type="CALCULATED",
                actor=actor,
                actor_role="lab",
                reason=revision_reason or "Calculation run",
            )

    return await get_lab_test(project_id, test_id)


async def _project_ags_rows(connection, test, project_id: str, actor: str):
    """
    Write the AGS publication record for the test's current revision.

    Publication is deliberately separate from approval. This step:
      * reads the released output keys (result_schema) and the AGS groups
        (ags_mapping_profile) from the pinned method definition - nothing is
        hardcoded in the service;
      * keeps only the released values the method actually declares;
      * refuses to publish when the approved revision carries no released
        value, so a release can never be an empty yes;
      * upserts one lab.ags_projection row per AGS group with a deterministic
        hash of the published business key + values.

    lab.ags_projection is the AGS publication record this schema owns. Writing
    the individual AGS group tables through the method package field mapping is
    the next step of the same release transaction.
    """
    method = await connection.fetchrow(
        """
        SELECT
            "ags_mapping_profile",
            "result_schema"
        FROM "lab"."method_definition"
        WHERE "method_definition_id" = $1
        """,
        test["method_definition_id"],
    )

    if method is None:
        raise ValueError("The test method definition is missing.")

    profile = _load_jsonb(method["ags_mapping_profile"]) or {}
    groups = profile.get("groups") or []
    schema = _load_jsonb(method["result_schema"]) or {}
    declared = schema.get("outputs") or []

    if not groups:
        raise ValueError(
            "The pinned method has no AGS mapping groups; publication is not "
            "configured for it."
        )

    revision = await connection.fetchrow(
        """
        SELECT "calculation_output_snapshot"
        FROM "lab"."test_revision"
        WHERE "test_id" = $1 AND "revision_no" = $2
        """,
        test["test_id"],
        test["current_revision"],
    )

    if revision is None:
        raise ValueError("There is no revision to publish.")

    calc = _load_jsonb(revision["calculation_output_snapshot"]) or {}
    outputs = calc.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    # Released values are stored either under the normalised "outputs" object
    # (Results Entry) or as flat top-level keys (older revisions). Read both so
    # an approved revision written before the normalised shape can still be
    # released. Only real numbers count; booleans are not measurements.
    released = {}
    for key in declared:
        value = outputs.get(key, calc.get(key))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        released[key] = value

    if not released:
        raise ValueError(
            "The approved revision has no released value to publish. The pinned "
            f"method declares {', '.join(declared) or 'no'} output key(s), and the "
            "calculation for this test has not produced them yet."
        )

    for group in groups:
        payload = {
            "PROJ_ID": project_id,
            "LOCA_ID": test["loca_id"],
            "SAMP_ID": test["samp_id"],
            "SPEC_REF": test["spec_ref"],
            "TEST_TYPE": test["test_type"],
            "AGS_GROUP": group,
            "revision_no": test["current_revision"],
            "released_values": released,
        }
        digest = sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        await connection.execute(
            """
            INSERT INTO "lab"."ags_projection" (
                "test_id",
                "revision_no",
                "ags_group",
                "business_key",
                "projected_row_count",
                "projected_row_hash",
                "projection_status",
                "projected_at",
                "projected_by"
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'PROJECTED', now(), $7)
            ON CONFLICT ("test_id", "revision_no", "ags_group") DO UPDATE SET
                "business_key" = EXCLUDED."business_key",
                "projected_row_count" = EXCLUDED."projected_row_count",
                "projected_row_hash" = EXCLUDED."projected_row_hash",
                "projection_status" = EXCLUDED."projection_status",
                "projected_at" = EXCLUDED."projected_at",
                "projected_by" = EXCLUDED."projected_by",
                "error_detail" = NULL
            """,
            test["test_id"],
            test["current_revision"],
            group,
            _jsonb(payload),
            len(released),
            digest,
            actor,
        )

    return groups



async def transition_lab_test(
    project_id: str,
    test_id: str,
    action: str,
    actor: str,
    actor_role: str,
    reason: str | None = None,
):
    """Advance a test through submit / check / approve / publish / return."""
    if action not in _TRANSITIONS:
        raise ValueError(f"Unknown review action '{action}'.")

    from_statuses, to_status, event_type = _TRANSITIONS[action]

    async with database.pool.acquire() as connection:
        async with connection.transaction():
            test = await _fetch_project_test(connection, project_id, test_id)

            if test["status"] not in from_statuses:
                raise ValueError(
                    f"Cannot {action} a test in status '{test['status']}'."
                )

            has_revision = await connection.fetchval(
                """
                SELECT 1
                FROM "lab"."test_revision"
                WHERE "test_id" = $1 AND "revision_no" = $2
                """,
                test["test_id"],
                test["current_revision"],
            )

            if has_revision is None:
                raise ValueError(
                    "This test has no calculated revision to review yet."
                )

            if action in ("submit", "check", "approve", "publish"):
                blockers = await connection.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM "lab"."validation_issue"
                    WHERE "test_id" = $1
                      AND "revision_no" = $2
                      AND "resolved" = false
                      AND "severity" IN ('ERROR', 'BLOCKER')
                    """,
                    test["test_id"],
                    test["current_revision"],
                )

                if blockers:
                    raise ValueError(
                        f"{blockers} blocking issue(s) must be resolved before "
                        f"this test can be {action}ed."
                    )

            # Release is not a status flip: the approved values are written to
            # the AGS publication record first, and only then does the test
            # become PUBLISHED.
            if action == "publish":
                await _project_ags_rows(connection, test, project_id, actor)

            await _set_status(
                connection,
                test,
                to_status,
                event_type=event_type,
                actor=actor,
                actor_role=actor_role,
                reason=reason or ("Released to AGS" if action == "publish" else None),
            )

    return await get_lab_test(project_id, test_id)
