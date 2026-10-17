"""Regression tests for the project create -> workspace flow.

The bug these tests exist for: create_project_record let the
`async with database.pool.acquire()` block end before running the metadata
insert, so asyncpg answered with "cannot call Connection.fetchrow():
connection has been released back to the pool" and the endpoint returned a
500 after the PROJ row had already committed. The shared FakePool cannot
see that class of mistake because its connection never really goes
anywhere, so StrictReleasePool below makes use-after-release raise the same
way the real pool does - the old code fails these tests, the fixed code
passes them.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import date

import pytest

from app import database
from tests.conftest import FakePool, auth_header, make_user_row


class StrictReleasePool(FakePool):
    """FakePool whose connection dies the moment it is handed back.

    acquire() marks the pool released on exit and every query method
    refuses to run after that, mirroring asyncpg's InterfaceError. Code
    that keeps a connection reference past its acquire() block cannot pass
    against this pool, exactly as it cannot pass against PostgreSQL.
    """

    def __init__(self):
        super().__init__()
        self._released = False

    def _guard(self):
        if self._released:
            raise RuntimeError(
                "cannot call Connection.fetchrow(): connection has been "
                "released back to the pool"
            )

    async def fetchrow(self, sql, *args):
        self._guard()
        return await super().fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        self._guard()
        return await super().fetch(sql, *args)

    async def fetchval(self, sql, *args):
        self._guard()
        return await super().fetchval(sql, *args)

    async def execute(self, sql, *args):
        self._guard()
        return await super().execute(sql, *args)

    def acquire(self):
        pool = self

        @asynccontextmanager
        async def _ctx():
            pool._released = False
            try:
                yield pool
            finally:
                pool._released = True

        return _ctx()


PROJECT_ROW = {
    "PROJ_ID": "TDAC-REG-001",
    "PROJ_NAME": "Regression Viaduct",
    "PROJ_LOC": "Kochi",
    "PROJ_CLNT": "KMRL",
    "PROJ_ENG": "Consultant LLP",
    "PROJ_CONT": "Contractor Pvt Ltd",
}


def _index_of_call(pool, method, substring):
    for index, (call_method, sql, _args) in enumerate(pool.calls):
        if call_method == method and substring in sql:
            return index
    raise AssertionError(
        f"no {method} call containing {substring!r} was recorded"
    )


def _create_payload(project_id="TDAC-REG-001"):
    return {
        "project_id": project_id,
        "project_name": "Regression Viaduct",
        "project_location": "Kochi",
        "project_client": "KMRL",
        "consultant_name": "Consultant LLP",
        "contractor_name": "Contractor Pvt Ltd",
        "metadata": {
            "road_reference": "NH-66",
            "chainage_text": "CH 10+000 to CH 12+500",
            "structure_reference": "Pier P12",
            "selected_boreholes": "BH-01, BH-02",
            "project_type": "LAB_AND_REPORT",
            "report_type": "Factual",
            "report_title": "GI Factual Report",
            "report_volume_title": "Volume I",
            "document_reference": "TDAC/REP/2026/01",
            "revision": "R0",
            "report_date": "2026-10-17",
            "issue_status": "Draft",
            "tdac_company_name": (
                "TDAC Geotechnical Solutions Private Limited"
            ),
            "groundwater_basis": "Observed during drilling",
        },
    }


def _overview_payload():
    return {
        "project_name": "Regression Viaduct",
        "project_location": "Kochi",
        "project_client": "KMRL",
        "consultant_name": "Consultant LLP",
        "contractor_name": "Contractor Pvt Ltd",
        "road_reference": "NH-66",
        "chainage_text": "CH 10+000 to CH 12+500",
        "structure_reference": "Pier P12",
        "selected_boreholes": "BH-01, BH-02",
        "report_type": "Factual",
        "report_title": "GI Factual Report",
        "report_volume_title": "Volume I",
        "document_reference": "TDAC/REP/2026/01",
        "revision": "R0",
        "report_date": "2026-10-17",
        "issue_status": "Draft",
        "tdac_company_name": (
            "TDAC Geotechnical Solutions Private Limited"
        ),
        "groundwater_basis": "Observed during drilling",
        "design_standard_basis": "",
        "factor_of_safety_basis": "",
        "load_combination_basis": "",
        "construction_verification_requirement": "",
        "pile_load_test_requirement": "",
    }


def _overview_row():
    return {
        "project_id": "TDAC-REG-001",
        "project_name": "Regression Viaduct",
        "project_location": "Kochi",
        "project_client": "KMRL",
        "consultant_name": "Consultant LLP",
        "contractor_name": "Contractor Pvt Ltd",
        "project_type": "LAB_AND_REPORT",
    }


def test_strict_pool_guard_mirrors_the_asyncpg_release_error():
    """Prove the guard is not vacuous: a post-release query must raise.

    Without this, the regression tests below could pass even if the pool
    silently tolerated use-after-release and the bug had simply returned.
    """

    async def scenario():
        pool = StrictReleasePool()

        async with pool.acquire() as connection:
            await connection.fetchrow("SELECT 1")

        with pytest.raises(RuntimeError, match="released back to the pool"):
            await connection.fetchrow("SELECT 2")

    asyncio.run(scenario())


def test_project_and_metadata_inserts_share_one_transaction(
    monkeypatch, client
):
    """PROJ and PROJ_METADATA must be written on one live connection.

    This is the regression guard for the released-connection bug: the old
    indentation ran the metadata insert after acquire() exited, which
    StrictReleasePool turns back into the asyncpg error and a 500.
    The ordering check additionally proves both inserts sit between
    BEGIN and COMMIT, so a future edit cannot quietly split them into
    two auto-committing statements.
    """
    pool = StrictReleasePool()
    pool.route("WHERE u.id", make_user_row())
    pool.route('INSERT INTO "ags42"."PROJ"', dict(PROJECT_ROW))
    pool.route(
        'INSERT INTO "tdac"."PROJ_METADATA"',
        {"PROJ_ID": "TDAC-REG-001"},
    )
    monkeypatch.setattr(database, "pool", pool)

    resp = client.post(
        "/api/portfolio/projects",
        json=_create_payload(),
        headers=auth_header(),
    )

    assert resp.status_code == 200
    assert resp.json()["project"]["project_number"] == "TDAC-REG-001"

    begin = _index_of_call(pool, "begin", "")
    commit = _index_of_call(pool, "commit", "")
    proj_insert = _index_of_call(
        pool, "fetchrow", 'INSERT INTO "ags42"."PROJ"'
    )
    meta_insert = _index_of_call(
        pool, "fetchrow", 'INSERT INTO "tdac"."PROJ_METADATA"'
    )

    assert begin < proj_insert < meta_insert < commit


def test_automatic_id_response_carries_the_allocated_number(
    monkeypatch, client
):
    """AUTO mode: the answer must name the number the server allocated.

    The form only previews the next free ID, so the client navigates with
    the response; if this ever returned the previewed value a parallel
    request could send the user to someone else's project.
    """
    pool = StrictReleasePool()
    pool.route("WHERE u.id", make_user_row())
    pool.route(
        'INSERT INTO "tdac"."PROJECT_ID_COUNTER"',
        {"LAST_NUMBER": 42},
    )
    pool.route(
        'INSERT INTO "ags42"."PROJ"',
        lambda *args: {**PROJECT_ROW, "PROJ_ID": args[0]},
    )
    pool.route(
        'INSERT INTO "tdac"."PROJ_METADATA"',
        {"PROJ_ID": "TDAC-AUTO"},
    )
    monkeypatch.setattr(database, "pool", pool)

    resp = client.post(
        "/api/portfolio/projects",
        json=_create_payload(project_id="AUTO"),
        headers=auth_header(),
    )

    today = date.today()
    expected = f"TDAC-{today.year:04d}-{today.month:02d}-42"

    assert resp.status_code == 200
    assert resp.json()["project"]["project_number"] == expected


def test_overview_update_answers_with_the_frontend_field_names(
    monkeypatch, client
):
    """The PATCH response must use the lowercase keys the header reads.

    It used to return bare PROJ_* columns, so the workspace header blanked
    every field to "—" the moment a save succeeded. The route below only
    matches the aliased SELECT: if someone drops the aliases again, the
    fake pool answers None, the endpoint turns that into a 404, and this
    test fails instead of the user seeing an emptied screen.
    """
    pool = StrictReleasePool()
    pool.route("WHERE u.id", make_user_row())
    pool.route("AS project_id", _overview_row())
    monkeypatch.setattr(database, "pool", pool)

    resp = client.patch(
        "/api/portfolio/projects/TDAC-REG-001/overview",
        json=_overview_payload(),
        headers=auth_header(),
    )

    assert resp.status_code == 200

    body = resp.json()
    assert body["project_name"] == "Regression Viaduct"
    assert body["project_location"] == "Kochi"
    assert body["project_client"] == "KMRL"
    assert body["consultant_name"] == "Consultant LLP"
    assert body["contractor_name"] == "Contractor Pvt Ltd"
    assert body["project_type"] == "LAB_AND_REPORT"

    # No raw database column names may leak into the HTTP contract.
    assert "PROJ_NAME" not in body
    assert "PROJ_ID" not in body
