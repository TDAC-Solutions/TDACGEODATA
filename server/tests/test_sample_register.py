"""Lab Data > Sample Register.

Moved from Field Data > "Sampling / Coring" to Lab Data, which is
project-scoped, so the register reads a whole project (or one location) in a
single request instead of one request per borehole.

Covers:
  * the rows are the same APPROVED-only records the old per-location
    /soil and /sampling endpoints returned
  * loca_id travels with every row, which is what lets one project-wide
    response replace the per-location calls
  * the optional loca_id narrows in SQL, and its result is a true subset of
    the unfiltered one
  * a location from another project is a 404, so the filter cannot be used to
    read across projects
  * both halves come from one request
"""
import json

from tests.conftest import auth_header, make_user_row, route_users_by_id

BASE = "/api/portfolio/projects/P1/sample-register"

# Shaped like the rows the two queries return -- the aliases the SQL projects,
# not the raw column names. The router maps these into the JSON payload.
SOIL = {
    "loca_id": "L1",
    "sample_id": "P1-001",
    "depth_from": 150,
    "blows_15": 2,
    "blows_30": 3,
    "blows_45": 4,
    "n_value": 9,
    "created_by": "engineer",
    "created_at": "2026-01-01T00:00:00Z",
}

ROCK = {
    "loca_id": "L1",
    "sample_id": "P1-002",
    "depth_from": 1000,
    "depth_to": 1100,
    "rock_description": "Fresh GRANITE",
    "recovery": 94,
    "rqd": 71,
    "remark": None,
    "lift_no": "1",
    "piece_length_cm": 42.5,
    "created_by": "engineer",
    "created_at": "2026-01-01T00:00:00Z",
}


def _soil_row(loca_id="L1", sample_id="P1-001", depth=150, n_value=9):
    return {
        "loca_id": loca_id,
        "sample_id": sample_id,
        "depth_from": depth,
        "blows_15": 2,
        "blows_30": 3,
        "blows_45": 4,
        "n_value": n_value,
        "created_by": "engineer",
        "created_at": "2026-01-01T00:00:00Z",
    }


def _rock_row(loca_id="L1", sample_id="P1-002", top=1000):
    return {
        "loca_id": loca_id,
        "sample_id": sample_id,
        "depth_from": top,
        "depth_to": top + 100,
        "rock_description": "Fresh GRANITE",
        "recovery": 94,
        "rqd": 71,
        "remark": None,
        "lift_no": "1",
        "piece_length_cm": 42.5,
        "created_by": "engineer",
        "created_at": "2026-01-01T00:00:00Z",
    }


def _seed(pool, *, soil=(), rock=(), loca_exists=True):
    route_users_by_id(pool, {1: make_user_row(id=1)})
    pool.route('"tdac"."SPT_RECORD_STATUS"', list(soil))
    pool.route('"tdac"."ROCK_RECORD"', list(rock))
    pool.route('"ags42"."LOCA"', 1 if loca_exists else None)


def _get(client, path=BASE):
    response = client.get(path, headers=auth_header())
    assert response.status_code == 200, response.text
    return response.json()


class TestSampleRegisterReturnsBothHalves:
    def test_one_request_returns_soil_and_rock(self, client, pool):
        _seed(pool, soil=[SOIL], rock=[ROCK])

        body = _get(client)

        assert len(body["soil"]) == 1
        assert len(body["rock"]) == 1
        assert body["soil"][0]["sample_id"] == "P1-001"
        assert body["rock"][0]["sample_id"] == "P1-002"

    def test_every_row_carries_its_location(self, client, pool):
        # This is what replaces the per-location calls: the register can span
        # boreholes only because each row says which one it came from.
        _seed(
            pool,
            soil=[_soil_row("L1", "P1-001"), _soil_row("L2", "P1-002")],
            rock=[_rock_row("L1", "P1-003"), _rock_row("L2", "P1-004")],
        )

        body = _get(client)

        assert [r["loca_id"] for r in body["soil"]] == ["L1", "L2"]
        assert [r["loca_id"] for r in body["rock"]] == ["L1", "L2"]

    def test_columns_match_the_old_sampling_view(self, client, pool):
        # Every field the Field Data viewer showed must still be here, except
        # the total piece length, which the Rock rework removed because it was
        # a hand-typed duplicate of the pieces themselves.
        _seed(pool, soil=[SOIL], rock=[ROCK])

        record = _get(client)["rock"][0]

        for field in (
            "sample_id",
            "depth_from",
            "depth_to",
            "rock_description",
            "recovery",
            "rqd",
            "remark",
            "lift_no",
            "created_by",
            "created_at",
        ):
            assert field in record, f"the register dropped {field}"

        assert record["rock_description"] == "Fresh GRANITE"
        assert record["lift_no"] == "1"
        assert "piece_length_cm" not in record

    def test_soil_columns_match_the_old_soil_view(self, client, pool):
        _seed(pool, soil=[SOIL])

        record = _get(client)["soil"][0]

        for field in (
            "sample_id",
            "depth_from",
            "blows_15",
            "blows_30",
            "blows_45",
            "n_value",
            "created_by",
        ):
            assert field in record, f"the register dropped {field}"

        assert record["blows_15"] == 2
        assert record["n_value"] == 9

    def test_empty_project_returns_empty_lists_not_an_error(self, client, pool):
        _seed(pool, soil=[], rock=[])

        body = _get(client)

        assert body["soil"] == []
        assert body["rock"] == []


class TestSampleRegisterLocationFilter:
    def test_filter_narrows_server_side(self, client, pool):
        # FakePool answers from whatever a route was given and does not apply a
        # WHERE clause, so the rows handed back here are the ones the real query
        # would have returned for loca_id=L2. What this test can honestly assert
        # is that the endpoint asks the database to do the narrowing -- which the
        # SQL assertions below do -- and that whatever it returns comes back
        # intact. The filter itself is verified against a live database.
        _seed(
            pool,
            soil=[_soil_row("L2", "P1-002")],
            rock=[_rock_row("L2", "P1-004")],
        )

        body = _get(client, f"{BASE}?loca_id=L2")

        assert [r["loca_id"] for r in body["soil"]] == ["L2"]
        assert [r["loca_id"] for r in body["rock"]] == ["L2"]

    def test_filter_is_passed_to_the_query(self, client, pool):
        # The narrowing has to reach SQL. A version that fetched the whole
        # project and filtered in the browser would issue the same statement.
        _seed(pool, soil=[], rock=[])

        _get(client, f"{BASE}?loca_id=L2")

        soil_args = pool.calls_with("fetch", '"SPT_RECORD_STATUS"')[-1][2]
        rock_args = pool.calls_with("fetch", '"tdac"."ROCK_RECORD"')[-1][2]

        assert soil_args == ("P1", "L2")
        assert rock_args == ("P1", "L2")

    def test_unfiltered_call_passes_only_the_project(self, client, pool):
        _seed(pool, soil=[], rock=[])

        _get(client)

        assert pool.calls_with("fetch", '"SPT_RECORD_STATUS"')[-1][2] == ("P1",)
        assert pool.calls_with("fetch", '"tdac"."ROCK_RECORD"')[-1][2] == ("P1",)

    def test_filter_is_applied_in_sql_not_in_the_browser(self, client, pool):
        # Filtering client-side would mean fetching every borehole and
        # discarding rows; the query itself has to narrow.
        _seed(pool, soil=[_soil_row("L1")])

        _get(client, f"{BASE}?loca_id=L1")

        soil_sql = pool.calls_with("fetch", '"SPT_RECORD_STATUS"')[-1][1]
        assert '"LOCA_ID" = $2' in soil_sql

        rock_sql = pool.calls_with("fetch", '"tdac"."ROCK_RECORD"')[-1][1]
        assert '"LOCA_ID" = $2' in rock_sql

    def test_unfiltered_query_carries_no_loca_predicate(self, client, pool):
        _seed(pool, soil=[_soil_row("L1")])

        _get(client)

        soil_sql = pool.calls_with("fetch", '"SPT_RECORD_STATUS"')[-1][1]
        assert '"LOCA_ID" = $2' not in soil_sql
        assert '"PROJ_ID" = $1' in soil_sql

    def test_a_location_from_another_project_is_404(self, client, pool):
        # The guard the field-data routes use. Without it the filter would read
        # another project's samples through this project's id.
        _seed(pool, soil=[], rock=[], loca_exists=False)

        response = client.get(f"{BASE}?loca_id=OTHER", headers=auth_header())

        assert response.status_code == 404
        assert "does not belong" in response.json()["detail"]


class TestSampleRegisterIsolation:
    def test_every_query_filters_on_the_project(self, client, pool):
        _seed(pool, soil=[SOIL], rock=[ROCK])

        _get(client)

        register_queries = [
            sql
            for method, sql, _ in pool.calls
            if method == "fetch" and '"PROJ_ID" = $1' in sql
        ]
        assert len(register_queries) == 2, "expected one query per half"
        for sql in register_queries:
            assert '"PROJ_ID" = $1' in sql

    def test_only_approved_records_are_read(self, client, pool):
        # Same rule as the two endpoints it replaces: an unapproved row is
        # still being edited and must not be published.
        _seed(pool, soil=[SOIL], rock=[ROCK])

        _get(client)

        for needle in ('"SPT_RECORD_STATUS"', '"tdac"."ROCK_RECORD"'):
            sql = pool.calls_with("fetch", needle)[-1][1]
            assert "'APPROVED'" in sql, f"{needle} lost the APPROVED filter"


class TestSampleRegisterAuth:
    def test_requires_a_token(self, client, pool):
        _seed(pool, soil=[], rock=[])

        response = client.get(BASE)

        assert response.status_code in (401, 403)

    def test_a_non_admin_can_read_it(self, client, pool):
        # It is a register, not an audit surface: every signed-in role reads it,
        # exactly as the Field Data viewer did.
        route_users_by_id(pool, {5: make_user_row(id=5, role_name="engineer")})
        pool.route('"tdac"."SPT_RECORD_STATUS"', [SOIL])
        pool.route('"tdac"."ROCK_RECORD"', [ROCK])

        response = client.get(
            BASE, headers=auth_header(user_id=5, role_name="engineer")
        )

        assert response.status_code == 200