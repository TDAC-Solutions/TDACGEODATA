"""Contract tests for the Add Location / Investigation Summary work.

Feature 13: the overview summary is derived from LOCA records, so the read
endpoint has to hand back every field that summary renders.
Feature 14: the location type is a fixed dropdown, so whatever string the
client sends has to survive the round trip untouched.
Feature 15: the extra survey fields persist into their AGS columns, and the
groundwater depth persists as a WSTG water-strike row.

These assert the app contract, not framework status codes for auth.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from tests.conftest import auth_header, make_user_row, route_users_by_id


PROJ = "P1"


def _auth(pool, user_id=5):
    """Route the auth lookup that get_current_user runs before the handler.

    Without a user row the dependency rejects the request as unauthorised,
    which would mask every assertion about the location payload.
    """
    route_users_by_id(
        pool, {user_id: make_user_row(id=user_id, role_id=2, role_name="engineer")}
    )
    return auth_header(user_id=user_id)


def _loca_row(**overrides):
    """A LOCA row as asyncpg returns it: uppercase keys, Decimal numerics."""
    row = {
        "LOCA_ID": "BH-01",
        "LOCA_TYPE": "BH",
        "LOCA_FDEP": Decimal("23.45"),
        "LOCA_STAR": datetime(2026, 10, 2, tzinfo=timezone.utc),
        "LOCA_ENDD": datetime(2026, 10, 3, tzinfo=timezone.utc),
        "LOCA_GL": Decimal("3.420"),
        "LOCA_NATE": Decimal("384512.235"),
        "LOCA_NATN": Decimal("1098776.412"),
        "LOCA_LAT": "9.9312",
        "LOCA_LON": "76.2673",
        "PROJ_ID": PROJ,
        "groundwater_depth": Decimal("1.20"),
    }
    row.update(overrides)
    return row


def _new_location_payload(**overrides):
    payload = {
        "loca_id": "BH-01",
        "loca_type": "BH",
        "start_date": "2026-10-02",
        "end_date": "2026-10-03",
        "final_depth": 23.45,
        "ground_level": 3.42,
        "easting": 384512.235,
        "northing": 1098776.412,
        "latitude": "9.9312",
        "longitude": "76.2673",
        "groundwater_depth": 1.2,
    }
    payload.update(overrides)
    return payload


class TestLocationFields:
    def test_create_returns_every_new_field(self, client, pool):
        pool.route("INSERT INTO", lambda *a: _loca_row())

        response = client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        )

        assert response.status_code == 200
        loca = response.json()["loca"]

        assert loca["ground_level"] == 3.42
        assert loca["easting"] == 384512.235
        assert loca["northing"] == 1098776.412
        assert loca["latitude"] == "9.9312"
        assert loca["longitude"] == "76.2673"
        assert loca["groundwater_depth"] == 1.2

    def test_numeric_fields_are_json_numbers_not_strings(self, client, pool):
        """A Decimal must not reach the client as a string, or the overview
        summary cannot do arithmetic on it."""
        pool.route("INSERT INTO", lambda *a: _loca_row())

        response = client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        )

        loca = response.json()["loca"]

        for field in (
            "final_depth",
            "ground_level",
            "easting",
            "northing",
            "groundwater_depth",
        ):
            assert isinstance(loca[field], float), f"{field} was {loca[field]!r}"

    def test_create_binds_the_new_columns(self, client, pool):
        pool.route("INSERT INTO", lambda *a: _loca_row())

        client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        )

        args = pool.last_args("fetchrow", "INSERT INTO")
        sql = pool.calls_with("fetchrow", "INSERT INTO")[-1][1]

        for column in ("LOCA_GL", "LOCA_NATE", "LOCA_NATN", "LOCA_LAT", "LOCA_LON"):
            assert column in sql, f"{column} missing from the LOCA insert"

        # Bind order must follow the VALUES list: id, type, start, end,
        # depth, RL, easting, northing, lat, lon, project.
        assert args[0] == "BH-01"
        assert args[1] == "BH"
        assert args[2] == date(2026, 10, 2)
        assert args[5] == Decimal("3.42")
        assert args[6] == Decimal("384512.235")
        assert args[7] == Decimal("1098776.412")
        assert args[8] == "9.9312"
        assert args[9] == "76.2673"
        assert args[10] == PROJ

    def test_omitted_survey_fields_persist_as_null(self, client, pool):
        """A borehole recorded before the survey arrives must store NULL,
        not a fabricated zero for RL, easting or northing."""
        pool.route("INSERT INTO", lambda *a: _loca_row(**{
            "LOCA_GL": None,
            "LOCA_NATE": None,
            "LOCA_NATN": None,
            "LOCA_LAT": None,
            "LOCA_LON": None,
            "groundwater_depth": None,
        }))

        response = client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json={
                "loca_id": "BH-02",
                "loca_type": "BH",
                "start_date": None,
                "end_date": None,
                "final_depth": None,
                "ground_level": None,
                "easting": None,
                "northing": None,
                "latitude": None,
                "longitude": None,
                "groundwater_depth": None,
            },
        )

        assert response.status_code == 200
        loca = response.json()["loca"]

        assert loca["ground_level"] is None
        assert loca["easting"] is None
        assert loca["northing"] is None
        assert loca["groundwater_depth"] is None

    def test_list_returns_every_new_field(self, client, pool):
        pool.route("FROM \"ags42\".\"LOCA\"", lambda *a: [_loca_row()])

        response = client.get(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
        )

        assert response.status_code == 200
        loca = response.json()["locas"][0]

        assert loca["ground_level"] == 3.42
        assert loca["easting"] == 384512.235
        assert loca["northing"] == 1098776.412
        assert loca["latitude"] == "9.9312"
        assert loca["longitude"] == "76.2673"
        assert loca["groundwater_depth"] == 1.2

    def test_list_and_create_agree_on_shape(self, client, pool):
        """Both endpoints must expose the same keys, otherwise the client
        gets a record that is missing fields the other path returns."""
        pool.route("FROM \"ags42\".\"LOCA\"", lambda *a: [_loca_row()])

        listed = client.get(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
        ).json()["locas"][0]

        pool.route("INSERT INTO", lambda *a: _loca_row())
        created = client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        ).json()["loca"]

        assert set(listed) == set(created)

    def test_missing_depth_reports_as_null_not_zero(self, client, pool):
        """Feature 13 excludes unsurveyed locations from the depth range,
        which only works if an unknown depth is null rather than 0."""
        pool.route("FROM \"ags42\".\"LOCA\"", lambda *a: [
            _loca_row(LOCA_ID="BH-01", LOCA_FDEP=Decimal("23.45")),
            _loca_row(LOCA_ID="BH-02", LOCA_FDEP=None),
        ])

        response = client.get(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
        )

        by_id = {l["loca_id"]: l for l in response.json()["locas"]}

        assert by_id["BH-01"]["final_depth"] == 23.45
        assert by_id["BH-02"]["final_depth"] is None


class TestLocationType:
    def test_dropdown_type_round_trips(self, client, pool):
        pool.route("INSERT INTO", lambda *a: _loca_row(LOCA_TYPE="SPT"))

        response = client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(loca_type="SPT"),
        )

        assert response.json()["loca"]["loca_type"] == "SPT"

    def test_existing_type_still_readable(self, client, pool):
        """Standardisation must not hide locations recorded before the
        dropdown existed."""
        pool.route("FROM \"ags42\".\"LOCA\"", lambda *a: [
            _loca_row(LOCA_TYPE="BH"),
            _loca_row(LOCA_ID="BH-02", LOCA_TYPE="Trial Pit"),
        ])

        response = client.get(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
        )

        types = [l["loca_type"] for l in response.json()["locas"]]

        assert types == ["BH", "Trial Pit"]


class TestGroundwaterStrike:
    def test_groundwater_writes_a_wstg_row(self, client, pool):
        pool.route("INSERT INTO", lambda *a: _loca_row())

        client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        )

        args = pool.last_args("execute", "WSTG")
        sql = pool.calls_with("execute", "WSTG")[-1][1]

        assert "WSTG_DPTH" in sql
        assert Decimal("1.2") in args
        assert PROJ in args and "BH-01" in args

    def test_no_groundwater_means_no_strike_row(self, client, pool):
        """Writing a null strike would record a water level that was never
        observed, so the insert must be skipped entirely."""
        pool.route("INSERT INTO", lambda *a: _loca_row())

        client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(groundwater_depth=None),
        )

        assert not pool.calls_with("execute", "WSTG")

    def test_repeated_strike_is_idempotent(self, client, pool):
        """uq_wstg_identity is the uniqueness guard, so re-saving the same
        strike must be an explicit no-op rather than an arbitrary
        conflict target that silently swallows a different mistake."""
        pool.route("INSERT INTO", lambda *a: _loca_row())

        client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        )

        sql = pool.calls_with("execute", "WSTG")[-1][1]

        assert 'ON CONFLICT ("PROJ_ID", "LOCA_ID", "WSTG_DPTH")' in sql


class TestLocationWritesAreAtomic:
    def test_both_writes_run_inside_one_transaction(self, client, pool):
        """The LOCA row and its WSTG strike are two statements on the same
        connection, so both must sit inside an explicit transaction.

        Without it, pool.acquire hands back a raw connection where every
        statement auto-commits separately: a rejected strike would leave the
        location committed while the caller saw an error, and the retry would
        then fail on the duplicate key instead of succeeding.
        """
        pool.route("INSERT INTO", lambda *a: _loca_row())

        client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        )

        order = [c[0] for c in pool.calls if c[0] in ("begin", "commit")]

        assert "begin" in order, f"no transaction opened: {order}"
        assert "commit" in order, f"no transaction committed: {order}"

        # Both inserts happen between BEGIN and COMMIT, never straddling it.
        methods = [c[0] for c in pool.calls]
        begin_at = methods.index("begin")
        commit_at = methods.index("commit")

        assert begin_at < commit_at
        assert "fetchrow" in methods[begin_at + 1 : commit_at]
        assert "execute" in methods[begin_at + 1 : commit_at]

    def test_transaction_covers_the_strike_too(self, client, pool):
        """The strike must not be written after the transaction closes, or
        it escapes the rollback the comment promises."""
        pool.route("INSERT INTO", lambda *a: _loca_row())

        client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(),
        )

        calls = pool.calls
        begin_at = [i for i, c in enumerate(calls) if c[0] == "begin"][0]
        commit_at = [i for i, c in enumerate(calls) if c[0] == "commit"][0]
        strike_at = [i for i, c in enumerate(calls) if "WSTG" in c[1]][0]

        assert begin_at < strike_at < commit_at

    def test_transaction_opened_even_without_a_strike(self, client, pool):
        """A location with no groundwater strike is a single statement, but
        it still runs inside the transaction so both paths behave the same
        way and a future statement cannot be added outside it by accident."""
        pool.route("INSERT INTO", lambda *a: _loca_row())

        client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(groundwater_depth=None),
        )

        assert "begin" in [c[0] for c in pool.calls]


class TestValidation:
    def test_negative_final_depth_rejected(self, client, pool):
        response = client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(final_depth=-1),
        )

        assert response.status_code == 422

    def test_negative_groundwater_rejected(self, client, pool):
        response = client.post(
            f"/api/portfolio/projects/{PROJ}/locas",
            headers=_auth(pool),
            json=_new_location_payload(groundwater_depth=-0.5),
        )

        assert response.status_code == 422
