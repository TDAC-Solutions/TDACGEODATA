"""Excel import: parser, endpoints, and service behavior.

Three layers:
1. Parser unit tests against synthetic in-memory workbooks (header-token
   matching, sheet detection, rounding, error surfaces).
2. The real example workbook (~/storage/downloads/Input_sheet_V8_AGS_mapped
   .xlsx) parsed through the shared endpoint, pinning its exact shape.
3. HTTP-layer tests against FakePool: routing, auth, 409/404/409 branches,
   transaction + bulk-insert behavior, and that no new columns are
   referenced in any generated SQL.

The real-workbook test reads the user's file when present and SKIPS (with
an explicit message) otherwise, so the suite stays runnable everywhere.
"""

import io
import os
from datetime import date
from decimal import Decimal

import openpyxl
import asyncpg
import pytest

from app.spreadsheet_import.errors import (
    SpreadsheetFormatError,
    SpreadsheetValidationError,
)
from app.spreadsheet_import.field_parser import (
    ExcelImportError,
    parse_field_input_spreadsheet,
    parse_input_sheet,
)
from app.spreadsheet_import.file_reader import SpreadsheetFormat, read_spreadsheet
from app.spreadsheet_import.validation import validate_field_workbook
from tests.conftest import auth_header, make_user_row

# The real V8 input sheet, committed as a fixture so the pinned-shape
# test runs on every machine, not just the device with the original file.
REAL_WORKBOOK = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "Input_sheet_V8_AGS_mapped.xlsx",
)


def build_workbook(sheets: dict) -> bytes:
    """Sheets spec {name: [rows]} -> workbook bytes (in memory)."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


GOOD_SHEETS = {
    "ProjectInfo": [
        ["Project Type", "PROPOSED G+1 ADMIN BUILDING"],
        ["Project Location", "CHAMPAKKULAM"],
        ["Client Name", "Mr. BEJOY MICHLE"],
        ["Borehole Number", "BH 2"],
        ["Drilling Start Date", "17.08.2026"],
        ["Drilling Completion Date", "17.08.2026"],
        ["Termination Depth (m)", 23.45],
    ],
    "Borelog": [
        [
            "Depth From (m)", "Depth To (m)", "Soil Description",
            "Thickness", "Sand/ clay", "Average N value",
        ],
        [0, 1.5, "Filling Gravel", 1.5, None, 2],
        [1.5, 2.5, "Soft Sandy CLAY", 1, "C", 2],
        [None, None, None, None, None, None],  # padding ends data
        ["Depth From", "GEOL.GEOL_TOP"],  # legend below data
    ],
    "SPT_Data": [
        [
            "SPT Depth (m)", "Blows @15cm", "Blows @30cm",
            "Blows @45cm", "SPT N-value",
        ],
        [1, 1, 1, 1, 2],
        [2, 1, 1, 1, 2],
    ],
    "AGS_Mapping_Remarks": [
        ["ID", "Source sheet", "Source cell(s) / label"],
        [1, "ProjectInfo", "A2"],
    ],
}


class TestParserSynthetic:
    def test_full_parse(self):
        parsed = parse_input_sheet(build_workbook(GOOD_SHEETS))

        info = parsed["project_info"]
        assert info["project_type"] == "PROPOSED G+1 ADMIN BUILDING"
        assert info["project_location"] == "CHAMPAKKULAM"
        assert info["client_name"] == "Mr. BEJOY MICHLE"
        assert info["borehole_number"] == "BH 2"
        assert info["start_date"] == date(2026, 8, 17)
        assert info["end_date"] == date(2026, 8, 17)
        # Depths are exact Decimals now: NUMERIC keeps what it is handed,
        # so the parse must produce the shortest decimal the sheet meant,
        # not the binary-float expansion of it.
        assert info["final_depth"] == Decimal("23.45")

        assert parsed["borelog"] == [
            {
                "depth_from": Decimal("0"), "depth_to": Decimal("1.5"),
                "soil_description": "Filling Gravel", "sand_clay": None,
            },
            {
                "depth_from": Decimal("1.5"), "depth_to": Decimal("2.5"),
                "soil_description": "Soft Sandy CLAY", "sand_clay": "C",
            },
        ]

        assert parsed["spt"] == [
            {
                "spt_depth": Decimal("1"), "blows_15": Decimal("1"),
                "blows_30": Decimal("1"), "blows_45": Decimal("1"),
                "n_value": Decimal("2"),
            },
            {
                "spt_depth": Decimal("2"), "blows_15": Decimal("1"),
                "blows_30": Decimal("1"), "blows_45": Decimal("1"),
                "n_value": Decimal("2"),
            },
        ]

        assert parsed["rock_profile"] == []

    def test_float_artifacts_are_rounded(self):
        # 2.2 stored as 2.1999999999999997 must land as 2.2 so re-imports
        # hit the same unique-constraint identity. repr() of the parsed
        # float is already the shortest form; the equality against
        # Decimal("2.2") proves no binary expansion survives either way.
        sheets = {
            "Borelog": [
                ["Depth From (m)", "Depth To (m)", "Soil Description"],
                [0, 2.1999999999999997, "CLAY"],
            ],
        }
        parsed = parse_input_sheet(build_workbook(sheets))
        assert parsed["borelog"][0]["depth_to"] == Decimal("2.2")

    def test_renamed_sheets_still_import(self):
        # Detection is by header tokens, not sheet names.
        renamed = {
            "Site Data": GOOD_SHEETS["Borelog"],
            "Whatever": GOOD_SHEETS["SPT_Data"],
        }
        parsed = parse_input_sheet(build_workbook(renamed))
        assert len(parsed["borelog"]) == 2
        assert len(parsed["spt"]) == 2

    def test_bad_depth_order_raises(self):
        sheets = {
            "Borelog": [
                ["Depth From (m)", "Depth To (m)", "Soil Description"],
                [5.0, 4.0, "Inverted"],
            ],
        }
        with pytest.raises(ExcelImportError, match="Depth To must be greater"):
            parse_input_sheet(build_workbook(sheets))

    def test_no_data_sheets_raises(self):
        sheets = {"Notes": [["hello", "world"]]}
        with pytest.raises(ExcelImportError, match="No recognizable data"):
            parse_input_sheet(build_workbook(sheets))

    def test_not_a_workbook_raises(self):
        with pytest.raises(ExcelImportError, match="could not be opened"):
            parse_input_sheet(b"not an excel file")

    def test_spt_padding_rows_end_data_block(self):
        # The example SPT sheet pads with 20+ styled-empty rows and ends
        # with a derived "Layer 1..9" block; parsing must stop at the
        # first empty depth row.
        rows = [GOOD_SHEETS["SPT_Data"][0]] + [
            [1, 1, 1, 1, 2],
            [None] * 5,
            [None] * 5,
            [None, None, None, None, None],
            [None, 2, None, None, None],  # layer summary block
        ]
        parsed = parse_input_sheet(
            build_workbook({"SPT_Data": rows})
        )
        assert len(parsed["spt"]) == 1

    def test_rock_profile_sheet(self):
        sheets = {
            "Rock profile": [
                [
                    "Depth From (m)", "Depth To (m)", "Rock Description",
                    "Thickness", "Recovery", "RQD", "Remark",
                ],
                [10.0, 11.5, "WEATHERED ROCK", 1.5, 80, 60, "Core lost"],
            ],
        }
        parsed = parse_input_sheet(build_workbook(sheets))
        assert parsed["rock_profile"] == [
            {
                "depth_from": 10.0, "depth_to": 11.5,
                "rock_description": "WEATHERED ROCK", "recovery": 80.0,
                "rqd": 60.0, "remark": "Core lost",
            }
        ]

    def test_csv_uses_the_same_field_workbook_contract(self):
        parsed = parse_field_input_spreadsheet(
            b"Depth From (m),Depth To (m),Soil Description\n"
            b"0,1.5,Filling Gravel\n"
            b"1.5,2.5,Soft Sandy CLAY\n",
            filename="borelog.csv",
        )

        assert parsed["dataset"] == "borelog"
        assert parsed["rows"] == [
            {
                "depth_from": Decimal("0"),
                "depth_to": Decimal("1.5"),
                "soil_description": "Filling Gravel",
                "sand_clay": None,
            },
            {
                "depth_from": Decimal("1.5"),
                "depth_to": Decimal("2.5"),
                "soil_description": "Soft Sandy CLAY",
                "sand_clay": None,
            },
        ]

    def test_reader_reports_the_source_format_for_csv(self):
        document = read_spreadsheet(
            b"Project ID,Project Name\n901,Existing work\n",
            filename="register.csv",
        )

        assert document.format == SpreadsheetFormat.CSV
        assert document.sheets[0].name == "CSV"
        assert document.sheets[0].rows[0] == [
            "Project ID",
            "Project Name",
        ]

    def test_csv_spt_without_optional_blow_columns_does_not_reuse_last_value(self):
        parsed = parse_field_input_spreadsheet(
            b"SPT Depth (m),SPT N-value\n1,5\n2,7\n",
            filename="spt.csv",
        )

        assert parsed["rows"] == [
            {
                "spt_depth": Decimal("1"),
                "blows_15": None,
                "blows_30": None,
                "blows_45": None,
                "n_value": Decimal("5"),
            },
            {
                "spt_depth": Decimal("2"),
                "blows_15": None,
                "blows_30": None,
                "blows_45": None,
                "n_value": Decimal("7"),
            },
        ]

    def test_csv_with_only_a_blank_data_row_is_rejected(self):
        with pytest.raises(ExcelImportError, match="no data rows"):
            parse_field_input_spreadsheet(
                b"Depth From (m),Depth To (m),Soil Description\n,\n",
                filename="empty-borelog.csv",
            )

    def test_legacy_xls_is_rejected_with_a_conversion_message(self):
        with pytest.raises(SpreadsheetFormatError, match="Convert"):
            read_spreadsheet(b"old binary workbook", filename="register.xls")

    def test_validation_rejects_duplicate_depth_keys_before_the_database(self):
        workbook = {
            "project_info": {"borehole_number": "BH 1"},
            "borelog": [
                {
                    "depth_from": Decimal("0"),
                    "depth_to": Decimal("1"),
                    "soil_description": "Fill",
                },
                {
                    "depth_from": Decimal("0"),
                    "depth_to": Decimal("1"),
                    "soil_description": "Different description",
                },
            ],
            "rock_profile": [],
            "spt": [],
        }

        with pytest.raises(SpreadsheetValidationError, match="Duplicate"):
            validate_field_workbook(workbook)


class TestParserRealWorkbook:
    def test_real_example_workbook(self):
        import os

        if not os.path.exists(REAL_WORKBOOK):
            pytest.skip(
                "Example workbook not present on this device "
                f"({REAL_WORKBOOK})"
            )

        parsed = parse_input_sheet(open(REAL_WORKBOOK, "rb").read())

        info = parsed["project_info"]
        assert info["borehole_number"] == "BH 2"
        assert info["final_depth"] == Decimal("23.45")
        assert info["start_date"] == date(2026, 8, 17)

        assert len(parsed["borelog"]) == 10
        assert parsed["borelog"][0]["soil_description"] == "Filling Gravel"
        assert parsed["borelog"][-1]["depth_to"] == Decimal("23.45")

        assert len(parsed["spt"]) == 14
        assert parsed["spt"][-1]["spt_depth"] == 23.0

        assert parsed["rock_profile"] == []


# ---------------------------------------------------------------------------
# HTTP layer (FakePool)
# ---------------------------------------------------------------------------

def post_workbook_file(client, sheets=None, filename="input.xlsx"):
    if sheets is None:
        sheets = GOOD_SHEETS
    data = build_workbook(sheets)
    return client.post(
        "/api/excel/workbook",
        files={"file": (filename, data, "application/vnd.ms-excel")},
        headers=auth_header(user_id=1),
    )


def make_commit_body(overrides=None):
    body = {
        "project_id": "901",
        "project_name": "Imported Project",
        "borehole_type": "BH",
        "workbook": {
            "project_info": {
                "project_location": "CHAMPAKKULAM",
                "client_name": "Mr. BEJOY MICHLE",
                "borehole_number": "BH 2",
                "start_date": "2026-08-17",
                "end_date": "2026-08-17",
                "final_depth": 23.45,
            },
            "borelog": [
                {
                    "depth_from": 0, "depth_to": 1.5,
                    "soil_description": "Filling Gravel",
                }
            ],
            "rock_profile": [],
            "spt": [
                {"spt_depth": 1, "blows_15": 1, "blows_30": 1,
                 "blows_45": 1, "n_value": 2}
            ],
        },
    }
    if overrides:
        body.update(overrides)
    return body


class TestParseEndpoint:
    def test_requires_auth(self, client, pool):
        resp = client.post("/api/excel/workbook")
        # HTTPBearer's missing-header code differs across fastapi/starlette
        # versions (403 historically, 401 on newer releases). The contract
        # under test is "rejected without credentials", not the exact code.
        assert resp.status_code in (401, 403)

    def test_parse_returns_workbook_and_suggestions(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        resp = post_workbook_file(client)
        assert resp.status_code == 200
        body = resp.json()

        assert body["suggestions"]["borehole_id"] == "BH 2"
        assert body["suggestions"]["final_depth"] == 23.45
        assert len(body["workbook"]["borelog"]) == 2
        assert body["workbook"]["project_info"]["client_name"] == (
            "Mr. BEJOY MICHLE"
        )

    def test_empty_file_rejected(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        resp = client.post(
            "/api/excel/workbook",
            files={"file": ("empty.xlsx", b"", "application/octet-stream")},
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"]

    def test_bad_file_is_400_with_safe_message(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        resp = client.post(
            "/api/excel/workbook",
            files={
                "file": ("junk.xlsx", b"junk", "application/octet-stream")
            },
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 400
        assert "workbook" in resp.json()["detail"].lower()

    def test_csv_parse_uses_the_field_table_contract(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        resp = client.post(
            "/api/excel/workbook",
            files={
                "file": (
                    "borelog.csv",
                    b"Depth From (m),Depth To (m),Soil Description\n"
                    b"0,1.5,Filling Gravel\n",
                    "text/csv",
                )
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["source_format"] == "csv"
        assert body["dataset"] == "borelog"
        assert body["rows"] == [
            {
                "depth_from": Decimal("0"),
                "depth_to": Decimal("1.5"),
                "soil_description": "Filling Gravel",
                "sand_clay": None,
            }
        ]


class TestProjectImportEndpoint:
    def test_requires_auth(self, client, pool):
        resp = client.post(
            "/api/excel/projects",
            json=make_commit_body(),
        )
        # Version-dependent code (401/403); see TestParseEndpoint.
        assert resp.status_code in (401, 403)

    def test_creates_project_and_bulks_field_rows(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', None)

        resp = client.post(
            "/api/excel/projects",
            json=make_commit_body(),
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["project_id"] == "901"
        assert body["borehole_id"] == "BH 2"
        assert body["geol_rows"] == 1
        assert body["spt_rows"] == 1
        assert body["core_rows"] == 0

        # One bulk insert per table, inside one transaction.
        assert len(pool.calls_with("executemany", "GEOL")) == 1
        assert len(pool.calls_with("executemany", "ISPT")) == 1
        assert len(pool.calls_with("executemany", "CORE")) == 0
        assert pool.calls_with("begin", "BEGIN")
        assert pool.calls_with("commit", "COMMIT")

        # PROJ + LOCA inserts carry the payload values.
        proj_args = pool.last_args("execute", 'INSERT INTO "ags42"."PROJ"')
        assert proj_args[0] == "901"
        assert proj_args[2] == "CHAMPAKKULAM"
        loca_args = pool.last_args("execute", 'INSERT INTO "ags42"."LOCA"')
        assert loca_args[0] == "BH 2"
        assert loca_args[5] == "901"

        # Bulk rows carry PROJ_ID first (FK + NOT NULL on GEOL/CORE/ISPT).
        geol_args = pool.last_args("executemany", "GEOL")
        assert geol_args[0][0] == ("901", "BH 2", 0.0, 1.5,
                                   "Filling Gravel", None)

    def test_creates_metadata_and_party_fields_in_one_transaction(
        self, client, pool
    ):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', None)

        body = make_commit_body({
            "consultant_name": "Consultant One",
            "contractor_name": "Contractor One",
            "metadata": {
                "project_type": "LAB_AND_REPORT",
                "road_reference": "NH-66",
                "chainage_text": "KM 45+200",
                "structure_reference": "Admin Block",
                "selected_boreholes": "BH 2",
                "report_type": "Factual",
                "report_title": "Geotechnical Investigation",
                "report_volume_title": "Volume I",
                "document_reference": "TDAC-001",
                "revision": "R0",
                "report_date": "2026-09-25",
                "issue_status": "Draft",
                "tdac_company_name": "TDAC",
                "groundwater_basis": "Borehole observations",
            },
        })

        resp = client.post(
            "/api/excel/projects",
            json=body,
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        proj_args = pool.last_args("execute", 'INSERT INTO "ags42"."PROJ"')
        assert proj_args[3] == "Mr. BEJOY MICHLE"
        assert proj_args[4] == "Consultant One"
        assert proj_args[5] == "Contractor One"

        metadata_calls = pool.calls_with(
            "execute", 'INSERT INTO "tdac"."PROJ_METADATA"'
        )
        assert len(metadata_calls) == 1
        metadata_args = metadata_calls[0][2]
        assert metadata_args[0] == "901"
        assert metadata_args[1] == "NH-66"
        assert metadata_args[2] == "KM 45+200"
        assert metadata_args[5] == "LAB_AND_REPORT"

        begin_index = next(
            index for index, call in enumerate(pool.calls)
            if call[0] == "begin"
        )
        metadata_index = pool.calls.index(metadata_calls[0])
        commit_index = next(
            index for index, call in enumerate(pool.calls)
            if call[0] == "commit"
        )
        assert begin_index < metadata_index < commit_index

    def test_duplicate_project_is_409(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)

        resp = client.post(
            "/api/excel/projects",
            json=make_commit_body(),
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]
        # Nothing written when the project exists.
        assert not pool.calls_with("execute", 'INSERT INTO "ags42"."PROJ"')

    def test_borehole_id_falls_back_to_sheet(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', None)

        body = make_commit_body({"borehole_id": None})
        resp = client.post(
            "/api/excel/projects",
            json=body,
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 200
        loca_args = pool.last_args("execute", 'INSERT INTO "ags42"."LOCA"')
        assert loca_args[0] == "BH 2"

    def test_missing_borehole_everywhere_is_400(self, client, pool):
        pool.route("WHERE u.id", make_user_row())

        body = make_commit_body()
        body["workbook"]["project_info"]["borehole_number"] = None
        resp = client.post(
            "/api/excel/projects",
            json=body,
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 400
        assert "borehole" in resp.json()["detail"].lower()
        assert not pool.calls_with("execute", 'INSERT INTO "ags42"."PROJ"')

    def test_commit_revalidates_depth_order_before_database(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        body = make_commit_body()
        body["workbook"]["borelog"][0]["depth_to"] = 0

        resp = client.post(
            "/api/excel/projects",
            json=body,
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 400
        assert "greater" in resp.json()["detail"].lower()
        assert not pool.calls_with("begin", "BEGIN")
        assert not pool.calls_with("execute", 'INSERT INTO "ags42"."PROJ"')

    def test_commit_revalidates_duplicate_keys_before_database(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        body = make_commit_body()
        body["workbook"]["borelog"].append(
            dict(body["workbook"]["borelog"][0])
        )

        resp = client.post(
            "/api/excel/projects",
            json=body,
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 400
        assert "duplicate" in resp.json()["detail"].lower()
        assert not pool.calls_with("begin", "BEGIN")
        assert not pool.calls_with("execute", 'INSERT INTO "ags42"."PROJ"')


class TestLocaImportEndpoint:
    def test_requires_auth(self, client, pool):
        resp = client.post(
            "/api/excel/projects/901/locas",
            json={"borehole_type": "BH", "workbook": {}},
        )
        # Version-dependent code (401/403); see TestParseEndpoint.
        assert resp.status_code in (401, 403)

    def test_adds_loca_to_existing_project(self, client, pool):
        pool.route("WHERE u.id", make_user_row())

        def proj_lookup(project_id):
            return 1 if project_id == "901" else None

        pool.route(
            'FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', proj_lookup
        )
        pool.route(
            'FROM "ags42"."LOCA"'
            ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
            lambda project_id, loca_id: None,
        )

        resp = client.post(
            "/api/excel/projects/901/locas",
            json={
                "borehole_type": "BH",
                "workbook": make_commit_body()["workbook"],
            },
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["borehole_id"] == "BH 2"
        assert body["geol_rows"] == 1

        loca_args = pool.last_args("execute", 'INSERT INTO "ags42"."LOCA"')
        assert loca_args[5] == "901"

    def test_missing_project_is_404(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route(
            'FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', lambda *a: None
        )

        resp = client.post(
            "/api/excel/projects/404/locas",
            json={
                "borehole_type": "BH",
                "workbook": make_commit_body()["workbook"],
            },
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 404
        assert not pool.calls_with("execute", 'INSERT INTO "ags42"."LOCA"')

    def test_existing_loca_is_409(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)
        pool.route(
            'FROM "ags42"."LOCA"'
            ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
            lambda *a: 1,
        )

        resp = client.post(
            "/api/excel/projects/901/locas",
            json={
                "borehole_type": "BH",
                "workbook": make_commit_body()["workbook"],
            },
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]
        assert not pool.calls_with("execute", 'INSERT INTO "ags42"."LOCA"')

    def test_workbook_from_other_project_is_409(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)

        workbook = make_commit_body()["workbook"]
        workbook["project_info"]["project_id"] = "other-project"

        resp = client.post(
            "/api/excel/projects/901/locas",
            json={"borehole_type": "BH", "workbook": workbook},
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 409
        assert "belongs to" in resp.json()["detail"]

    def test_workbook_without_borehole_is_400(self, client, pool):
        pool.route("WHERE u.id", make_user_row())

        workbook = make_commit_body()["workbook"]
        workbook["project_info"]["borehole_number"] = None

        resp = client.post(
            "/api/excel/projects/901/locas",
            json={"borehole_type": "BH", "workbook": workbook},
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 400
        assert "borehole" in resp.json()["detail"]


class TestFieldTableImportEndpoint:
    def test_requires_auth(self, client, pool):
        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "borelog",
                "rows": [
                    {
                        "depth_from": 0,
                        "depth_to": 1,
                        "soil_description": "Fill",
                    }
                ],
            },
        )
        assert resp.status_code in (401, 403)

    def test_rejects_empty_field_table_before_database(self, client, pool):
        pool.route("WHERE u.id", make_user_row())

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={"dataset": "borelog", "rows": []},
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 400
        assert "no data rows" in resp.json()["detail"].lower()
        assert not pool.calls_with("begin", "BEGIN")

    def test_appends_validated_rows_to_an_existing_location(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route(
            'FROM "ags42"."LOCA"'
            ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
            1,
        )

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "borelog",
                "rows": [
                    {
                        "depth_from": "0",
                        "depth_to": "1.5",
                        "soil_description": "Filling Gravel",
                    }
                ],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["dataset"] == "borelog"
        assert body["rows"] == 1
        args = pool.last_args("executemany", '"ags42"."GEOL"')
        assert args[0][0] == (
            "901",
            "BH 1",
            Decimal("0"),
            Decimal("1.5"),
            "Filling Gravel",
            None,
        )

    def test_rejects_invalid_rows_before_acquiring_a_connection(self, client, pool):
        pool.route("WHERE u.id", make_user_row())

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "borelog",
                "rows": [
                    {
                        "depth_from": 0,
                        "depth_to": "not-a-number",
                    }
                ],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 400
        assert "invalid" in resp.json()["detail"].lower()
        assert not pool.calls_with("begin", "BEGIN")
        assert not pool.calls_with("executemany", '"ags42"."GEOL"')

    def test_missing_location_is_rejected_before_insert(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route(
            'FROM "ags42"."LOCA"'
            ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
            None,
        )

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "spt",
                "rows": [
                    {
                        "spt_depth": 1,
                        "n_value": 3,
                    }
                ],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 404
        assert not pool.calls_with("executemany", '"ags42"."ISPT"')


class TestNoSchemaGrowth:
    """The import touches only existing columns; pin that here."""

    def test_inserts_reference_no_new_columns(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', None)

        resp = client.post(
            "/api/excel/projects",
            json=make_commit_body(),
            headers=auth_header(user_id=1),
        )
        assert resp.status_code == 200

        allowed = {
            "PROJ": {
                "PROJ_ID", "PROJ_NAME", "PROJ_LOC", "PROJ_CLNT",
                "PROJ_ENG", "PROJ_CONT"
            },
            "LOCA": {"LOCA_ID", "LOCA_TYPE", "LOCA_STAR", "LOCA_ENDD",
                     "LOCA_FDEP", "PROJ_ID"},
            "GEOL": {"PROJ_ID", "LOCA_ID", "GEOL_TOP", "GEOL_BASE",
                     "GEOL_DESC", "GEOL_GEOL"},
            "CORE": {"PROJ_ID", "LOCA_ID", "CORE_TOP", "CORE_BASE",
                     "CORE_PREC", "CORE_RQD", "CORE_REM"},
            "ISPT": {"PROJ_ID", "LOCA_ID", "ISPT_TOP", "ISPT_INC1",
                     "ISPT_INC2", "ISPT_INC3", "ISPT_NVAL"},
        }

        import re as _re

        for method, sql, _args in pool.calls:
            for table, columns in allowed.items():
                pattern = _re.compile(
                    rf'INSERT INTO "ags42"\."{table}" \((.*?)\)'
                )
                match = pattern.search(sql)
                if match:
                    used = {
                        c.strip().strip('"')
                        for c in match.group(1).split(",")
                    }
                    unknown = used - columns
                    assert not unknown, (
                        f"{table} insert references unknown columns: "
                        f"{unknown}"
                    )


class TestImportAttribution:
    """Imported rows must record who imported them.

    The AGS tables (GEOL/CORE/ISPT) carry no author column, so the Borehole,
    Sampling and SPT tabs read created_by from the tdac attribution tables.
    Writing the AGS rows without those left every imported row showing a
    dash under Created By, and left CORE/ISPT with no Sample ID at all.
    """

    def _route_location(self, pool):
        pool.route("WHERE u.id", make_user_row())
        pool.route(
            'FROM "ags42"."LOCA"'
            ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
            1,
        )

    def test_borelog_import_writes_the_importer(self, client, pool):
        self._route_location(pool)

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "borelog",
                "rows": [{"depth_from": "0", "depth_to": "1.5",
                          "soil_description": "Fill"}],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        meta = pool.calls_with("executemany", '"BOREHOLE_RECORD_META"')
        assert meta, "no borehole attribution written"
        # created_by is the authenticated user, taken from the token.
        assert meta[-1][2][0][0][-1] == 1

    def test_rock_import_allocates_a_sample_id(self, client, pool):
        self._route_location(pool)

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "rock_profile",
                "rows": [{"depth_from": "2", "depth_to": "3",
                          "rock_description": "Granite"}],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        assert pool.calls_with(
            "fetchrow", '"SAMPLE_ID_COUNTER"'
        ), "core import did not allocate a Sample ID"
        samp = pool.calls_with("executemany", '"SAMPLING_RECORD_ID"')
        assert samp, "no sampling attribution written"
        # The whole block is written in one statement now, with the sample
        # ids allocated by a single counter call.
        assert samp[-1][2][0][0][0] == "901-1", f"got {samp[-1][2][0][0]}"
        counter = pool.calls_with("fetchrow", "SAMPLE_ID_COUNTER")
        assert counter, "sample ids were not allocated"

    def test_spt_import_is_queued_for_approval(self, client, pool):
        self._route_location(pool)

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "spt",
                "rows": [{"spt_depth": "2.5", "blows_15": "3",
                          "n_value": "6"}],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        st = pool.calls_with("executemany", '"SPT_RECORD_STATUS"')
        assert st, "no spt attribution written"
        # The CHECK allows PENDING/APPROVED/REJECTED. An import is not an
        # approval, so it must enter the queue as PENDING.
        assert "PENDING" in st[-1][1]
        assert "DRAFT" not in st[-1][1]
        assert st[-1][2][0][0][-1] == 1, f"got {st[-1][2][0][0]}"

    def test_attribution_rolls_back_with_a_failed_insert(self, client, pool):
        """A duplicate insert must not leave attribution rows behind."""
        self._route_location(pool)

        def _boom(*args):
            raise asyncpg.UniqueViolationError("duplicate key")

        pool.route('"ags42"."GEOL"', _boom)

        resp = client.post(
            "/api/excel/projects/901/locas/BH 1/field-table",
            json={
                "dataset": "borelog",
                "rows": [{"depth_from": "0", "depth_to": "1",
                          "soil_description": "Fill"}],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 409
        assert not pool.calls_with("executemany", '"BOREHOLE_RECORD_META"')

    def test_project_import_writes_attribution(self, client, pool):
        """The full project import must attribute rows too.

        It reaches the writer through _insert_field_rows, not the
        field-table route, so it needs its own cover.
        """
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', None)

        resp = client.post(
            "/api/excel/projects",
            json=make_commit_body(),
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        meta = pool.calls_with("executemany", '"BOREHOLE_RECORD_META"')
        assert meta, "project import wrote no borehole attribution"
        assert meta[-1][2][0][0][-1] == 1

    def test_loca_import_writes_attribution(self, client, pool):
        """Adding a borehole to an existing project also attributes rows."""
        pool.route("WHERE u.id", make_user_row())
        pool.route('FROM "ags42"."PROJ" WHERE "PROJ_ID" = $1', 1)

        pool.route(
            'FROM "ags42"."LOCA"'
            ' WHERE "PROJ_ID" = $1 AND "LOCA_ID" = $2',
            lambda project_id, loca_id: None,
        )

        resp = client.post(
            "/api/excel/projects/901/locas",
            json={
                "borehole_type": "BH",
                "workbook": make_commit_body()["workbook"],
            },
            headers=auth_header(user_id=1),
        )

        assert resp.status_code == 200
        meta = pool.calls_with("executemany", '"BOREHOLE_RECORD_META"')
        assert meta, "loca import wrote no borehole attribution"
        assert meta[-1][2][0][0][-1] == 1
