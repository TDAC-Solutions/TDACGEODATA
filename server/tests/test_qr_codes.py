"""Sample Register QR codes.

The payload is built and the symbol is drawn server-side. That is not an
implementation detail: the QR has to name the same sample the register above
it shows, and the browser must not get to decide what a code says. These
tests pin the parts that would silently rot -- the payload shape, the scope
and location filters, and the project guard.
"""
import json
from decimal import Decimal

import pytest

from app.qr_service import (
    SCHEMA_VERSION,
    attach_qr_codes,
    build_payload,
    generate_svg_data_url,
)
from tests.conftest import auth_header, make_user_row, route_users_by_id

BASE = "/api/portfolio/projects/P1/sample-register/qr"


def _as_admin(pool):
    route_users_by_id(pool, {1: make_user_row(id=1)})
    pool.route('"ags42"."LOCA"', 1)


def _sample(kind="rock", sample_id="P1-1", loca_id="BH-1", depth_from=5, depth_to=10):
    return {
        "kind": kind,
        "sample_id": sample_id,
        "loca_id": loca_id,
        "depth_from": depth_from,
        "depth_to": depth_to,
    }


class TestPayload:
    def test_the_payload_is_compact_json(self):
        payload = build_payload("P1", _sample())

        assert " " not in payload
        assert json.loads(payload) == {
            "v": SCHEMA_VERSION,
            "t": "sample",
            "p": "P1",
            "l": "BH-1",
            "s": "P1-1",
            "k": "rock",
        }

    def test_the_payload_carries_the_schema_version(self):
        """So a scanner meeting an unknown version can refuse rather than
        mis-parse it."""
        payload = json.loads(build_payload("P1", _sample()))

        assert payload["v"] == SCHEMA_VERSION
        assert payload["t"] == "sample"

    def test_a_location_with_a_space_survives(self):
        """boreholes are keyed by strings like "BH 2", not just "BH-2"."""
        payload = json.loads(build_payload("P1", _sample(loca_id="BH 2")))

        assert payload["l"] == "BH 2"

    def test_the_data_uri_is_a_single_line_svg(self):
        """A newline in a data URI inside an HTML attribute is a broken image."""
        uri = generate_svg_data_url(build_payload("P1", _sample()))

        assert uri.startswith("data:image/svg+xml")
        assert "\n" not in uri
        # Percent-encoded, so the tag arrives as %3Csvg rather than <svg.
        assert "%3Csvg" in uri and "%3C%2Fsvg%3E" in uri

    def test_attaching_does_not_mutate_the_caller_rows(self):
        """The register payload and the QR payload must not leak into each
        other."""
        original = _sample()
        coded = attach_qr_codes("P1", [original])

        assert "payload" not in original
        assert "qr_svg_data_url" in coded[0]
        assert coded[0] is not original

    def test_decimals_become_json_safe_numbers(self):
        """asyncpg hands back Decimal, which json.dumps refuses."""
        coded = attach_qr_codes("P1", [_sample(depth_from=Decimal("5.00"), depth_to=Decimal("10.00"))])

        assert coded[0]["depth_from"] == 5.0
        json.dumps(coded[0])  # must not raise


class TestEndpoint:
    def _seed(self, pool, soil=0, rock=0):
        pool.route('FROM "tdac"."SPT_RECORD_STATUS" sr', [
            {"sample_id": f"P1-S{i}", "loca_id": "BH-1",
             "depth_from": Decimal(i), "depth_to": None}
            for i in range(soil)
        ])
        pool.route('FROM "tdac"."ROCK_RECORD" rr', [
            {"sample_id": f"P1-R{i}", "loca_id": "BH-1",
             "depth_from": Decimal(10 + i), "depth_to": Decimal(11 + i),
             "recovery": Decimal("80"), "rqd": Decimal("50"),
             "rock_type": "SAND", "lift_no": "1", "status": "APPROVED",
             "created_by": "u", "created_at": None}
            for i in range(rock)
        ])
        pool.route('FROM "tdac"."ROCK_PIECE"', [])

    def test_scope_all_returns_both_kinds(self, client, pool):
        _as_admin(pool)
        self._seed(pool, soil=2, rock=1)

        body = client.get(f"{BASE}?scope=all", headers=auth_header(user_id=1)).json()

        assert body["count"] == 3
        assert sorted({s["kind"] for s in body["samples"]}) == ["rock", "soil"]

    def test_scope_soil_excludes_rock(self, client, pool):
        _as_admin(pool)
        self._seed(pool, soil=2, rock=3)

        body = client.get(f"{BASE}?scope=soil", headers=auth_header(user_id=1)).json()

        assert body["count"] == 2
        assert {s["kind"] for s in body["samples"]} == {"soil"}

    def test_scope_rock_excludes_soil(self, client, pool):
        _as_admin(pool)
        self._seed(pool, soil=4, rock=1)

        body = client.get(f"{BASE}?scope=rock", headers=auth_header(user_id=1)).json()

        assert body["count"] == 1
        assert {s["kind"] for s in body["samples"]} == {"rock"}

    def test_an_unknown_scope_is_a_400(self, client, pool):
        _as_admin(pool)
        self._seed(pool)

        response = client.get(f"{BASE}?scope=bogus", headers=auth_header(user_id=1))

        assert response.status_code == 400
        assert "scope" in response.json()["detail"]

    def test_a_location_outside_the_project_is_a_404(self, client, pool):
        """The same guard the register uses, so the QR sheet cannot be used
        to probe another project's boreholes."""
        # Deliberately NOT _as_admin: it routes LOCA as present, and the
        # fake pool honours the FIRST matching route, so re-routing to absent
        # would be ignored. Leaving it unrouted makes the lookup return None,
        # which is exactly the "belongs to another project" case.
        route_users_by_id(pool, {1: make_user_row(id=1)})
        self._seed(pool, soil=1)

        response = client.get(
            f"{BASE}?scope=all&loca_id=OTHER", headers=auth_header(user_id=1)
        )

        assert response.status_code == 404

    def test_every_sample_carries_its_payload_and_symbol(self, client, pool):
        _as_admin(pool)
        self._seed(pool, soil=1, rock=1)

        body = client.get(f"{BASE}?scope=all", headers=auth_header(user_id=1)).json()

        for sample in body["samples"]:
            assert sample["payload"].startswith("{")
            assert sample["qr_svg_data_url"].startswith("data:image/svg+xml")
            # The payload shown must be the payload encoded: same sample id.
            assert json.loads(sample["payload"])["s"] == sample["sample_id"]

    def test_an_empty_project_is_an_empty_sheet_not_an_error(self, client, pool):
        _as_admin(pool)
        self._seed(pool)

        body = client.get(f"{BASE}?scope=all", headers=auth_header(user_id=1)).json()

        assert body["count"] == 0
        assert body["samples"] == []

    def test_the_order_is_deterministic(self, client, pool):
        """Re-printing must produce the same sheet."""
        _as_admin(pool)
        self._seed(pool, soil=3, rock=2)

        first = client.get(f"{BASE}?scope=all", headers=auth_header(user_id=1)).json()
        second = client.get(f"{BASE}?scope=all", headers=auth_header(user_id=1)).json()

        assert [s["sample_id"] for s in first["samples"]] == [
            s["sample_id"] for s in second["samples"]
        ]

    def test_authentication_is_required(self, client, pool):
        _as_admin(pool)
        self._seed(pool, soil=1)

        assert client.get(f"{BASE}?scope=all").status_code in (401, 403)