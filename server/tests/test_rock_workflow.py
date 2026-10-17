"""Field Data > Rock: same workflow as SPT.

Drives the real router + service against FakePool (no live database) and
asserts on the SQL and bind parameters the service issues, like
test_spt_edit_approval.py. Covers: the AGS mapping, shared Sample ID
generator, PENDING / admin auto-approve, edit -> PENDING + audit, admin
approve/reject, delete, and Sampling & Coring > Rock being view-only.
"""
import json
from decimal import Decimal

from tests.conftest import (
    auth_header,
    make_engineer_row,
    make_user_row,
    route_users_by_id,
)

BASE = "/api/portfolio/projects/P1/locas/L1/field-data"
REGISTER = "/api/portfolio/projects/P1/sample-register"

# A 1.5 m run holding 138 cm of pieces in four blocks: 30 + 20 + 8 + 80.
#   Recovery = 138 / 150            = 92.00%
#   RQD      = (30 + 20 + 80) / 150 = 86.67%   (the 8 cm block is too short)
# The recovery/rqd that used to be typed into RUN are now what these pieces
# produce, so the numbers below are unchanged on purpose.
RUN = {
    "depth_from": 10.0,
    "depth_to": 11.5,
    "rock_type": "Fresh grey GRANITE",
    "lift_no": "2",
    "pieces": [30, 20, 8, 80],
    "piece_unit": "cm",
}


def _as_engineer(pool):
    route_users_by_id(pool, {5: make_engineer_row(id=5)})
    pool.route('"ags42"."LOCA"', 1)  # _require_loca


def _as_admin(pool):
    route_users_by_id(pool, {1: make_user_row(id=1)})
    pool.route('"ags42"."LOCA"', 1)


def _exec(pool, needle):
    return [c for c in pool.calls if c[0] == "execute" and needle in c[1]]


def _audit_actions(pool):
    return [c[2][3] for c in _exec(pool, "tdac.audit_log")]


def _audit_meta(pool, action):
    return [json.loads(c[2][4]) for c in _exec(pool, "tdac.audit_log") if c[2][3] == action]


class TestRockSubmit:
    def test_submit_maps_to_ags_and_goes_pending(self, client, pool):
        _as_engineer(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [RUN]},
        )

        assert response.status_code == 201, response.text

        # Run Depth From/To, Recovery, RQD -> CORE_TOP/BASE/PREC/RQD
        core = _exec(pool, 'INSERT INTO "ags42"."CORE"')
        assert len(core) == 1
        assert core[0][2] == (
            "P1", "L1",
            Decimal("10.0"), Decimal("11.5"), Decimal("92.00"), Decimal("86.67"),
        )

        # Type of Rock -> GEOL_DESC over CORE_TOP..CORE_BASE
        geol = _exec(pool, 'INSERT INTO "ags42"."GEOL"')
        assert len(geol) == 1
        assert geol[0][2] == (
            "P1", "L1", Decimal("10.0"), Decimal("11.5"), "Fresh grey GRANITE",
        )

        # Lift No / Length of pieces -> the new tdac table; no AGS column.
        rock = _exec(pool, 'INSERT INTO "tdac"."ROCK_RECORD"')
        assert len(rock) == 1
        args = rock[0][2]
        assert args[:4] == ("P1", "L1", Decimal("10.0"), "P1-1")
        assert args[4] == "PENDING"
        assert args[5] == "2"         # LIFT_NO
        assert args[6] == 5           # CREATED_BY
        assert args[7] is None and args[8] is None  # not approved yet

        # Each piece is its own row, numbered from 1 in entry order.
        pieces = [c for c in pool.calls if c[0] == "executemany" and "ROCK_PIECE" in c[1]]
        assert len(pieces) == 1
        assert pieces[0][2][0] == [
            ("P1", "L1", Decimal("10.0"), "P1-1", 1, Decimal("30")),
            ("P1", "L1", Decimal("10.0"), "P1-1", 2, Decimal("20")),
            ("P1", "L1", Decimal("10.0"), "P1-1", 3, Decimal("8")),
            ("P1", "L1", Decimal("10.0"), "P1-1", 4, Decimal("80")),
        ]

        assert "ROCK_SUBMITTED" in _audit_actions(pool)

    def test_sample_id_comes_from_the_shared_counter(self, client, pool):
        _as_engineer(pool)

        client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [RUN, {**RUN, "depth_from": 12, "depth_to": 14}]},
        )

        counter = pool.calls_with("fetchrow", '"tdac"."SAMPLE_ID_COUNTER"')
        assert len(counter) == 2, "one existing-generator call per Rock row"
        # No second generator / counter table is touched.
        assert not pool.calls_with("execute", "ROCK_ID_COUNTER")

    def test_admin_submission_is_auto_approved(self, client, pool):
        _as_admin(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=1),
            json={"records": [RUN]},
        )

        assert response.status_code == 201
        args = _exec(pool, 'INSERT INTO "tdac"."ROCK_RECORD"')[0][2]
        assert args[4] == "APPROVED"
        assert args[7] == 1  # APPROVED_BY = the submitting admin

    def test_existing_depth_returns_409_and_writes_nothing(self, client, pool):
        _as_engineer(pool)
        pool.route('SELECT 1 FROM "ags42"."CORE"', 1)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [RUN]},
        )

        assert response.status_code == 409
        assert not _exec(pool, 'INSERT INTO "ags42"."CORE"')
        assert not _exec(pool, 'INSERT INTO "tdac"."ROCK_RECORD"')
        # A rejected submit must not burn a Sample ID.
        assert not pool.calls_with("fetchrow", '"tdac"."SAMPLE_ID_COUNTER"')

    def test_depth_to_must_exceed_depth_from(self, client, pool):
        _as_engineer(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "depth_from": 5, "depth_to": 5}]},
        )

        assert response.status_code == 422
        assert not _exec(pool, 'INSERT INTO "ags42"."CORE"')

    def test_type_of_rock_is_required(self, client, pool):
        _as_engineer(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "rock_type": "   "}]},
        )

        assert response.status_code == 422

    def test_recovery_and_rqd_cannot_be_supplied_by_the_client(self, client, pool):
        """They are derived, so a client-chosen percentage is not accepted.

        Extra fields are ignored by default in this API, which is what makes
        this safe: a client still sending the old recovery/rqd cannot pin a
        value that disagrees with its own pieces.
        """

        _as_engineer(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "recovery": 120, "rqd": 5}]},
        )

        assert response.status_code == 201
        # The submitted 120 is ignored; the pieces decide.
        assert response.json()["records"][0]["recovery"] == 92.0

    def test_pieces_longer_than_the_run_are_rejected(self, client, pool):
        _as_engineer(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "pieces": [200], "piece_unit": "cm"}]},
        )

        assert response.status_code == 422

    def test_pieces_entered_in_metres_match_the_same_run_in_cm(self, client, pool):
        _as_engineer(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={
                "records": [
                    {
                        **RUN,
                        "pieces": [0.3, 0.2, 0.08, 0.8],
                        "piece_unit": "m",
                    }
                ]
            },
        )

        assert response.status_code == 201
        assert response.json()["records"][0]["recovery"] == 92.0


def _before(**overrides):
    row = {
        "depth_from": Decimal("10.0"),
        "depth_to": Decimal("11.5"),
        "recovery": Decimal("92.00"),
        "rqd": Decimal("86.67"),
        "rock_type": "Fresh grey GRANITE",
        "lift_no": "2",
        "sample_id": "P1-7",
        "status": "APPROVED",
    }
    row.update(overrides)
    return row


class TestRockIntervalOverlap:
    """A cored run cannot sit inside a soil stratum.

    The form only ever checked for a clash at the exact same top depth, so a
    run from 5 to 10 m was accepted next to a stratum from 3 to 6.5 m. The log
    then drew one bar on top of the other and the soil layer vanished.
    """

    # FakePool matches on a substring and does not evaluate the WHERE clause,
    # so each test states outright what the overlap lookup should return:
    # the straddling stratum, or None when the run clears it.
    OVERLAP_QUERY = '"GEOL_BASE" > $3'

    def _stratum(self, pool, top="3.00", base="6.50", desc="Soft Silty CLAY"):
        pool.route(
            self.OVERLAP_QUERY,
            {"GEOL_TOP": Decimal(top), "GEOL_BASE": Decimal(base), "GEOL_DESC": desc},
        )

    def _clear(self, pool):
        pool.route(self.OVERLAP_QUERY, None)

    def test_a_run_inside_a_stratum_is_refused(self, client, pool):
        _as_engineer(pool)
        self._stratum(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "depth_from": 5.0, "depth_to": 10.0}]},
        )

        assert response.status_code == 409
        detail = response.json()["detail"]
        # It must name both sides, or the user cannot tell what to change.
        assert "overlaps" in detail
        assert "Soft Silty CLAY" in detail
        assert "3.00" in detail and "6.50" in detail

    def test_a_run_entirely_below_the_stratum_is_fine(self, client, pool):
        _as_engineer(pool)
        self._clear(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "depth_from": 7.0, "depth_to": 9.0}]},
        )

        assert response.status_code == 201

    def test_a_run_entirely_above_the_stratum_is_fine(self, client, pool):
        _as_engineer(pool)
        self._clear(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "depth_from": 0.5, "depth_to": 2.0}]},
        )

        assert response.status_code == 201

    def test_touching_at_the_boundary_is_not_an_overlap(self, client, pool):
        """Intervals are half-open, so 3.00-6.50 and 6.50-9.00 merely touch."""
        _as_engineer(pool)
        self._clear(pool)

        response = client.post(
            f"{BASE}/rock/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{**RUN, "depth_from": 6.5, "depth_to": 9.0}]},
        )

        assert response.status_code == 201

    def test_editing_a_run_does_not_clash_with_its_own_geology_row(self, client, pool):
        """The Rock workflow writes a GEOL row for its own Type of Rock, so an
        edit must not be refused by the row it created."""
        _as_engineer(pool)
        pool.route("FOR UPDATE OF rr, c", _before())
        self._clear(pool)

        response = client.patch(
            f"{BASE}/rock/10.0",
            headers=auth_header(user_id=5),
            json={**RUN, "lift_no": "9"},
        )

        assert response.status_code == 200, response.text

    def test_editing_a_run_into_another_stratum_is_refused(self, client, pool):
        _as_engineer(pool)
        pool.route("FOR UPDATE OF rr, c", _before())
        self._stratum(pool, top="20.0", base="30.0", desc="Stiff Sandy CLAY")

        response = client.patch(
            f"{BASE}/rock/10.0",
            headers=auth_header(user_id=5),
            json={**RUN, "depth_from": 22.0, "depth_to": 25.0},
        )

        assert response.status_code == 409
        assert "Stiff Sandy CLAY" in response.json()["detail"]


class TestRockEdit:
    def test_non_admin_edit_returns_record_to_pending_and_audits(self, client, pool):
        _as_engineer(pool)
        pool.route("FOR UPDATE OF rr, c", _before())

        response = client.patch(
            f"{BASE}/rock/10.0",
            headers=auth_header(user_id=5),
            json={
                **RUN,
                "pieces": [30, 20, 80],
                "rock_type": "Weathered GRANITE",
            },
        )

        assert response.status_code == 200, response.text

        status = _exec(pool, 'UPDATE "tdac"."ROCK_RECORD"')
        assert len(status) == 1
        assert "'PENDING'" in status[0][1]
        assert '"APPROVED_BY" = NULL' in status[0][1]

        # CORE and the GEOL interval are kept in step with the run.
        assert len(_exec(pool, 'UPDATE "ags42"."CORE"')) == 1
        geol = _exec(pool, 'UPDATE "ags42"."GEOL"')
        assert len(geol) == 1
        assert geol[0][2][-1] == "Weathered GRANITE"

        # One audit row per changed field, keyed by the Sample ID.
        edits = _audit_meta(pool, "SAMPLE_EDITED")
        assert {e["field"] for e in edits} == {"pieces", "recovery", "rock_type"}
        assert all(e["sample_id"] == "P1-7" and e["source"] == "ROCK" for e in edits)

    def test_admin_edit_is_an_approval(self, client, pool):
        _as_admin(pool)
        pool.route("FOR UPDATE OF rr, c", _before(status="PENDING"))

        response = client.patch(
            f"{BASE}/rock/10.0",
            headers=auth_header(user_id=1),
            json={**RUN, "lift_no": "3"},
        )

        assert response.status_code == 200
        status = _exec(pool, 'UPDATE "tdac"."ROCK_RECORD"')[0]
        assert "'APPROVED'" in status[1]
        assert "ROCK_APPROVED" in _audit_actions(pool)

    def test_missing_or_legacy_record_returns_404(self, client, pool):
        _as_engineer(pool)
        pool.route("FOR UPDATE OF rr, c", None)  # no tdac.ROCK_RECORD row

        response = client.patch(
            f"{BASE}/rock/9.9",
            headers=auth_header(user_id=5),
            json=RUN,
        )

        assert response.status_code == 404
        assert not _exec(pool, 'UPDATE "ags42"."CORE"')

    def test_moving_to_an_occupied_depth_is_409(self, client, pool):
        _as_engineer(pool)
        pool.route("FOR UPDATE OF rr, c", _before())
        pool.route('SELECT 1 FROM "ags42"."GEOL"', 1)

        response = client.patch(
            f"{BASE}/rock/10.0",
            headers=auth_header(user_id=5),
            json={**RUN, "depth_from": 20, "depth_to": 22},
        )

        assert response.status_code == 409
        assert not _exec(pool, 'UPDATE "ags42"."CORE"')


class TestRockApproval:
    def test_approval_endpoints_are_admin_only(self, client, pool):
        _as_engineer(pool)

        for path in ("/rock/10.0/approve", "/rock/10.0/reject"):
            r = client.post(
                f"{BASE}{path}", headers=auth_header(user_id=5), json={}
            )
            assert r.status_code == 403, path

        assert client.get(
            f"{BASE}/rock/pending", headers=auth_header(user_id=5)
        ).status_code == 403

    def test_admin_approve(self, client, pool):
        _as_admin(pool)
        pool.route(
            'UPDATE "tdac"."ROCK_RECORD"',
            {"sample_id": "P1-7", "status": "APPROVED"},
        )

        r = client.post(f"{BASE}/rock/10.0/approve", headers=auth_header(user_id=1))

        assert r.status_code == 200
        assert r.json()["sample_id"] == "P1-7"
        sql = pool.calls_with("fetchrow", 'UPDATE "tdac"."ROCK_RECORD"')[0][1]
        assert "'PENDING'" in sql  # only a PENDING record can be approved
        assert "ROCK_APPROVED" in _audit_actions(pool)

    def test_admin_reject_records_reason(self, client, pool):
        _as_admin(pool)
        pool.route(
            'UPDATE "tdac"."ROCK_RECORD"',
            {"sample_id": "P1-7", "status": "REJECTED"},
        )

        r = client.post(
            f"{BASE}/rock/10.0/reject",
            headers=auth_header(user_id=1),
            json={"reason": "RQD looks wrong"},
        )

        assert r.status_code == 200
        assert _audit_meta(pool, "ROCK_REJECTED")[0]["reason"] == "RQD looks wrong"

    def test_approving_a_non_pending_record_is_404(self, client, pool):
        _as_admin(pool)
        pool.route('UPDATE "tdac"."ROCK_RECORD"', None)

        r = client.post(f"{BASE}/rock/10.0/approve", headers=auth_header(user_id=1))

        assert r.status_code == 404


class TestRockDelete:
    def test_delete_removes_run_geology_and_tdac_row(self, client, pool):
        _as_engineer(pool)
        pool.route(
            'AS sample_id',
            {**_before(), "sample_id": "P1-7"},
        )
        pool.route('DELETE FROM "tdac"."ROCK_RECORD"', "DELETE 1")

        r = client.delete(f"{BASE}/rock/10.0", headers=auth_header(user_id=5))

        assert r.status_code == 200
        assert len(_exec(pool, 'DELETE FROM "ags42"."CORE"')) == 1
        assert len(_exec(pool, 'DELETE FROM "ags42"."GEOL"')) == 1
        assert len(_exec(pool, 'DELETE FROM "tdac"."ROCK_RECORD"')) == 1
        assert _audit_meta(pool, "SAMPLE_DELETED")[0]["source"] == "ROCK"

    def test_legacy_core_row_is_never_deleted(self, client, pool):
        _as_engineer(pool)
        pool.route('AS sample_id', None)  # no tdac.ROCK_RECORD row

        r = client.delete(f"{BASE}/rock/10.0", headers=auth_header(user_id=5))

        assert r.status_code == 404
        assert not _exec(pool, 'DELETE FROM "ags42"."CORE"')


class TestSamplingRockIsViewOnly:
    """The view-only guarantees, now covered on the Lab Data Sample Register.

    These used to assert against Field Data's GET .../field-data/sampling.
    That route is gone; the register is served by one project-scoped endpoint
    in portfolio_router, so the same guarantees are asserted there.
    """

    def test_lists_only_approved_rock_records_with_sample_id(self, client, pool):
        _as_engineer(pool)
        pool.route(
            'FROM "tdac"."ROCK_RECORD"',
            [
                {
                    "loca_id": "L1",
                    "sample_id": "P1-7",
                    "depth_from": Decimal("10.0"),
                    "depth_to": Decimal("11.5"),
                    "rock_description": "Fresh grey GRANITE",
                    "recovery": Decimal("92"),
                    "rqd": Decimal("70"),
                    "remark": None,
                    "lift_no": "2",
                    "created_by": "enguser",
                    "created_at": None,
                }
            ],
        )

        r = client.get(REGISTER, headers=auth_header(user_id=5))

        assert r.status_code == 200
        record = r.json()["rock"][0]
        assert record["sample_id"] == "P1-7"
        assert record["loca_id"] == "L1"
        assert record["lift_no"] == "2"
        # The redundant total is gone; Recovery/RQD are derived from pieces.
        assert "piece_length_cm" not in record

        sql = pool.calls_with("fetch", '"ROCK_RECORD"')[0][1]
        assert "'APPROVED'" in sql
        # Legacy CORE rows without a Rock record cannot appear.
        assert 'JOIN "ags42"."CORE"' in sql

    def test_no_add_edit_delete_endpoints_and_no_sample_id_generation(
        self, client, pool
    ):
        _as_engineer(pool)
        h = auth_header(user_id=5)

        # The collection path still exists (GET), so a write is method-not-allowed;
        # the item path has no route at all, so it is simply not found. Both prove
        # there is no write endpoint.
        assert client.post(REGISTER, headers=h, json=RUN).status_code == 405
        assert client.patch(f"{REGISTER}/10.0", headers=h, json=RUN).status_code == 404
        assert client.delete(f"{REGISTER}/10.0", headers=h).status_code == 404
        assert not pool.calls_with("fetchrow", '"tdac"."SAMPLE_ID_COUNTER"')

    def test_the_old_per_location_sampling_route_is_gone(self, client, pool):
        """Field Data's per-location view was replaced by the register.

        Guards against the dead route creeping back, and documents why the
        Sample Register is the only reader of approved Rock records.
        """
        _as_engineer(pool)

        assert client.get(f"{BASE}/sampling", headers=auth_header(user_id=5)).status_code == 404
        assert client.get(f"{BASE}/soil", headers=auth_header(user_id=5)).status_code == 404
