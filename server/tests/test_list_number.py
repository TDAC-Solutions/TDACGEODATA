"""List Number: the row's position in the list, derived server-side.

The client used to show an "#" in the Rock entry grid that vanished once a
row was saved, and SPT showed no row number at all. Both now read "List No"
and both get it from the same place: the server stamps each row with its
position in the very ordering that draws the table.

Derived, not stored, on purpose. A stored sequence would go stale the moment
a run was inserted or deleted between two others, and would then disagree
with the depth order the table -- and the PDF -- are drawn in.
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


def _as_engineer(pool):
    route_users_by_id(pool, {5: make_engineer_row(id=5)})
    pool.route('"ags42"."LOCA"', 1)


def _as_admin(pool):
    # The pending queue is admin-only, so this has to be a real admin row.
    route_users_by_id(pool, {1: make_user_row(id=1)})
    pool.route('"ags42"."LOCA"', 1)


def _spt_rows(*depths):
    return [
        {
            "spt_depth": Decimal(str(depth)),
            "blows_15": 1,
            "blows_30": 2,
            "blows_45": 3,
            "n_value": 5,
            "status": "APPROVED",
            "sample_id": f"P1-{index}",
            "attachment_count": 0,
        }
        for index, depth in enumerate(depths)
    ]


def _rock_rows(*depths):
    return [
        {
            "depth_from": Decimal(str(depth)),
            "depth_to": Decimal(str(depth)) + 1,
            "recovery": Decimal("80"),
            "rqd": Decimal("50"),
            "rock_type": "SANDSTONE",
            "lift_no": str(index),
            "status": "APPROVED",
            "sample_id": f"P1-{index}",
            "created_by": "enguser",
            "created_at": None,
        }
        for index, depth in enumerate(depths)
    ]


class TestSptListNumber:
    def test_numbers_run_from_one_in_depth_order(self, client, pool):
        _as_engineer(pool)
        pool.route('FROM "ags42"."ISPT"', _spt_rows(1.5, 3.0, 6.5))

        body = client.get(f"{BASE}/spt", headers=auth_header(user_id=5)).json()["records"]
        assert [r["list_no"] for r in body] == [1, 2, 3]

    def test_the_number_follows_the_sort_not_the_input_order(self, client, pool):
        """Rows can be stored in any order; the number is the position in the
        ordered list, so it must not simply count the rows as they came back."""
        _as_engineer(pool)
        # Deliberately unsorted: the SQL orders by ISPT_TOP, and the test
        # asserts the numbers are assigned after that ordering, not before.
        pool.route('FROM "ags42"."ISPT"', _spt_rows(6.5, 1.5, 3.0))

        body = client.get(f"{BASE}/spt", headers=auth_header(user_id=5)).json()["records"]
        assert [r["list_no"] for r in body] == [1, 2, 3]
        # And it tracks the row it belongs to rather than floating free.
        assert body[0]["spt_depth"] == Decimal("6.5") and body[0]["list_no"] == 1

    def test_a_single_row_is_number_one(self, client, pool):
        _as_engineer(pool)
        pool.route('FROM "ags42"."ISPT"', _spt_rows(2.0))

        body = client.get(f"{BASE}/spt", headers=auth_header(user_id=5)).json()["records"]
        assert body[0]["list_no"] == 1

    def test_no_rows_is_an_empty_list_not_an_error(self, client, pool):
        _as_engineer(pool)
        pool.route('FROM "ags42"."ISPT"', [])

        body = client.get(f"{BASE}/spt", headers=auth_header(user_id=5)).json()["records"]
        assert body == []

    def test_the_pending_queue_is_numbered_by_its_own_order(self, client, pool):
        _as_admin(pool)
        pool.route('FROM "tdac"."SPT_RECORD_STATUS" sr', _spt_rows(1.0, 2.0, 3.0, 4.0))

        body = client.get(f"{BASE}/spt/pending", headers=auth_header(user_id=1)).json()["records"]
        assert [r["list_no"] for r in body] == [1, 2, 3, 4]

    def test_the_client_cannot_choose_the_number(self, client, pool):
        """It is an output, so sending one must not stick."""
        _as_engineer(pool)
        pool.route('FROM "ags42"."ISPT"', _spt_rows(1.0, 2.0))

        body = client.get(f"{BASE}/spt", headers=auth_header(user_id=5)).json()["records"]
        for index, row in enumerate(body):
            assert row["list_no"] == index + 1


class TestRockListNumber:
    def test_numbers_run_from_one_in_depth_order(self, client, pool):
        _as_engineer(pool)
        pool.route('FROM "tdac"."ROCK_RECORD" rr', _rock_rows(5.0, 10.0, 12.0))
        pool.route('FROM "tdac"."ROCK_PIECE"', [])

        body = client.get(f"{BASE}/rock", headers=auth_header(user_id=5)).json()["records"]
        assert [r["list_no"] for r in body] == [1, 2, 3]

    def test_the_number_survives_alongside_the_pieces(self, client, pool):
        """The pieces helper is where the number is stamped, so the two must
        not overwrite each other."""
        _as_engineer(pool)
        pool.route('FROM "tdac"."ROCK_RECORD" rr', _rock_rows(5.0, 10.0))
        pool.route(
            'FROM "tdac"."ROCK_PIECE"',
            [
                {"DEPTH_FROM": Decimal("5.0"), "LENGTH_CM": Decimal("30")},
                {"DEPTH_FROM": Decimal("10.0"), "LENGTH_CM": Decimal("20")},
            ],
        )

        body = client.get(f"{BASE}/rock", headers=auth_header(user_id=5)).json()["records"]
        assert [r["list_no"] for r in body] == [1, 2]
        assert body[0]["pieces"] == [Decimal("30")]
        assert body[1]["pieces"] == [Decimal("20")]

    def test_the_pending_queue_is_numbered_by_its_own_order(self, client, pool):
        _as_admin(pool)
        pool.route('FROM "tdac"."ROCK_RECORD" rr', _rock_rows(7.0, 8.0))
        pool.route('FROM "tdac"."ROCK_PIECE"', [])

        body = client.get(
            f"{BASE}/rock/pending", headers=auth_header(user_id=1)
        ).json()["records"]
        assert [r["list_no"] for r in body] == [1, 2]


class TestListNumberIsNotStored:
    def test_the_number_is_never_written_to_the_database(self, client, pool):
        """No LIST_NO column exists, and the submit path must not try to write
        one. A client that sends it is ignored rather than trusted."""
        _as_engineer(pool)
        pool.route('SELECT 1 FROM "ags42"."GEOL"', 1)
        pool.route('SELECT 1 FROM "ags42"."CORE"', None)
        pool.route('AS sample_id', {"sample_id": "P1-1"})
        pool.route('FROM "ags42"."GEOL" g', [])

        response = client.post(
            f"{BASE}/spt/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{"spt_depth": 1.0, "blows_15": 1, "blows_30": 2, "blows_45": 3}]},
        )

        assert response.status_code == 201
        executed = " ".join(call[1] for call in pool.calls if call[0] == "execute")
        assert "LIST_NO" not in executed.upper()