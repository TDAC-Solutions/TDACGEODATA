from app import database
from datetime import date

async def get_portfolio_summary():
    async with database.pool.acquire() as connection:
        total_projects = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM "ags42"."PROJ"
            """
        )

        projects = await connection.fetch(
            """
            SELECT
                p."PROJ_ID",
                p."PROJ_NAME",
                p."PROJ_LOC",
                p."PROJ_CLNT",
                -- Issue status is project metadata, not a PROJ column. The
                -- portfolio table filters on it client-side, so it has to be
                -- in the summary payload; previously every row rendered "—"
                -- and the status filter could never match.
                pm."ISSUE_STATUS"
            FROM "ags42"."PROJ" p
            LEFT JOIN "tdac"."PROJ_METADATA" pm
                ON pm."PROJ_ID" = p."PROJ_ID"
            ORDER BY p."PROJ_ID"
            """
        )

        # Per-status tally for the metric cards and the Portfolio Status
        # side table. Projects with no metadata row land in "Unspecified"
        # rather than being dropped, so the counts always sum to
        # total_projects.
        status_rows = await connection.fetch(
            """
            SELECT
                COALESCE(pm."ISSUE_STATUS", 'Unspecified') AS status,
                COUNT(*) AS count
            FROM "ags42"."PROJ" p
            LEFT JOIN "tdac"."PROJ_METADATA" pm
                ON pm."PROJ_ID" = p."PROJ_ID"
            GROUP BY COALESCE(pm."ISSUE_STATUS", 'Unspecified')
            """
        )

    return {
        "total_projects": total_projects,
        "projects": projects,
        "status_counts": {row["status"]: row["count"] for row in status_rows},
    }

async def get_project_id_preview() -> str:
    today = date.today()
    year = today.year
    month = today.month

    async with database.pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT "LAST_NUMBER"
            FROM "tdac"."PROJECT_ID_COUNTER"
            WHERE "YEAR" = $1
              AND "MONTH" = $2
            """,
            year,
            month,
        )

    next_number = (row["LAST_NUMBER"] + 1) if row else 1

    return f"TDAC-{year:04d}-{month:02d}-{next_number}"

async def allocate_project_id() -> str:
    today = date.today()
    year = today.year
    month = today.month

    async with database.pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO "tdac"."PROJECT_ID_COUNTER"
                ("YEAR", "MONTH", "LAST_NUMBER")
            VALUES ($1, $2, 1)
            ON CONFLICT ("YEAR", "MONTH")
            DO UPDATE
            SET "LAST_NUMBER" =
                "tdac"."PROJECT_ID_COUNTER"."LAST_NUMBER" + 1
            RETURNING "LAST_NUMBER"
            """,
            year,
            month,
        )

    return f"TDAC-{year:04d}-{month:02d}-{row['LAST_NUMBER']}"

async def get_project(project_id: str):
    async with database.pool.acquire() as connection:
        project = await connection.fetchrow(
            """
            SELECT
                p."PROJ_ID",
                p."PROJ_NAME",
                p."PROJ_LOC",
                p."PROJ_CLNT",
                p."PROJ_ENG",
                p."PROJ_CONT",
                pm."PROJECT_TYPE"
            FROM "ags42"."PROJ" p
            LEFT JOIN "tdac"."PROJ_METADATA" pm
                ON pm."PROJ_ID" = p."PROJ_ID"
            WHERE p."PROJ_ID" = $1
            """,
            project_id,
        )

    return project

async def update_project(
    project_id: str,
    project_name: str,
    project_location: str,
    project_client: str,
):
    async with database.pool.acquire() as connection:
        project = await connection.fetchrow(
            """
            UPDATE "ags42"."PROJ"
            SET
                "PROJ_NAME" = $2,
                "PROJ_LOC" = $3,
                "PROJ_CLNT" = $4
            WHERE "PROJ_ID" = $1
            RETURNING
                "PROJ_ID",
                "PROJ_NAME",
                "PROJ_LOC",
                "PROJ_CLNT"
            """,
            project_id,
            project_name,
            project_location,
            project_client,
        )

    return project

async def create_project(
    connection,
    project_number: str,
    project_name: str,
    country_region: str,
    client: str,
    consultant_name: str,
    contractor_name: str,
):
    project = await connection.fetchrow(
        """
        INSERT INTO "ags42"."PROJ" (
            "PROJ_ID",
            "PROJ_NAME",
            "PROJ_LOC",
            "PROJ_CLNT",
            "PROJ_ENG",
            "PROJ_CONT"
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING
            "PROJ_ID",
            "PROJ_NAME",
            "PROJ_LOC",
            "PROJ_CLNT",
            "PROJ_ENG",
            "PROJ_CONT"
        """,
        project_number,
        project_name,
        country_region,
        client,
        consultant_name,
        contractor_name
    )

    return project

async def get_project_locas(project_id: str):
    async with database.pool.acquire() as connection:
        locas = await connection.fetch(
            """
            SELECT
                l."LOCA_ID",
                l."LOCA_TYPE",
                l."LOCA_FDEP",
                l."LOCA_STAR",
                l."LOCA_ENDD",
                l."LOCA_GL",
                l."LOCA_NATE",
                l."LOCA_NATN",
                l."LOCA_LAT",
                l."LOCA_LON",
                l."PROJ_ID",
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
            ORDER BY l."LOCA_ID"
            """,
            project_id,
        )

    return locas

async def create_project_loca(
    project_id: str,
    loca_id: str,
    loca_type: str,
    start_date,
    end_date,
    final_depth,
    ground_level=None,
    easting=None,
    northing=None,
    latitude=None,
    longitude=None,
    groundwater_depth=None,
):
    async with database.pool.acquire() as connection:
        # Both writes share one transaction so the location and its water
        # strike either both land or neither does. Without this, pool.acquire
        # hands back a raw connection where every statement auto-commits on
        # its own: a rejected strike would leave the LOCA row committed while
        # the caller saw an error, and the retry would then fail on the
        # duplicate key. That half-saved state is worse than a visible
        # failure, so the rollback is the point.
        async with connection.transaction():
            loca = await connection.fetchrow(
                """
                INSERT INTO "ags42"."LOCA" (
                    "LOCA_ID",
                    "LOCA_TYPE",
                    "LOCA_STAR",
                    "LOCA_ENDD",
                    "LOCA_FDEP",
                    "LOCA_GL",
                    "LOCA_NATE",
                    "LOCA_NATN",
                    "LOCA_LAT",
                    "LOCA_LON",
                    "PROJ_ID"
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING
                    "LOCA_ID",
                    "LOCA_TYPE",
                    "LOCA_FDEP",
                    "LOCA_STAR",
                    "LOCA_ENDD",
                    "LOCA_GL",
                    "LOCA_NATE",
                    "LOCA_NATN",
                    "LOCA_LAT",
                    "LOCA_LON",
                    "PROJ_ID"
                """,
                loca_id,
                loca_type,
                start_date,
                end_date,
                final_depth,
                ground_level,
                easting,
                northing,
                latitude,
                longitude,
                project_id,
            )

            if groundwater_depth is not None:
                # A water strike is a strike, not a finding: the same
                # borehole can be struck several times, and AGS records each
                # one as its own WSTG row. A plain insert is therefore
                # correct. uq_wstg_identity makes re-saving the same strike a
                # no-op rather than an error, and naming the constraint
                # explicitly keeps a bare DO NOTHING from swallowing an
                # unrelated conflict.
                await connection.execute(
                    """
                    INSERT INTO "ags42"."WSTG" (
                        "PROJ_ID", "LOCA_ID", "WSTG_DPTH", "WSTG_DTIM"
                    )
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT ("PROJ_ID", "LOCA_ID", "WSTG_DPTH") DO NOTHING
                    """,
                    project_id,
                    loca_id,
                    groundwater_depth,
                )

    return {**dict(loca), "groundwater_depth": groundwater_depth}

async def create_project_metadata(
    connection,
    project_id: str,
    road_reference: str | None = None,
    chainage_text: str | None = None,
    structure_reference: str | None = None,
    selected_boreholes: str | None = None,
    project_type: str | None = None,
    report_type: str | None = None,
    report_title: str | None = None,
    report_volume_title: str | None = None,
    document_reference: str | None = None,
    revision: str | None = None,
    report_date=None,
    issue_status: str | None = None,
    tdac_company_name: str | None = None,
    groundwater_basis: str | None = None,
    design_standard_basis: str | None = None,
    factor_of_safety_basis: str | None = None,
    load_combination_basis: str | None = None,
    construction_verification_requirement: str | None = None,
    pile_load_test_requirement: str | None = None,
):
    metadata = await connection.fetchrow(
        """
        INSERT INTO "tdac"."PROJ_METADATA" (
            "PROJ_ID",
            "ROAD_REFERENCE",
            "CHAINAGE_TEXT",
            "STRUCTURE_REFERENCE",
            "SELECTED_BOREHOLES",
            "PROJECT_TYPE",
            "REPORT_TYPE",
            "REPORT_TITLE",
            "REPORT_VOLUME_TITLE",
            "DOCUMENT_REFERENCE",
            "REVISION",
            "REPORT_DATE",
            "ISSUE_STATUS",
            "TDAC_COMPANY_NAME",
            "GROUNDWATER_BASIS",
            "DESIGN_STANDARD_BASIS",
            "FACTOR_OF_SAFETY_BASIS",
            "LOAD_COMBINATION_BASIS",
            "CONSTRUCTION_VERIFICATION_REQUIREMENT",
            "PILE_LOAD_TEST_REQUIREMENT"
        )
        VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15,
            $16, $17, $18, $19, $20
        )
        RETURNING
            "PROJ_ID",
            "ROAD_REFERENCE",
            "CHAINAGE_TEXT",
            "STRUCTURE_REFERENCE",
            "SELECTED_BOREHOLES",
            "PROJECT_TYPE",
            "REPORT_TYPE",
            "REPORT_TITLE",
            "REPORT_VOLUME_TITLE",
            "DOCUMENT_REFERENCE",
            "REVISION",
            "REPORT_DATE",
            "ISSUE_STATUS",
            "TDAC_COMPANY_NAME",
            "GROUNDWATER_BASIS",
            "DESIGN_STANDARD_BASIS",
            "FACTOR_OF_SAFETY_BASIS",
            "LOAD_COMBINATION_BASIS",
            "CONSTRUCTION_VERIFICATION_REQUIREMENT",
            "PILE_LOAD_TEST_REQUIREMENT"
        """,
        project_id,
        road_reference,
        chainage_text,
        structure_reference,
        selected_boreholes,
        project_type,
        report_type,
        report_title,
        report_volume_title,
        document_reference,
        revision,
        report_date,
        issue_status,
        tdac_company_name,
        groundwater_basis,
        design_standard_basis,
        factor_of_safety_basis,
        load_combination_basis,
        construction_verification_requirement,
        pile_load_test_requirement,

    )
    return metadata

async def get_project_metadata(project_id: str):
    async with database.pool.acquire() as connection:
        metadata = await connection.fetchrow(
            """
            SELECT
                "PROJ_ID" AS proj_id,
                "ROAD_REFERENCE" AS road_reference,
                "CHAINAGE_TEXT" AS chainage_text,
                "STRUCTURE_REFERENCE" AS structure_reference,
                "SELECTED_BOREHOLES" AS selected_boreholes,
                "REPORT_TYPE" AS report_type,
                "REPORT_TITLE" AS report_title,
                "REPORT_VOLUME_TITLE" AS report_volume_title,
                "DOCUMENT_REFERENCE" AS document_reference,
                "REVISION" AS revision,
                "REPORT_DATE" AS report_date,
                "ISSUE_STATUS" AS issue_status,
                "TDAC_COMPANY_NAME" AS tdac_company_name,
                "GROUNDWATER_BASIS" AS groundwater_basis,
                "DESIGN_STANDARD_BASIS" AS design_standard_basis,
                "FACTOR_OF_SAFETY_BASIS" AS factor_of_safety_basis,
                "LOAD_COMBINATION_BASIS" AS load_combination_basis,
                "CONSTRUCTION_VERIFICATION_REQUIREMENT" AS construction_verification_requirement,
                "PILE_LOAD_TEST_REQUIREMENT" AS pile_load_test_requirement
            FROM "tdac"."PROJ_METADATA"
            WHERE "PROJ_ID" = $1
            """,
            project_id,
        )

    return metadata

async def update_project_overview(
    project_id: str,
    project_name: str,
    project_location: str,
    project_client: str,
    consultant_name: str,
    contractor_name: str,
    road_reference: str,
    chainage_text: str,
    structure_reference: str,
    selected_boreholes: str,
    report_type: str,
    report_title: str,
    report_volume_title: str,
    document_reference: str,
    revision: str,
    report_date,
    issue_status: str,
    tdac_company_name: str,
    groundwater_basis: str,
    design_standard_basis: str = "",
    factor_of_safety_basis: str = "",
    load_combination_basis: str = "",
    construction_verification_requirement: str = "",
    pile_load_test_requirement: str = "",
):
    async with database.pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """
                UPDATE "ags42"."PROJ"
                SET
                    "PROJ_NAME" = $1,
                    "PROJ_LOC" = $2,
                    "PROJ_CLNT" = $3,
                    "PROJ_ENG" = $4,
                    "PROJ_CONT" = $5
                WHERE "PROJ_ID" = $6
                """,
                project_name,
                project_location,
                project_client,
                consultant_name,
                contractor_name,
                project_id,
            )

            await connection.execute(
                """
                UPDATE "tdac"."PROJ_METADATA"
                SET
                    "ROAD_REFERENCE" = $1,
                    "CHAINAGE_TEXT" = $2,
                    "STRUCTURE_REFERENCE" = $3,
                    "SELECTED_BOREHOLES" = $4,
                    "REPORT_TYPE" = $5,
                    "REPORT_TITLE" = $6,
                    "REPORT_VOLUME_TITLE" = $7,
                    "DOCUMENT_REFERENCE" = $8,
                    "REVISION" = $9,
                    "REPORT_DATE" = $10,
                    "ISSUE_STATUS" = $11,
                    "TDAC_COMPANY_NAME" = $12,
                    "GROUNDWATER_BASIS" = $13,
                    "DESIGN_STANDARD_BASIS" = $14,
                    "FACTOR_OF_SAFETY_BASIS" = $15,
                    "LOAD_COMBINATION_BASIS" = $16,
                    "CONSTRUCTION_VERIFICATION_REQUIREMENT" = $17,
                    "PILE_LOAD_TEST_REQUIREMENT" = $18
                WHERE "PROJ_ID" = $19
                """,
                road_reference,
                chainage_text,
                structure_reference,
                selected_boreholes,
                report_type,
                report_title,
                report_volume_title,
                document_reference,
                revision,
                report_date,
                issue_status,
                tdac_company_name,
                groundwater_basis,
                design_standard_basis,
                factor_of_safety_basis,
                load_combination_basis,
                construction_verification_requirement,
                pile_load_test_requirement,
                project_id,
            )

        project = await connection.fetchrow(
            """
            SELECT
                "PROJ_ID",
                "PROJ_NAME",
                "PROJ_LOC",
                "PROJ_CLNT",
                "PROJ_ENG",
                "PROJ_CONT"
            FROM "ags42"."PROJ"
            WHERE "PROJ_ID" = $1
            """,
            project_id,
        )

    return project