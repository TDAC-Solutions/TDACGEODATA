"""Tests for the revision supersession flow (start_new_revision).

B3 regression: once a test reached APPROVED or PUBLISHED the workbench was
permanently read-only — save_lab_revision refuses to write, the unique key
forbids re-registering the same sample+type, and nothing incremented
current_revision. start_new_revision closes that dead end.
"""

import json
from uuid import UUID

from tests.conftest import auth_header, make_user_row, route_users_by_id
PROJ = "P1"
TEST_ID = "66666666-6666-6666-6666-666666666666"
ATTERBERG_METHOD = UUID("22222222-2222-2222-2222-222222222222")
NEW_REVISION_URL = f"/api/portfolio/projects/{PROJ}/lab/tests/{TEST_ID}/new-revision"

RAW = {
    "identity": {"locationId": "BH-1", "sampleId": "SAMP-1"},
    "data": {"rows": [], "rows2": []},
}


def _test_row(status="APPROVED", revision=1):
    return {
        "test_id": UUID(TEST_ID),
        "loca_id": "BH-1",
        "samp_id": "SAMP-1",
        "spec_ref": "SPEC-01",
        "spec_depth": 2.0,
        "spec_base": 2.5,
        "test_type": "ATTERBERG",
        "status": status,
        "current_revision": revision,
        "row_version": 1,
        "method_definition_id": ATTERBERG_METHOD,
        "created_by": "tester",
    }


def _revision_row(revision_no=1, raw=None):
    return {
        "revision_no": revision_no,
        "raw_input_snapshot": json.dumps(raw or RAW),
        "calculation_output_snapshot": None,
        "validation_snapshot": None,
        "status": "CALCULATED",
        "created_at": "2026-10-10T10:00:00",
        "created_by": "tester",
    }


def _method_row():
    return {
        "method_definition_id": ATTERBERG_METHOD,
        "method_code": "ATTERBERG",
        "method_version": 1,
        "method_name": "Atterberg limits",
        "standard_body": "BIS",
        "standard_reference": "IS 2720",
        "standard_edition": "Part 5",
        "calculation_package": "atterberg_engine",
        "calculation_package_version": "0.1.0",
        "validation_schema": json.dumps({"standard_profile": "IS_2720_5_1985"}),
        "ags_mapping_profile": json.dumps({"groups": ["LLPL"]}),
        "result_schema": json.dumps({"outputs": ["liquid_limit"]}),
    }


def _wire(pool, test=None):
    route_users_by_id(
        pool, {5: make_user_row(id=5, role_id=2, role_name="engineer")}
    )
    pool.route('FROM "lab"."test" t', test or _test_row())
    pool.route('FROM "lab"."method_definition"', _method_row())
    pool.route('FROM "lab"."test_revision"', _revision_row())
    pool.route('FROM "lab"."validation_issue"', [])
    pool.route('FROM "lab"."review_event"', [])
    pool.route('FROM "lab"."ags_projection"', [])


class TestStartNewRevision:
    def test_approved_test_opens_new_editable_revision(self, client, pool):
        _wire(pool, _test_row(status="APPROVED", revision=1))

        response = client.post(
            NEW_REVISION_URL, headers=auth_header(user_id=5)
        )

        assert response.status_code == 200, response.text

        # The new revision row was inserted with the readings carried forward
        # and an empty calculated snapshot.
        insert_args = [
            args for method, sql, args in pool.calls
            if method == "execute" and "INSERT INTO" in sql
            and "test_revision" in sql
        ]
        assert insert_args, "the new revision INSERT must have run"
        bound = list(insert_args[0])
        # The INSERT..SELECT binds: test_id, new revision_no, reason,
        # actor, previous revision_no (the snapshot columns are read from
        # the previous row by the SELECT, not passed as parameters).
        assert bound[1] == 2                       # revision_no = old + 1
        assert bound[2] == "New revision (supersedes rev 1)"
        assert bound[4] == 1                        # previous revision_no

        # The test row was flipped back to DRAFT at the new revision.
        update_args = [
            args for method, sql, args in pool.calls
            if method == "execute" and "UPDATE" in sql
            and '"current_revision" = $2' in sql
        ]
        assert update_args, "the current_revision UPDATE must have run"
        assert list(update_args[0])[1] == 2

        # A SUPERSEDED review event was recorded against the new revision.
        event_args = [
            args for method, sql, args in pool.calls
            if method == "execute" and "review_event" in sql
        ]
        assert event_args
        assert list(event_args[0])[2] == 2          # revision_no
        assert list(event_args[0])[3] == "SUPERSEDED"

    def test_draft_test_cannot_be_superseded(self, client, pool):
        _wire(pool, _test_row(status="DRAFT", revision=1))

        response = client.post(
            NEW_REVISION_URL, headers=auth_header(user_id=5)
        )

        assert response.status_code == 400
        assert "Cannot start a new revision" in response.json()["detail"]
        # No revision INSERT happened.
        assert [
            args for method, sql, args in pool.calls
            if method == "execute" and "test_revision" in sql and "INSERT" in sql
        ] == []

    def test_response_uses_the_standard_envelope(self, client, pool):
        """C2 regression: every other lab mutation answers {message, test},
        but this route returned the bare payload, so the client's
        body.test was undefined and the new revision never opened."""
        _wire(pool, _test_row(status="APPROVED", revision=1))

        response = client.post(
            NEW_REVISION_URL, headers=auth_header(user_id=5)
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["message"] == "New revision started"
        assert body["test"]["test_id"] == TEST_ID

    def test_superseded_revision_is_frozen_immutable(self, client, pool):
        """The released revision must never be editable again: once
        current_revision moves on, a stray save would otherwise rewrite
        the record the old revision already published."""
        _wire(pool, _test_row(status="APPROVED", revision=1))

        client.post(NEW_REVISION_URL, headers=auth_header(user_id=5))

        freeze = [
            (sql, args) for method, sql, args in pool.calls
            if method == "execute" and 'SET "immutable" = true' in sql
        ]
        assert freeze, "the superseded revision must be frozen"
        assert list(freeze[0][1]) == [UUID(TEST_ID), 1]

    def test_new_revision_starts_as_draft_not_calculated(self, client, pool):
        """The calculation and validation snapshots are NOT carried
        forward, so the new revision must not claim CALCULATED before the
        save path recomputes it. The old code copied 'CALCULATED', which
        let an uncalculated revision pass straight into QA."""
        _wire(pool, _test_row(status="APPROVED", revision=1))

        client.post(NEW_REVISION_URL, headers=auth_header(user_id=5))

        insert_sql = [
            sql for method, sql, args in pool.calls
            if method == "execute" and 'INSERT INTO "lab"."test_revision"' in sql
        ][0]
        assert "'DRAFT'" in insert_sql
        assert "'CALCULATED'" not in insert_sql

    def test_missing_previous_revision_row_falls_back_to_an_empty_revision(
        self, pool, monkeypatch
    ):
        """C3: a legacy test can reach APPROVED with no test_revision row
        (the original register path wrote bare lab.test rows). The
        INSERT..SELECT then copies zero rows and the review event's FK on
        (test_id, revision_no) aborted the whole supersession. The zero-row
        path must provision an empty revision from the method definition
        instead."""
        import asyncio

        from app import database, lab_data_service

        pool.route('FROM "lab"."test" t', _test_row(status="APPROVED", revision=1))
        # The INSERT..SELECT matches this route and reports zero rows, the
        # way a missing previous revision row does on a live database.
        pool.route('INSERT INTO "lab"."test_revision"', "INSERT 0 0")
        pool.route('FROM "lab"."method_definition"', _method_row())
        monkeypatch.setattr(database, "pool", pool)

        async def _payload(*args, **kwargs):
            return {"test_id": TEST_ID}

        monkeypatch.setattr(lab_data_service, "get_lab_test", _payload)

        result = asyncio.run(
            lab_data_service.start_new_revision(PROJ, TEST_ID, "tester")
        )

        assert result == {"test_id": TEST_ID}

        fallback = [
            (sql, args) for method, sql, args in pool.calls
            if method == "execute" and "INSERT INTO" in sql
            and "test_revision" in sql and "VALUES" in sql
        ]
        assert fallback, "the fallback revision INSERT must have run"
        sql, args = fallback[0]
        assert "'{}'::jsonb" in sql
        assert list(args)[1] == 2
        assert list(args)[2] == "atterberg_engine"
