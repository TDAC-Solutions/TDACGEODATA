"""SPT edit behaviour: every edit must send the record back for approval.

The regression this pins: update_spt_record used to touch the status row
only when the depth itself moved, so editing an APPROVED record in place
left the old approval standing and the user never saw it again. These tests
drive the real router + service against FakePool and assert on the SQL the
service actually issues.
"""
from decimal import Decimal

from tests.conftest import auth_header, make_user_row, route_users_by_id


def _row(depth, b15=2, b30=3, b45=5, n=8):
    return {
        "spt_depth": Decimal(depth),
        "blows_15": Decimal(b15),
        "blows_30": Decimal(b30),
        "blows_45": Decimal(b45),
        "n_value": Decimal(n),
    }


def _wire_spt(pool, before, updated, sample_id="SPT-1"):
    """Route the statements update_spt_record makes, in call order.

    Routing is first-match-wins on SQL substring, so the auth lookup, the
    SELECT ... FOR UPDATE probe and the UPDATE ... RETURNING each need a
    distinct substring. The user row is routed first because get_current_user
    runs before the handler body.
    """
    route_users_by_id(pool, {5: make_user_row(id=5, role_id=2, role_name="engineer")})
    pool.route("SELECT 1", 1)                                   # _require_loca
    # Anchor on FOR UPDATE: a clause, not layout, so reformatting the service
    # file cannot break this. It also cannot be confused with the row UPDATE,
    # which repeats the same selected columns in its RETURNING clause - a
    # route on the columns alone would match the UPDATE first and hand it
    # this probe's row.
    pool.route("FOR UPDATE", before)                            # locking probe
    pool.route('UPDATE "ags42"."ISPT"', updated)                # row update
    pool.route('SELECT "SAMPLE_ID"', sample_id)                # sample id lookup


def _status_update(pool):
    """The SPT_RECORD_STATUS write, with its SQL and bind args."""
    calls = [
        c for c in pool.calls
        if c[0] == "execute" and 'UPDATE "tdac"."SPT_RECORD_STATUS"' in c[1]
    ]
    return calls


class TestSptEditResetsApproval:
    def test_same_depth_edit_resets_approved_record(self, client, pool):
        _wire_spt(pool, _row("1.5"), _row("1.5", b30=4, b45=6, n=10))

        response = client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=5),
            json={"spt_depth": 1.5, "blows_15": 2, "blows_30": 4, "blows_45": 6},
        )

        assert response.status_code == 200
        updates = _status_update(pool)
        assert len(updates) == 1, "status row was not touched on an in-place edit"

        sql, args = updates[0][1], updates[0][2]
        assert "'PENDING'" in sql
        assert '"APPROVED_BY" = NULL' in sql
        assert '"APPROVED_AT" = NULL' in sql
        assert '"REJECT_REASON" = NULL' in sql
        # Old depth keys the WHERE; new depth is re-keyed into DEPTH_FROM.
        assert args[2] == Decimal("1.5")
        assert args[3] == Decimal("1.5")

    def test_changed_depth_edit_resets_and_rekeys(self, client, pool):
        _wire_spt(pool, _row("1.5"), _row("1.75"))

        response = client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=5),
            json={"spt_depth": 1.75, "blows_15": 2, "blows_30": 3, "blows_45": 5},
        )

        assert response.status_code == 200
        updates = _status_update(pool)
        assert len(updates) == 1

        sql, args = updates[0][1], updates[0][2]
        assert '"DEPTH_FROM" = $4' in sql
        assert "'PENDING'" in sql
        assert args[2] == Decimal("1.5")   # original depth in the WHERE
        assert args[3] == Decimal("1.75")  # new depth in DEPTH_FROM

    def test_edit_is_recognised_by_the_pending_queue_query(self, client, pool):
        """After the reset the record must satisfy get_pending_spt_records.

        That query filters sr."STATUS" = 'PENDING'. A record left as APPROVED
        would silently vanish from the admin queue instead of reappearing.
        """
        _wire_spt(pool, _row("1.5"), _row("1.5", b30=4, b45=6, n=10))

        client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=5),
            json={"spt_depth": 1.5, "blows_15": 2, "blows_30": 4, "blows_45": 6},
        )

        sql, _ = _status_update(pool)[0][1], None
        assert "STATUS" in sql and "PENDING" in sql

    def test_n_value_is_recomputed_server_side(self, client, pool):
        """N is a plain sum of Below 30 + Below 45, never trusted from input."""
        _wire_spt(pool, _row("1.5"), _row("1.5", b30=4, b45=6, n=10))

        response = client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=5),
            json={"spt_depth": 1.5, "blows_15": 99, "blows_30": 4, "blows_45": 6},
        )

        assert response.status_code == 200
        body = response.json()
        # blows_15 is not part of N; 4 + 6 = 10, not 99 + 4 + 6.
        assert Decimal(str(body["record"]["n_value"])) == Decimal("10")
        assert body["record"]["blows_15"] == 2  # unchanged column, from the row

    def test_missing_record_returns_404_and_writes_no_status(self, client, pool):
        route_users_by_id(pool, {5: make_user_row(id=5, role_id=2, role_name="engineer")})
        pool.route("SELECT 1", 1)
        # Same clause anchor as _wire_spt, so this stays a "record absent" test
        # regardless of the probe's layout.
        pool.route("FOR UPDATE", None)   # probe finds nothing

        response = client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/9.9",
            headers=auth_header(user_id=5),
            json={"spt_depth": 9.9, "blows_15": 1, "blows_30": 1, "blows_45": 1},
        )

        assert response.status_code == 404
        assert _status_update(pool) == []

    def test_location_not_in_project_returns_404(self, client, pool):
        route_users_by_id(pool, {5: make_user_row(id=5, role_id=2, role_name="engineer")})
        pool.route("SELECT 1", None)

        response = client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=5),
            json={"spt_depth": 1.5, "blows_15": 1, "blows_30": 1, "blows_45": 1},
        )

        assert response.status_code == 404


def _wire_spt_admin(pool, before, updated, sample_id="SPT-1", previous_status="APPROVED"):
    """Route the statements update_spt_record makes when an ADMIN edits.

    Differs from _wire_spt only in the actor (admin) and in additionally
    routing the pre-read of STATUS, which the admin path consults before
    deciding whether the edit counts as a workflow transition.
    """
    route_users_by_id(pool, {1: make_user_row(id=1, role_id=1, role_name="admin")})
    pool.route("SELECT 1", 1)                                  # _require_loca
    pool.route("FOR UPDATE", before)                           # locking probe
    pool.route('UPDATE "ags42"."ISPT"', updated)              # row update
    pool.route('SELECT "SAMPLE_ID"', sample_id)               # sample id lookup
    # Anchored on the projected column so the earlier routes (SELECT 1,
    # FOR UPDATE, SAMPLE_ID) cannot swallow this one.
    pool.route('SELECT "STATUS"', previous_status)             # pre-edit status


def _audit_actions(pool):
    """The action argument of every tdac.audit_log insert, in call order."""
    return [
        args[3]
        for method, sql, args in pool.calls
        if method == "execute" and "INSERT INTO tdac.audit_log" in sql
    ]


class TestSptAdminEditIsItsOwnApproval:
    def test_admin_edit_keeps_record_approved(self, client, pool):
        """An admin's edit is the approval, so an APPROVED record stays
        approved and the approver is re-stamped with the editing admin
        rather than left pointing at the original reviewer."""
        _wire_spt_admin(pool, _row("1.5"), _row("1.5", b30=4, b45=6, n=10))

        response = client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=1),
            json={"spt_depth": 1.5, "blows_15": 2, "blows_30": 4, "blows_45": 6},
        )

        assert response.status_code == 200
        updates = _status_update(pool)
        assert len(updates) == 1
        sql, args = updates[0][1], updates[0][2]
        assert "'APPROVED'" in sql
        assert "'PENDING'" not in sql
        assert '"APPROVED_BY" = $5' in sql
        assert args[4] == 1  # the admin who just edited

    def test_admin_edit_of_approved_logs_no_approval_event(self, client, pool):
        """Staying approved is not a decision, so it must not pad the review
        history with an approval that decided nothing."""
        _wire_spt_admin(pool, _row("1.5"), _row("1.5", b30=4, b45=6, n=10))

        client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=1),
            json={"spt_depth": 1.5, "blows_15": 2, "blows_30": 4, "blows_45": 6},
        )

        actions = _audit_actions(pool)
        assert "SPT_APPROVED" not in actions
        assert "SAMPLE_EDITED" in actions

    def test_admin_edit_of_pending_lifts_to_approved_and_logs(self, client, pool):
        """PENDING -> APPROVED by the admin's own hand IS a real workflow
        transition, so the history must show an approval, not an edit."""
        _wire_spt_admin(
            pool,
            _row("1.5"),
            _row("1.5", b30=4, b45=6, n=10),
            previous_status="PENDING",
        )

        response = client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=1),
            json={"spt_depth": 1.5, "blows_15": 2, "blows_30": 4, "blows_45": 6},
        )

        assert response.status_code == 200
        actions = _audit_actions(pool)
        assert "SPT_APPROVED" in actions, (
            "admin self-edit of a PENDING record must log an approval"
        )
        assert "SAMPLE_EDITED" in actions

    def test_admin_edit_of_rejected_clears_rejection_and_approves(self, client, pool):
        """REJECTED -> APPROVED clears the stale rejection reason."""
        _wire_spt_admin(pool, _row("1.5"), _row("1.5"), previous_status="REJECTED")

        client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=1),
            json={"spt_depth": 1.5, "blows_15": 1, "blows_30": 2, "blows_45": 3},
        )

        sql, _ = _status_update(pool)[0][1], None
        assert "'APPROVED'" in sql
        assert '"REJECT_REASON" = NULL' in sql
        assert "SPT_APPROVED" in _audit_actions(pool)

    def test_non_admin_never_takes_the_admin_path(self, client, pool):
        """The client role is not an admin: its edit must still be re-queued,
        and must never stamp an approver."""
        route_users_by_id(
            pool, {10: make_user_row(id=10, role_id=10, role_name="client")}
        )
        pool.route("SELECT 1", 1)
        pool.route("FOR UPDATE", _row("1.5"))
        pool.route('UPDATE "ags42"."ISPT"', _row("1.5", b30=4, b45=6, n=10))
        pool.route('SELECT "SAMPLE_ID"', "SPT-1")
        pool.route('SELECT "STATUS"', "APPROVED")

        client.patch(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/1.5",
            headers=auth_header(user_id=10),
            json={"spt_depth": 1.5, "blows_15": 2, "blows_30": 4, "blows_45": 6},
        )

        sql, args = _status_update(pool)[0][1], _status_update(pool)[0][2]
        assert "'PENDING'" in sql
        assert "'APPROVED'" not in sql
        assert len(args) == 4, "non-admin write must not bind an approver id"
        assert "SPT_APPROVED" not in _audit_actions(pool)


class TestSptAdminSubmitIsPreApproved:
    def test_admin_submit_starts_approved_with_stamps(self, client, pool):
        """An admin's own submission needs no queue round-trip: it starts
        APPROVED with the approver and timestamp filled in."""
        # The duplicate-depth probe must be registered BEFORE the broad
        # "SELECT 1" route: _require_loca's query is also `SELECT 1 FROM
        # "ags42"."LOCA"`, and first-match-wins would answer the probe with
        # the location row and report every submit as a duplicate.
        route_users_by_id(pool, {1: make_user_row(id=1, role_id=1, role_name="admin")})
        pool.route('FROM "ags42"."ISPT"', None)   # no existing row at this depth
        pool.route("SELECT 1", 1)                  # _require_loca
        pool.route('INSERT INTO "ags42"."ISPT"', "INSERT 0 1")
        pool.route('INSERT INTO "tdac"."SAMPLE_ID_COUNTER"', {"LAST_NUMBER": 7})
        pool.route(
            'INSERT INTO "tdac"."SPT_RECORD_STATUS"',
            "INSERT 0 1",
        )

        response = client.post(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/bulk",
            headers=auth_header(user_id=1),
            json={"records": [{"spt_depth": 1.5, "blows_15": 2, "blows_30": 3, "blows_45": 5}]},
        )

        assert response.status_code in (200, 201)
        body = response.json()
        rows = body.get("records") or body.get("created") or []
        assert rows, f"expected created rows in {body}"
        assert rows[0]["status"] == "APPROVED"

        status_sql = pool.calls_with(
            "execute", 'INSERT INTO "tdac"."SPT_RECORD_STATUS"'
        )[-1][1]
        args = pool.last_args("execute", 'INSERT INTO "tdac"."SPT_RECORD_STATUS"')
        assert "APPROVED_BY" in status_sql and "APPROVED_AT" in status_sql
        assert "APPROVED" in args
        # Bind order is PROJ_ID, LOCA_ID, DEPTH_FROM, SAMPLE_ID, STATUS,
        # CREATED_BY, APPROVED_BY, APPROVED_AT. The approver id and the
        # timestamp are separate parameters: reusing one parameter in two
        # type contexts makes Postgres fail at prepare time with
        # AmbiguousParameterError, which no FakePool assertion can catch.
        assert args[-2] == 1, "APPROVED_BY must be the editing admin"
        assert args[-1] is not None, "APPROVED_AT must be stamped"

    def test_engineer_submit_starts_pending(self, client, pool):
        """A non-admin's submission is unchanged: PENDING, no approver."""
        route_users_by_id(
            pool, {5: make_user_row(id=5, role_id=2, role_name="engineer")}
        )
        # The duplicate-depth probe must be registered BEFORE the broad
        # "SELECT 1" route: _require_loca's query is also `SELECT 1 FROM
        # "ags42"."LOCA"`, and first-match-wins would answer the probe with
        # the location row and report every submit as a duplicate.
        pool.route('FROM "ags42"."ISPT"', None)   # no existing row at this depth
        pool.route("SELECT 1", 1)                  # _require_loca
        pool.route('INSERT INTO "ags42"."ISPT"', "INSERT 0 1")
        pool.route('INSERT INTO "tdac"."SAMPLE_ID_COUNTER"', {"LAST_NUMBER": 8})
        pool.route('INSERT INTO "tdac"."SPT_RECORD_STATUS"', "INSERT 0 1")

        response = client.post(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/bulk",
            headers=auth_header(user_id=5),
            json={"records": [{"spt_depth": 1.5, "blows_15": 2, "blows_30": 3, "blows_45": 5}]},
        )

        assert response.status_code in (200, 201)
        args = pool.last_args("execute", 'INSERT INTO "tdac"."SPT_RECORD_STATUS"')
        assert "PENDING" in args
        assert "'APPROVED'" not in args
        # Both approver fields must be NULL for a non-admin.
        assert args[-2] is None, "no approver id for a non-admin"
        assert args[-1] is None, "no approval timestamp for a non-admin"

    def test_status_column_check_constraint_still_satisfied(self, client, pool):
        """Guard the value written against the table's CHECK constraint:
        only PENDING / APPROVED / REJECTED may reach STATUS."""
        allowed = {"PENDING", "APPROVED", "REJECTED"}
        for actor_role, expected in (
            ("admin", "APPROVED"),
            ("engineer", "PENDING"),
        ):
            # Each iteration needs a clean routing table: routes are
            # first-match-wins and append-only, so leftovers from the previous
            # actor would answer the next actor's queries.
            pool.routes.clear()
            pool.calls.clear()

            route_users_by_id(
                pool,
                {7: make_user_row(id=7, role_id=2, role_name=actor_role)},
            )
            # Probe before the broad "SELECT 1" route, for the same reason as
            # the tests above.
            pool.route('FROM "ags42"."ISPT"', None)   # no existing row here
            pool.route("SELECT 1", 1)                  # _require_loca
            pool.route('INSERT INTO "ags42"."ISPT"', "INSERT 0 1")
            pool.route('INSERT INTO "tdac"."SAMPLE_ID_COUNTER"', {"LAST_NUMBER": 9})
            pool.route('INSERT INTO "tdac"."SPT_RECORD_STATUS"', "INSERT 0 1")

            client.post(
                "/api/portfolio/projects/P1/locas/L1/field-data/spt/bulk",
                headers=auth_header(user_id=7),
                json={"records": [{"spt_depth": 2.0, "blows_15": 1, "blows_30": 2, "blows_45": 3}]},
            )

            args = pool.last_args(
                "execute", 'INSERT INTO "tdac"."SPT_RECORD_STATUS"'
            )
            status = args[4]
            assert status in allowed, f"{actor_role} wrote {status!r}"
            assert status == expected


class TestSptStatusInsertIsPostgresSafe:
    """Guards against the statement shape that caused a live 500.

    PostgreSQL refuses to PREPARE a statement in which one bind parameter is
    used in two type contexts, reporting
        AmbiguousParameterError: could not determine data type of parameter $N
    before any row is written, so the whole submit fails. FakePool never hands
    the SQL to the database, so no amount of call-shape assertion catches it.

    The static checks below catch the *shape* without a database, and
    scripts/check_spt_status_param_types.py confirms both shapes against a
    real PostgreSQL.
    """

    _STATUS_INSERT = 'INSERT INTO "tdac"."SPT_RECORD_STATUS"'

    def _submit_as(self, client, pool, user_id, role_name, role_id=2):
        pool.routes.clear()
        pool.calls.clear()
        route_users_by_id(
            pool, {user_id: make_user_row(id=user_id, role_id=role_id, role_name=role_name)}
        )
        pool.route('FROM "ags42"."ISPT"', None)   # no existing row at this depth
        pool.route("SELECT 1", 1)                  # _require_loca
        pool.route('INSERT INTO "ags42"."ISPT"', "INSERT 0 1")
        pool.route('INSERT INTO "tdac"."SAMPLE_ID_COUNTER"', {"LAST_NUMBER": 42})
        pool.route(self._STATUS_INSERT, "INSERT 0 1")

        response = client.post(
            "/api/portfolio/projects/P1/locas/L1/field-data/spt/bulk",
            headers=auth_header(user_id=user_id),
            json={"records": [{"spt_depth": 6.5, "blows_15": 1, "blows_30": 2, "blows_45": 3}]},
        )
        assert response.status_code in (200, 201), response.text

        calls = pool.calls_with("execute", self._STATUS_INSERT)
        assert calls, "no SPT_RECORD_STATUS insert was issued"
        return calls[-1][1]

    def test_no_bind_parameter_is_used_twice(self, client, pool):
        """A repeated $N across two type contexts is what Postgres rejects."""
        import re

        for user_id, role, role_id in ((1, "admin", 1), (5, "engineer", 2)):
            sql = self._submit_as(client, pool, user_id, role, role_id)
            placeholders = re.findall(r"\$(\d+)", sql)
            duplicates = {p for p in placeholders if placeholders.count(p) > 1}
            assert not duplicates, (
                f"{role} submit reuses bind parameter(s) {sorted(duplicates)}; "
                "PostgreSQL cannot infer one type for two contexts and raises "
                "AmbiguousParameterError before writing anything"
            )

    def test_no_case_expression_over_bind_parameters(self, client, pool):
        """Now()/NULL selection belongs in Python, not in a SQL CASE."""
        for user_id, role, role_id in ((1, "admin", 1), (5, "engineer", 2)):
            sql = self._submit_as(client, pool, user_id, role, role_id)
            assert "CASE" not in sql.upper(), (
                f"{role} submit still computes approver fields in SQL"
            )

    def test_one_bind_parameter_per_inserted_column(self, client, pool):
        """The VALUES list must be a plain positional list, one $N per column."""
        import re

        for user_id, role, role_id in ((1, "admin", 1), (5, "engineer", 2)):
            sql = self._submit_as(client, pool, user_id, role, role_id)
            values = re.search(r"VALUES\s*\((.*?)\)", sql, re.S | re.I)
            assert values, f"{role} submit has no VALUES list"
            entries = [v.strip() for v in values.group(1).split(",")]
            assert all(re.fullmatch(r"\$\d+", e) for e in entries), (
                f"{role} submit has a non-literal VALUES entry: {entries}"
            )
            assert [int(e[1:]) for e in entries] == list(range(1, len(entries) + 1)), (
                f"{role} submit placeholders are not contiguous from $1: {entries}"
            )
