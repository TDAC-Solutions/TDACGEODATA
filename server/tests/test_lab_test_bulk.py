"""Tests for the multi-select bulk lab test registration path.

Task 16 registers several tests against one sample in a single transaction.
The regression these pin: FILE_FSET is NOT NULL on lab."test", but both
ags42."PROJ"."FILE_FSET" and ags42."SAMP"."FILE_FSET" are NULL in the
seeded data. Reading the column at face value therefore 500'd on every
registration, on the single-test path as well as the bulk one.
"""
from decimal import Decimal
from uuid import UUID

import asyncpg

from tests.conftest import auth_header, make_user_row, route_users_by_id


PROJ = "P1"
LOCA = "BH-1"
SAMP = "SAMP-1"
PSD_METHOD = UUID("11111111-1111-1111-1111-111111111111")
ATT_METHOD = UUID("22222222-2222-2222-2222-222222222222")
FSET = "FS-P1"


def _auth(pool, user_id=5):
    route_users_by_id(
        pool, {user_id: make_user_row(id=user_id, role_id=2, role_name="engineer")}
    )
    return auth_header(user_id=user_id)


def _project(fset=None, file_row_fset: str | None = FSET):
    return {"PROJ_ID": PROJ, "FILE_FSET": fset, "project_file_fset": file_row_fset}


def _sample(fset=None):
    return {
        "PROJ_ID": PROJ,
        "LOCA_ID": LOCA,
        "SAMP_ID": SAMP,
        "SAMP_TOP": Decimal("1.50"),
        "SAMP_REF": "SP-1",
        "SAMP_TYPE": "U",
        "SAMP_BASE": Decimal("12.00"),
        "FILE_FSET": fset,
    }


def _inserted_row(**overrides):
    row = {
        "test_id": UUID("33333333-3333-3333-3333-333333333333"),
        "file_fset": FSET,
        "loca_id": LOCA,
        "samp_id": SAMP,
        "spec_ref": "SPEC-01",
        "test_type": "PSD",
        "method_definition_id": PSD_METHOD,
        "laboratory": "Lab",
        "technician": None,
        "status": "DRAFT",
        "current_revision": 1,
        "row_version": 1,
    }
    row.update(overrides)
    return row


def _wire(pool, methods, project=None, sample=None, single=False, insert=None):
    """Route the statements the create paths make.

    First-match-wins on SQL substring, so the auth lookup is routed first
    because get_current_user runs before the handler body.

    `single` picks the method lookup shape: create_lab_test fetches one
    row with fetchrow, while the bulk path fetches every method in the
    batch with fetch. A single route cannot satisfy both.

    `insert` overrides the lab."test" INSERT result; the C4 tests pass a
    callable that raises asyncpg.UniqueViolationError to simulate the
    database-level duplicate the in-Python pre-check cannot see.
    """
    route_users_by_id(pool, {5: make_user_row(id=5, role_id=2, role_name="engineer")})
    pool.route('FROM "ags42"."PROJ"', project if project is not None else _project())
    pool.route('FROM "ags42"."SAMP"', sample if sample is not None else _sample())

    if single:
        pool.route('FROM "lab"."method_definition"', methods[0] if methods else None)
    else:
        pool.route('FROM "lab"."method_definition"', methods)

    pool.route(
        'INSERT INTO "lab"."test"',
        insert if insert is not None else (lambda *a: _inserted_row()),
    )


def _method_rows(*pairs):
    return [{"method_definition_id": m, "test_type": t} for m, t in pairs]


def _payload(*types, specimen_ref="SPEC-01"):
    ids = {"PSD": PSD_METHOD, "ATTERBERG": ATT_METHOD}
    return {
        "tests": [
            {
                "loca_id": LOCA,
                "samp_id": SAMP,
                "specimen_ref": specimen_ref,
                "test_type": t,
                "method_definition_id": str(ids[t]),
                "laboratory": "Lab",
            }
            for t in types
        ]
    }


BULK = f"/api/portfolio/projects/{PROJ}/lab/tests/bulk"


class TestBulkRegistration:
    def test_creates_one_row_per_ticked_type(self, client, pool):
        _wire(pool, _method_rows((PSD_METHOD, "PSD"), (ATT_METHOD, "ATTERBERG")))

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD", "ATTERBERG")
        )

        assert response.status_code == 201
        body = response.json()

        assert body["message"] == "2 laboratory test(s) created successfully"
        assert len(body["tests"]) == 2

    def test_both_writes_share_one_transaction(self, client, pool):
        """A batch must commit as a unit, or a duplicate in the middle
        leaves the sample half-registered."""
        _wire(pool, _method_rows((PSD_METHOD, "PSD"), (ATT_METHOD, "ATTERBERG")))

        client.post(
            BULK, headers=_auth(pool), json=_payload("PSD", "ATTERBERG")
        )

        methods = [c[0] for c in pool.calls]
        begin = methods.index("begin")
        commit = methods.index("commit")

        assert begin < commit

        # Counted by the SQL, not the call type: the project, sample and
        # method lookups are fetchrow too, so counting fetchrows would
        # include the reads that precede the writes. The ags42."SAMP"
        # provision sync also writes inside this transaction, so the count
        # is narrowed to the lab."test" rows the batch is about.
        inserts = [
            c for c in pool.calls[begin + 1 : commit]
            if 'INSERT INTO "lab"."test"' in c[1]
        ]

        assert len(inserts) == 2, [c[1][:60] for c in inserts]

        # Exactly one transaction for the whole batch.
        assert methods.count("begin") == 1
        assert methods.count("commit") == 1

    def test_file_fset_falls_back_to_the_file_table(self, client, pool):
        """PROJ.FILE_FSET and SAMP.FILE_FSET are both NULL in the seeded
        data, so the project's FILE row is the only thing that can supply
        the NOT NULL value. Without this the insert fails as a 500."""
        _wire(
            pool,
            _method_rows((PSD_METHOD, "PSD")),
            project=_project(fset=None),
            sample=_sample(fset=None),
        )

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD")
        )

        assert response.status_code == 201

        args = pool.last_args("fetchrow", 'INSERT INTO "lab"."test"')
        assert args[1] == FSET

    def test_sample_file_fset_wins_over_the_project(self, client, pool):
        _wire(
            pool,
            _method_rows((PSD_METHOD, "PSD")),
            project=_project(fset="FS-PROJ"),
            sample=_sample(fset="FS-SAMP"),
        )

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD")
        )

        assert response.status_code == 201
        assert pool.last_args("fetchrow", 'INSERT INTO "lab"."test"')[1] == "FS-SAMP"

    def test_project_with_no_file_record_is_provisioned_lazily(self, client, pool):
        """A project born in the UI (Create Project → Location → Sample) has no
        ags42."FILE" row to provision from, so the registration transaction
        itself creates a deterministic FS-<id> file set. A UI-born project is
        a lazy provision, not a refusal — the old behavior dead-ended Test
        Register for every real project."""
        _wire(
            pool,
            _method_rows((PSD_METHOD, "PSD")),
            project=_project(fset=None, file_row_fset=None),
        )

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD")
        )

        assert response.status_code == 201
        assert response.json()["tests"][0]["status"] == "DRAFT"
        # The lab.test INSERT bound FS-P1 as the file set, not a refusal.
        bind = pool.last_args("fetchrow", 'INSERT INTO "lab"."test"')[1]
        assert bind == f"FS-{PROJ}"
        # And the FILE provision INSERT ran with the deterministic values.
        provision_args = [
            args for method, sql, args in pool.calls
            if method == "execute" and 'INSERT INTO "ags42"."FILE"' in sql
        ]
        assert provision_args, "the FILE provision INSERT must have run"
        assert list(provision_args[0]) == [PROJ, f"FS-{PROJ}", f"{PROJ} AGS Data"]

        # C1 regression: a column-targeted ON CONFLICT names the key columns
        # unquoted, which PostgreSQL folds to lowercase; ags42."FILE" is
        # keyed on quoted mixed-case columns, so every UI-born project's
        # first registration died with UndefinedColumnError before this.
        provision_sql = [
            sql for method, sql, args in pool.calls
            if method == "execute" and 'INSERT INTO "ags42"."FILE"' in sql
        ][0]
        assert "ON CONFLICT DO NOTHING" in provision_sql
        assert "ON CONFLICT (" not in provision_sql

    def test_whitespace_only_file_set_falls_back_to_provision(self, client, pool):
        """The FILE table's CHECK rejects '' but not '   ', and Python treats
        '   ' as truthy, so a whitespace-only file set must not reach
        lab."test" as-is. It strips to nothing and the deterministic
        FS-<project> provision takes over instead."""
        _wire(
            pool,
            _method_rows((PSD_METHOD, "PSD")),
            project=_project(fset=None),
            sample=_sample(fset="   "),
        )

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD")
        )

        assert response.status_code == 201
        # The whitespace value never reached the INSERT: the provisioned
        # deterministic file set did.
        bind = pool.last_args("fetchrow", 'INSERT INTO "lab"."test"')[1]
        assert bind == f"FS-{PROJ}"

    def test_file_set_is_stripped(self, client, pool):
        """A padded but real file set is valid data and is stored clean."""
        _wire(
            pool,
            _method_rows((PSD_METHOD, "PSD")),
            project=_project(fset=None),
            sample=_sample(fset="  FS-P1  "),
        )

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD")
        )

        assert response.status_code == 201
        args = pool.last_args("fetchrow", 'INSERT INTO "lab"."test"')
        assert args[1] == FSET

    def test_duplicate_type_in_batch_is_rejected_before_any_write(self, client, pool):
        _wire(pool, _method_rows((PSD_METHOD, "PSD")))

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD", "PSD")
        )

        assert response.status_code == 400
        assert "PSD is selected more than once" in response.json()["detail"]
        assert not pool.calls_with("fetchrow", 'INSERT INTO "lab"."test"')

    def test_mixed_sample_batch_is_rejected(self, client, pool):
        """A hand-crafted batch spanning two samples would otherwise
        insert every test against whichever sample came first."""
        _wire(pool, _method_rows((PSD_METHOD, "PSD"), (ATT_METHOD, "ATTERBERG")))

        payload = _payload("PSD", "ATTERBERG")
        payload["tests"][1]["samp_id"] = "SAMP-2"

        response = client.post(BULK, headers=_auth(pool), json=payload)

        assert response.status_code == 400
        assert "same sample" in response.json()["detail"]
        assert not pool.calls_with("fetchrow", 'INSERT INTO "lab"."test"')

    def test_inactive_method_is_rejected_before_any_write(self, client, pool):
        """An invalid selection at position 2 must not leave test 1
        committed, so every method is validated up front."""
        _wire(pool, _method_rows((PSD_METHOD, "PSD")))  # Atterberg missing

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD", "ATTERBERG")
        )

        assert response.status_code == 400
        assert "ATTERBERG" in response.json()["detail"]
        assert not pool.calls_with("fetchrow", 'INSERT INTO "lab"."test"')

    def test_mismatched_method_is_rejected(self, client, pool):
        _wire(pool, _method_rows((PSD_METHOD, "ATTERBERG")))  # PSD id, wrong type

        response = client.post(
            BULK, headers=_auth(pool), json=_payload("PSD")
        )

        assert response.status_code == 400
        assert "does not match test type" in response.json()["detail"]

    def test_empty_batch_is_rejected_by_the_schema(self, client, pool):
        response = client.post(BULK, headers=_auth(pool), json={"tests": []})

        assert response.status_code == 422


class TestSinglePathStillWorks:
    """The refactor must not have changed the existing single-test contract."""

    def test_single_test_creates_one_row(self, client, pool):
        _wire(pool, _method_rows((PSD_METHOD, "PSD")), single=True)

        response = client.post(
            f"/api/portfolio/projects/{PROJ}/lab/tests",
            headers=_auth(pool),
            json={
                "loca_id": LOCA,
                "samp_id": SAMP,
                "specimen_ref": "SPEC-01",
                "test_type": "PSD",
                "method_definition_id": str(PSD_METHOD),
                "laboratory": "Lab",
            },
        )

        assert response.status_code == 201
        assert response.json()["test"]["test_type"] == "PSD"

    def test_single_test_still_uses_one_transaction(self, client, pool):
        _wire(pool, _method_rows((PSD_METHOD, "PSD")), single=True)

        client.post(
            f"/api/portfolio/projects/{PROJ}/lab/tests",
            headers=_auth(pool),
            json={
                "loca_id": LOCA,
                "samp_id": SAMP,
                "specimen_ref": "SPEC-01",
                "test_type": "PSD",
                "method_definition_id": str(PSD_METHOD),
                "laboratory": "Lab",
            },
        )

        methods = [c[0] for c in pool.calls]
        assert "begin" in methods
        assert "commit" in methods


def _duplicate_insert(*_args):
    """Simulate the database-level unique violation the pre-check missed."""
    raise asyncpg.UniqueViolationError(
        "duplicate key value violates unique constraint"
    )


SINGLE = f"/api/portfolio/projects/{PROJ}/lab/tests"


class TestDuplicateRegistration:
    """C4: a duplicate is already-existing state, so it is a 409 conflict.

    The service raised a plain ValueError, which the routers mapped to 400
    alongside real validation errors; the client then showed "check your
    selections" for something only a new revision or a different specimen
    reference can resolve. The service now raises DuplicateLabTestError and
    the routers single it out for a 409.
    """

    def test_single_path_duplicate_is_409(self, client, pool):
        _wire(
            pool,
            _method_rows((PSD_METHOD, "PSD")),
            single=True,
            insert=_duplicate_insert,
        )

        response = client.post(
            SINGLE,
            headers=_auth(pool),
            json=_payload("PSD")["tests"][0],
        )

        assert response.status_code == 409, response.text
        assert "already registered" in response.json()["detail"]

    def test_bulk_path_duplicate_is_409(self, client, pool):
        _wire(
            pool,
            _method_rows((PSD_METHOD, "PSD")),
            insert=_duplicate_insert,
        )

        response = client.post(BULK, headers=_auth(pool), json=_payload("PSD"))

        assert response.status_code == 409, response.text
        assert "already registered" in response.json()["detail"]