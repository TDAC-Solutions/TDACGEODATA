"""Integration tests for the server calculation engine wiring.

Covers the contract the Lab Data tabs depend on:

1. POST /lab/tests/{id}/calculate  -- dry-run returns the authoritative
   snapshots without persisting anything.
2. PUT  /lab/tests/{id}/revision   -- the server recomputes the calculation
   for engine-backed test types, so the stored snapshot is the engine's,
   never the browser's. A fake client snapshot with invented numbers must
   NOT survive the save.
3. Non-engine test types keep the client snapshot untouched.
4. Engine refusals surface as 400 with a message written for the form
   (TDAC_* tokens humanized).
5. The declared output keys in the migration SQL match the keys the
   adapters actually write, so a released value can never be a key the
   engine does not produce.

All database access is faked with the suite's FakePool; the engines
themselves are the real ported code.
"""

import json
from pathlib import Path
from uuid import UUID

from tests.conftest import auth_header, make_user_row, route_users_by_id
import pytest

PROJ = "P1"
LOCA = "BH-1"
SAMP = "SAMP-1"
ATTERBERG_METHOD = UUID("22222222-2222-2222-2222-222222222222")
TRIAXIAL_METHOD = UUID("44444444-4444-4444-4444-444444444444")
TEST_ID = "55555555-5555-5555-5555-555555555555"

HERE = Path(__file__).parent
MIGRATION_SQL = (HERE / ".." / "scripts" / "migration_lab_engine.sql").read_text()

# Real Atterberg readings (the package fixture values as strings, exactly
# what the Results Entry grid produces) -> LL 45.0, PL 24.5, PI 20.5.
ATTERBERG_RAW = {
    "identity": {
        "locationId": LOCA,
        "sampleId": SAMP,
        "specimenReference": "SPEC-01",
        "testDate": "2026-10-10",
    },
    "method": "ATTERBERG · IS 2720 · Part 5 · v1",
    "preparation": "Wet preparation",
    "data": {
        "rows": [
            {"blows": "15", "containerMass": "20", "wetContainer": "34.766218",
             "dryContainer": "30", "use": "true"},
            {"blows": "20", "containerMass": "20", "wetContainer": "34.616292",
             "dryContainer": "30", "use": "true"},
            {"blows": "28", "containerMass": "20", "wetContainer": "34.441162",
             "dryContainer": "30", "use": "true"},
            {"blows": "35", "containerMass": "20", "wetContainer": "34.324647",
             "dryContainer": "30", "use": "true"},
        ],
        "rows2": [
            {"containerMass": "20", "wetContainer": "32.42", "dryContainer": "30"},
            {"containerMass": "21", "wetContainer": "33.48", "dryContainer": "31"},
        ],
    },
}

VALIDATION_SCHEMA = json.dumps(
    {
        "standard_profile": "IS_2720_5_1985",
        "liquid_limit_method": "casagrande",
        "ll_r2_min": 0.95,
        "pl_range_tolerance_pct": 1.0,
    }
)


def _test_row(test_type="ATTERBERG", method_id=ATTERBERG_METHOD, status="DRAFT"):
    return {
        "test_id": UUID(TEST_ID),
        "loca_id": LOCA,
        "samp_id": SAMP,
        "spec_ref": "SPEC-01",
        "spec_depth": 2.0,
        "spec_base": 2.5,
        "test_type": test_type,
        "status": status,
        "current_revision": 1,
        "row_version": 1,
        "method_definition_id": method_id,
        "created_by": "tester",
    }


def _revision_row(raw=None, calc=None, validation=None):
    return {
        "revision_no": 1,
        "raw_input_snapshot": json.dumps(raw or ATTERBERG_RAW),
        "calculation_output_snapshot": json.dumps(calc) if calc is not None else None,
        "validation_snapshot": json.dumps(validation) if validation is not None else None,
        "status": "CALCULATED",
        "created_at": "2026-10-10T10:00:00",
        "created_by": "tester",
    }


def _wire_engine_test(pool, test_type="ATTERBERG", method_id=ATTERBERG_METHOD):
    """Route every statement calculate/save makes for an engine-backed test."""
    route_users_by_id(
        pool, {5: make_user_row(id=5, role_id=2, role_name="engineer")}
    )
    pool.route('FROM "lab"."test" t', _test_row(test_type, method_id))
    # The method row carries everything both the calculate path (validation_
    # schema, calculation_package) and the get_lab_test payload builder
    # (ags_mapping_profile, result_schema, method naming columns) read.
    pool.route(
        'FROM "lab"."method_definition"',
        {
            "validation_schema": VALIDATION_SCHEMA,
            "calculation_package": "atterberg_engine",
            "calculation_package_version": "0.1.0",
            "method_definition_id": method_id,
            "method_code": test_type,
            "method_version": 1,
            "method_name": "Atterberg limits",
            "standard_body": "BIS",
            "standard_reference": "IS 2720",
            "standard_edition": "Part 5",
            "ags_mapping_profile": json.dumps({"groups": ["LLPL"]}),
            "result_schema": json.dumps(
                {"outputs": [
                    "liquid_limit", "plastic_limit",
                    "plasticity_index", "flow_index",
                ]}
            ),
        },
    )
    pool.route('FROM "lab"."test_revision"', _revision_row())
    pool.route('FROM "lab"."validation_issue"', [])
    pool.route('FROM "lab"."review_event"', [])
    pool.route('FROM "lab"."ags_projection"', [])


CALC_URL = f"/api/portfolio/projects/{PROJ}/lab/tests/{TEST_ID}/calculate"
REV_URL = f"/api/portfolio/projects/{PROJ}/lab/tests/{TEST_ID}/revision"


class TestCalculateEndpoint:
    def test_dry_run_returns_authoritative_snapshots(self, client, pool):
        _wire_engine_test(pool)

        response = client.post(
            CALC_URL, json={"raw_input_snapshot": ATTERBERG_RAW},
            headers=auth_header(user_id=5),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        outputs = body["calculation_output_snapshot"]["outputs"]

        # The engine's numbers, not a client echo.
        assert abs(outputs["liquid_limit"] - 45.0) < 0.001
        assert abs(outputs["plastic_limit"] - 24.5) < 0.01
        assert abs(outputs["plasticity_index"] - 20.5) < 0.001

        # Nothing was persisted.
        assert pool.calls_with("execute", "INSERT INTO") == []

        # The validation snapshot carries the engine's warnings, never blockers.
        validation = body["validation_snapshot"]
        assert validation["errors"] == 0
        assert validation["warnings"] >= 1  # method_verified defaults False

    def test_engine_refusal_is_a_400_with_human_message(self, client, pool):
        _wire_engine_test(pool)

        bad = json.loads(json.dumps(ATTERBERG_RAW))
        bad["data"]["rows"][0]["wetContainer"] = "19"  # wet < dry

        response = client.post(
            CALC_URL, json={"raw_input_snapshot": bad},
            headers=auth_header(user_id=5),
        )

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "TDAC_" not in detail  # humanized for the form
        assert "wet >= dry" in detail

    def test_non_engine_type_returns_clear_message(self, client, pool):
        _wire_engine_test(pool, test_type="TRIAXIAL_UU", method_id=TRIAXIAL_METHOD)

        response = client.post(
            CALC_URL, json={"raw_input_snapshot": {}},
            headers=auth_header(user_id=5),
        )

        assert response.status_code == 400
        assert "TRIAXIAL_UU" in response.json()["detail"]


class TestSaveRecomputesServerSide:
    def test_client_calculation_is_replaced_by_engine_output(self, client, pool):
        _wire_engine_test(pool)

        # A browser snapshot with invented values. The server must discard
        # these and store the engine's numbers instead.
        invented = {
            "outputs": {"liquid_limit": 999.0, "plasticity_index": 888.0},
            "results": [{"label": "Liquid limit", "value": "999"}],
        }
        response = client.put(
            REV_URL,
            json={
                "raw_input_snapshot": ATTERBERG_RAW,
                "calculation_output_snapshot": invented,
                "validation_snapshot": {"issues": [], "errors": 0, "warnings": 0},
                "revision_reason": "Calculated draft",
            },
            headers=auth_header(user_id=5),
        )

        assert response.status_code == 200, response.text

        # The real assertion: find the revision INSERT args and inspect the
        # jsonb payloads that were bound.
        insert_calls = [
            args for (method, sql, args) in pool.calls
            if method == "execute" and "INSERT INTO" in sql
            and "test_revision" in sql
        ]
        assert insert_calls, "the revision INSERT must have run"
        bound = insert_calls[0]
        # asyncpg binds jsonb as the JSON string; the payload is arg index 3.
        calc_arg = bound[3]
        assert isinstance(calc_arg, str)
        stored_calc = json.loads(calc_arg)

        assert abs(stored_calc["outputs"]["liquid_limit"] - 45.0) < 0.001
        assert abs(stored_calc["outputs"]["plasticity_index"] - 20.5) < 0.001
        # The invented values are gone.
        assert stored_calc["outputs"].get("liquid_limit") != 999.0
        assert stored_calc["engine"] == "tdac_lab_engine"

        # Validation issues written from the engine's warnings.
        validation_arg = bound[4]
        stored_validation = json.loads(validation_arg)
        assert stored_validation["errors"] == 0
        assert stored_validation["warnings"] >= 1

    def test_non_engine_type_keeps_client_snapshot(self, client, pool):
        _wire_engine_test(pool, test_type="TRIAXIAL_UU", method_id=TRIAXIAL_METHOD)

        client_calc = {
            "outputs": {"cu": 42.0},
            "results": [{"label": "Mean cu", "value": "42"}],
        }
        response = client.put(
            REV_URL,
            json={
                "raw_input_snapshot": {"data": {"rows": []}},
                "calculation_output_snapshot": client_calc,
                "validation_snapshot": {"issues": [], "errors": 0, "warnings": 0},
            },
            headers=auth_header(user_id=5),
        )

        assert response.status_code == 200, response.text
        insert_calls = [
            args for (method, sql, args) in pool.calls
            if method == "execute" and "test_revision" in sql
        ]
        stored_calc = json.loads(insert_calls[0][3])
        assert stored_calc["outputs"] == {"cu": 42.0}
        assert "engine" not in stored_calc

    def test_engine_refusal_aborts_the_save(self, client, pool):
        _wire_engine_test(pool)

        bad = json.loads(json.dumps(ATTERBERG_RAW))
        bad["data"]["rows"][0]["wetContainer"] = "19"

        response = client.put(
            REV_URL,
            json={
                "raw_input_snapshot": bad,
                "calculation_output_snapshot": {"outputs": {}},
                "validation_snapshot": None,
            },
            headers=auth_header(user_id=5),
        )

        assert response.status_code == 400
        assert "wet >= dry" in response.json()["detail"]
        # No revision write happened.
        assert pool.calls_with("execute", "test_revision") == []


class TestDeclaredOutputsParity:
    """The migration's result_schema.outputs must equal the adapters'
    DECLARED_OUTPUTS, or a released key could be a key the engine never
    writes (the exact PSD seed bug this migration fixes)."""

    def test_migration_declares_exactly_the_adapter_keys(self):
        import re

        from app.lab_engine import adapters

        # Parse every "UPDATE ... SET result_schema = jsonb_build_object(
        # 'outputs', jsonb_build_array(...)) WHERE test_type = 'X' ..."
        # statement. Statement-scoped regex, not string splitting, so one
        # method's array can never be attributed to another.
        statements = re.findall(
            r"SET result_schema\s*=\s*jsonb_build_object\(\s*'outputs',\s*"
            r"jsonb_build_array\((.*?)\)\s*\)\s*WHERE test_type = '(\w+)'",
            MIGRATION_SQL,
            re.DOTALL,
        )
        declared_by_type = {
            test_type: [k.strip().strip("'") for k in array.split(",") if k.strip()]
            for array, test_type in statements
        }

        for test_type, keys in adapters.DECLARED_OUTPUTS.items():
            assert test_type in declared_by_type, (
                f"migration has no result_schema statement for {test_type}"
            )
            assert sorted(declared_by_type[test_type]) == sorted(keys), (
                f"{test_type}: migration declares "
                f"{declared_by_type[test_type]}, adapters write {list(keys)}"
            )
