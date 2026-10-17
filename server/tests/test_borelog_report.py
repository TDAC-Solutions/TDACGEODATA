"""Borelog report: Field Data -> Overview.

Drives the real router, data source and layout module against FakePool (no live
database), the way test_rock_workflow.py and test_spt_edit_approval.py do, and
exercises the v6 port through the same route.

Covers:
  * the AGS mapping, including the one that matters most here -- a Rock run
    writes both a CORE row and a GEOL interval, so the report has to emit it
    once, as rock, not twice
  * only APPROVED rock runs reach the report
  * the cross-project filter (PROJ_ID *and* LOCA_ID on every query)
  * the JSON preview: continuous rows, depth-ordered, no page break
  * preview and PDF agree, because both come from build_log_rows()
  * pagination: 20 m a page, and the page count is reported to the client
  * the PDF really is a PDF, with one page per 20 m
  * the renderer's own rules: the >50 dot saturation, NIL percentages, the
    water-table and termination markers, SPT below the soil/rock contact
  * a location from another project is a 404
  * the PDF memo is keyed on the data, so a changed borehole re-renders
  * the v6 rock appendix: its "useful row" filter, NIL percentages, the
    page badge, and that it is joined behind the log's own pages
  * the v6 soil-profile narrative: the transition phrases, the SPT summary
    clauses (values, ranges, rebound, rock), and the .docx the endpoint
    serves
"""
from decimal import Decimal

import pytest

from app.borelog_report.layout import (
    COLUMNS,
    MAX_DEPTH_PER_PAGE,
    SPT_PENETRATION,
    Layer,
    ReportData,
    ReportHeader,
    SptTest,
    build_log_rows,
    format_pct,
)
from tests.conftest import auth_header, make_user_row, route_users_by_id

BASE = "/api/portfolio/projects/P1/locas/L1/borelog-report"

PDF_MAGIC = b"%PDF"
PDF_PAGE_MARKER = b"/Type /Page"


def _project(project_type="ROAD RESURFACING"):
    return {
        "PROJ_NAME": "A1 Upgrade",
        "PROJ_LOC": "Kilometre 12",
        "PROJ_CLNT": "Highways Dept",
        "PROJECT_TYPE": project_type,
    }


def _loca(final_depth=Decimal("30.0"), water=Decimal("4.5")):
    return {
        "LOCA_ID": "L1",
        "LOCA_FDEP": final_depth,
        "LOCA_STAR": None,
        "LOCA_ENDD": None,
        "groundwater_depth": water,
    }


def _geol(*rows):
    """(from, to, description)"""
    return [
        {"depth_from": Decimal(str(a)), "depth_to": Decimal(str(b)), "description": d}
        for a, b, d in rows
    ]


def _spt(*rows):
    """(depth, blows15, blows30, blows45, n)"""
    return [
        {
            "spt_depth": Decimal(str(d)),
            "blows_15": None if b15 is None else Decimal(str(b15)),
            "blows_30": None if b30 is None else Decimal(str(b30)),
            "blows_45": None if b45 is None else Decimal(str(b45)),
            "n_value": None if n is None else Decimal(str(n)),
        }
        for d, b15, b30, b45, n in rows
    ]


def _rock(*rows):
    """(from, to, recovery, rqd, remark, description)"""
    return [
        {
            "depth_from": Decimal(str(a)),
            "depth_to": Decimal(str(b)),
            "recovery": None if rec is None else Decimal(str(rec)),
            "rqd": None if rqd is None else Decimal(str(rqd)),
            "remark": remark,
            "description": description,
        }
        for a, b, rec, rqd, remark, description in rows
    ]


def _seed(pool, *, project=None, loca=None, geol=(), spt=(), rock=()):
    """Route every query the report issues. Order matters: FakePool takes the
    first matching substring, so the more specific rock query is routed before
    the plain GEOL one."""
    # FakePool answers from the FIRST route whose substring matches, so a
    # re-seed inside one test would keep serving the earlier rows.
    pool.routes.clear()
    route_users_by_id(pool, {1: make_user_row(id=1)})

    pool.route('"tdac"."ROCK_RECORD"', list(rock))
    pool.route('"ags42"."GEOL"', list(geol))
    pool.route('"ags42"."ISPT"', list(spt))
    pool.route('"ags42"."LOCA"', loca if loca is not None else _loca())
    pool.route('"ags42"."PROJ"', project if project is not None else _project())


@pytest.fixture(autouse=True)
def _clear_pdf_cache():
    from app.borelog_report import router as report_router

    report_router.reset_pdf_cache()
    yield
    report_router.reset_pdf_cache()


def _report(client, pool, path=BASE):
    response = client.get(path, headers=auth_header())
    assert response.status_code == 200, response.text
    return response.json()


def _pdf(client, pool):
    response = client.get(f"{BASE}/pdf", headers=auth_header())
    assert response.status_code == 200, response.text
    return response


# ---------------------------------------------------------------------------
# The one mapping that can double-count
# ---------------------------------------------------------------------------


class TestRockIsNotCountedTwice:
    def test_approved_run_appears_once_as_rock(self, client, pool):        # The Rock workflow writes a CORE run *and* a GEOL interval for it, so
        # an approved run is present in both result sets.
        _seed(
            pool,
            geol=_geol((0.0, 10.0, "Made Ground"), (10.0, 14.0, "Fresh GRANITE")),
            rock=_rock((10.0, 14.0, 92.0, 70.0, "Run 1", "Fresh GRANITE")),
        )

        body = _report(client, pool)

        granites = [r for r in body["rows"] if "GRANITE" in r["description"]]
        assert len(granites) == 1, body["rows"]
        assert granites[0]["is_rock"] is True
        assert granites[0]["recovery_text"] == "92%"
        assert granites[0]["rqd_text"] == "70%"
        assert granites[0]["remark"] == "Run 1"

    def test_pending_run_is_not_in_the_report(self, client, pool):
        # The report's query filters STATUS = 'APPROVED'; the fake pool cannot
        # evaluate that, so this asserts the filter is actually in the SQL.
        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))

        _report(client, pool)

        rock_sql = pool.calls_with("fetch", '"tdac"."ROCK_RECORD"')[0][1]
        assert "'APPROVED'" in rock_sql

    def test_a_geol_interval_with_the_same_span_as_rock_is_the_rock_row(
        self, client, pool
    ):
        # A soil interval the user typed over the same depths is replaced, not
        # doubled -- two rows for one span would break the log's continuity.
        _seed(
            pool,
            geol=_geol((0.0, 10.0, "Made Ground"), (10.0, 14.0, "To be confirmed")),
            rock=_rock((10.0, 14.0, None, None, "", "Weathered SCHIST")),
        )

        body = _report(client, pool)

        spans = [
            (r["depth_from"], r["depth_to"])
            for r in body["rows"]
            if r["kind"] == "layer"
        ]
        assert spans == [(0.0, 10.0), (10.0, 14.0)]
        assert "To be confirmed" not in str(body["rows"])

    def test_rock_without_a_geol_interval_still_reports(self, client, pool):
        # A rock run whose GEOL row is missing must not vanish from the log.
        _seed(
            pool,
            geol=_geol((0.0, 10.0, "Made Ground")),
            rock=_rock((10.0, 14.0, 80.0, 55.0, "", None)),
        )

        body = _report(client, pool)

        rock_rows = [r for r in body["rows"] if r["is_rock"]]
        assert len(rock_rows) == 1
        assert rock_rows[0]["description"] == ""


class TestImportedAndUnapprovedData:
    """B2/B3: the report must show imported coring data and must not show
    unapproved SPT values. The fake pool cannot evaluate SQL predicates, so
    these assert the report's queries carry the filters."""

    def test_spt_values_are_gated_on_the_approval_ledger(self, client, pool):
        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))

        _report(client, pool)

        spt_sql = pool.calls_with("fetch", '"ags42"."ISPT"')[0][1]
        assert '"tdac"."SPT_RECORD_STATUS"' in spt_sql
        # PENDING/REJECTED values are withheld; rows with no ledger row are
        # legacy data with no approval state to withhold.
        assert 'sr."STATUS" IS NULL OR sr."STATUS" = \'APPROVED\'' in spt_sql

    def test_imported_rock_runs_survive_without_a_rock_record(self, client, pool):
        _seed(pool, geol=_geol((0.0, 14.0, "GRANITE")))

        _report(client, pool)

        rock_sql = pool.calls_with("fetch", '"tdac"."ROCK_RECORD"')[0][1]
        # CORE drives the query with ROCK_RECORD left-joined, so the
        # spreadsheet import's coring rows (which never write ROCK_RECORD)
        # reach the report; workflow rows still need approval.
        assert 'FROM "ags42"."CORE" c' in rock_sql
        assert 'LEFT JOIN "tdac"."ROCK_RECORD" rr' in rock_sql
        assert 'rr."PROJ_ID" IS NULL' in rock_sql
        assert 'rr."STATUS" = \'APPROVED\'' in rock_sql

    def test_imported_rock_description_falls_back_to_covering_geol(self, client, pool):
        _seed(pool, geol=_geol((0.0, 14.0, "GRANITE")))

        _report(client, pool)

        rock_sql = pool.calls_with("fetch", '"tdac"."ROCK_RECORD"')[0][1]
        # The import writes no GEOL interval for a run, so "Type of Rock"
        # falls back to the GEOL interval that covers the run's span.
        assert "COALESCE(g.\"GEOL_DESC\", cover.\"GEOL_DESC\")" in rock_sql
        assert 'LEFT JOIN LATERAL' in rock_sql


class TestLogo:
    def test_logo_candidates_are_file_paths_not_directories(self):
        from app.borelog_report.router import _logo_candidates

        candidates = _logo_candidates()

        assert candidates, "at least one candidate must be offered"
        assert {candidate.name for candidate in candidates} == {
            "TDAC GEOTECH LOGO1.png",
            "tdac_logo.png",
            "logo.png",
        }
        for candidate in candidates:
            # Directories made every read raise IsADirectoryError, which
            # _load_logo swallows as OSError -- the logo never loaded.
            assert candidate.name.endswith(".png")
            assert candidate.parent.name == "assets"


# ---------------------------------------------------------------------------
# Cross-project isolation
# ---------------------------------------------------------------------------


class TestProjectIsolation:
    def test_every_query_filters_both_project_and_location(self, client, pool):
        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))

        _report(client, pool)

        report_queries = [
            sql
            for method, sql, _ in pool.calls
            if method == "fetch" and "PROJ_ID" in sql and "LOCA_ID" in sql
        ]
        assert report_queries, "no field-data query was issued"
        for sql in report_queries:
            assert '"PROJ_ID" = $1' in sql or '"PROJ_ID" = l."PROJ_ID"' in sql
            assert '"LOCA_ID" = $2' in sql or '"LOCA_ID" = l."LOCA_ID"' in sql

    def test_location_from_another_project_is_404(self, client, pool):
        route_users_by_id(pool, {1: make_user_row(id=1)})
        # No LOCA row routed: the location does not exist in P1.
        pool.route('"tdac"."ROCK_RECORD"', [])
        pool.route('"ags42"."GEOL"', [])
        pool.route('"ags42"."ISPT"', [])
        pool.route('"ags42"."PROJ"', _project())

        response = client.get(
            "/api/portfolio/projects/P1/locas/OTHER/borelog-report",
            headers=auth_header(),
        )

        assert response.status_code == 404

    def test_unknown_project_is_404(self, client, pool):
        route_users_by_id(pool, {1: make_user_row(id=1)})
        # No PROJ row routed.
        pool.route('"ags42"."LOCA"', _loca())

        response = client.get(
            "/api/portfolio/projects/NOPE/locas/L1/borelog-report",
            headers=auth_header(),
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# The preview
# ---------------------------------------------------------------------------


class TestPreviewIsContinuous:
    def test_no_page_break_in_the_preview(self, client, pool):
        # 45 m of borehole: three PDF pages. The preview must be one list.
        _seed(
            pool,
            loca=_loca(final_depth=Decimal("45.0")),
            geol=_geol(
                (0.0, 12.0, "Made Ground"),
                (12.0, 25.0, "Sandy CLAY"),
                (25.0, 38.0, "Dense SAND"),
                (38.0, 45.0, "Stiff CLAY"),
            ),
        )

        body = _report(client, pool)

        assert body["pdf_page_count"] == 3
        assert body["max_depth_per_page"] == MAX_DEPTH_PER_PAGE
        # Nothing in the payload describes pages: the client cannot split
        # because it is never told where the breaks are.
        assert "pages" not in body
        assert [r for r in body["rows"] if r["kind"] == "layer"] != []
        assert all("page" not in key for key in body["rows"][0])

    def test_payload_splits_rows_for_the_columns(self, client, pool):
        # The depth-proportional log draws each column from its own stream, so
        # the payload carries `layers` and `spt` as well as the ordered `rows`.
        # All three must be projections of one assembly, never separate queries:
        # if they disagreed, the log would show a stratum the PDF does not have.
        _seed(
            pool,
            geol=_geol((0.0, 8.0, "Made Ground"), (8.0, 20.0, "Stiff CLAY")),
            spt=_spt((1.5, 2, 3, 4, 9.0), (6.0, 6, 8, 10, 22.0)),
            rock=_rock((20.0, 26.0, 88.0, 61.0, "", "LIMESTONE")),
            loca=_loca(final_depth=Decimal("26.0"), water=Decimal("3.2")),
        )

        body = _report(client, pool)

        layers = [row for row in body["rows"] if row["kind"] == "layer"]
        assert body["layers"] == layers
        assert body["spt"] == [row for row in body["rows"] if row["kind"] == "spt"]
        # Markers are not records and belong to neither column stream.
        assert all(row["kind"] == "layer" for row in body["layers"])
        assert all(row["kind"] == "spt" for row in body["spt"])
        assert len(body["layers"]) == body["summary"]["layer_count"]

    def test_spt_test_depth_is_the_base_of_the_drive(self, client, pool):
        # The log places a test at the base of its 45 cm drive, the same point
        # the PDF plots it at. Sending only the start depth would put the marker
        # half a metre too shallow on screen and correct on paper.
        _seed(
            pool,
            geol=_geol((0.0, 12.0, "Made Ground")),
            spt=_spt((2.0, 2, 3, 4, 9.0), (7.5, 10, 15, 20, 45.0)),
        )

        spt = _report(client, pool)["spt"]

        assert [test["spt_depth"] for test in spt] == [2.0, 7.5]
        assert [test["spt_test_depth"] for test in spt] == [
            pytest.approx(2.45),
            pytest.approx(7.95),
        ]

    def test_qualitative_spt_is_measured_at_its_start_depth(self, client, pool):
        # A worded test has no 45 cm drive, so its result belongs at the depth
        # recorded, not 45 cm below it.
        from app.borelog_report.layout import Layer, ReportData, SptTest, build_log_rows

        rows = build_log_rows(
            ReportData(
                header=ReportHeader(termination_depth=10.0),
                layers=(Layer(0.0, 10.0, "SAND"),),
                spt=(SptTest(3.0, n_value="rb"),),
            )
        )

        spt_row = next(row for row in rows if row.kind == "spt")
        assert spt_row.spt_test_depth == pytest.approx(3.0)

    def test_rows_are_depth_ordered(self, client, pool):
        _seed(
            pool,
            geol=_geol((0.0, 5.0, "Made Ground"), (5.0, 12.0, "Clay"), (12.0, 18.0, "SAND")),
            spt=_spt((2.0, 2, 3, 4, 9.0), (7.0, 4, 6, 8, 18.0)),
        )

        body = _report(client, pool)

        data_rows = [r for r in body["rows"] if r["kind"] in ("layer", "spt")]
        depths = [
            row["depth_from"]
            if row["kind"] == "layer"
            else row["spt_depth"] + SPT_PENETRATION
            for row in data_rows
        ]
        assert depths == sorted(depths)

    def test_header_carries_the_pdf_fields(self, client, pool):
        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))

        header = _report(client, pool)["header"]

        assert header["title"] == (
            "GEOTECHNICAL INVESTIGATION FOR THE PROPOSED\n"
            "ROAD RESURFACING AT Kilometre 12"
        )
        assert header["client_name"] == "Highways Dept"
        assert header["borehole_number"] == "L1"
        assert header["boring_type"] == "Rotary"
        assert header["water_table_text"] == "4.50 m"

    def test_columns_match_the_paper(self, client, pool):
        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))

        columns = _report(client, pool)["columns"]

        assert [c["id"] for c in columns] == [c.id for c in COLUMNS]
        # The widths the client renders with are the widths the PDF draws at.
        assert sum(c["percent"] for c in columns) == pytest.approx(100.0, abs=0.01)

    def test_derived_values_come_from_the_server(self, client, pool):
        _seed(
            pool,
            geol=_geol((0.0, 4.5, "Made Ground")),
            spt=_spt((2.0, 2, 3, 4, 55.0)),
        )

        row = next(
            r for r in _report(client, pool)["rows"] if r["kind"] == "spt"
        )

        assert row["thickness"] is None
        assert row["spt_depth_text"] == "2.00 – 2.45"
        assert row["n_text"] == ">50"
        assert row["n_plot_text"] == ">50"
        # Saturating scale: a 55 sits inside the column, as on paper.
        assert row["n_plot_fraction"] == pytest.approx(40 / 60)

    def test_empty_location_reports_rather_than_crashing(self, client, pool):
        _seed(pool, geol=(), spt=(), rock=(), loca=_loca(final_depth=None, water=None))

        body = _report(client, pool)

        assert body["rows"] == []
        assert body["summary"]["layer_count"] == 0
        assert body["header"]["termination_depth"] is None
        assert body["header"]["water_table_text"] == "Not met with"


# ---------------------------------------------------------------------------
# Preview / PDF agreement -- the whole point of the shared layout
# ---------------------------------------------------------------------------


class TestPreviewMatchesPdf:
    def test_both_endpoints_render_the_same_row_list(self, client, pool, monkeypatch):
        _seed(
            pool,
            geol=_geol((0.0, 8.0, "Made Ground"), (8.0, 20.0, "Stiff CLAY")),
            spt=_spt((1.5, 2, 3, 4, 9.0), (6.0, 6, 8, 10, 22.0)),
            rock=_rock((20.0, 26.0, 88.0, 61.0, "Run 3", "Weathered LIMESTONE")),
            loca=_loca(final_depth=Decimal("26.0"), water=Decimal("3.2")),
        )

        # Record before the PDF is requested, or the render happens unobserved.
        recorded = _record_draws(monkeypatch)

        body = _report(client, pool)
        pdf = _pdf(client, pool)

        assert pdf.content.startswith(PDF_MAGIC)

        # The rock block is drawn as one multi-line string, so flatten before
        # searching for a single line of it.
        drawn = "\n".join(recorded)
        assert drawn, "the renderer placed no text at all"

        # Every description the preview shows is one the sheet prints. Read from
        # the preview's own rows, so the assertion cannot pass by both sides
        # drifting to some third value.
        descriptions = [
            row["description"] for row in body["rows"] if row["kind"] == "layer"
        ]
        assert descriptions == [
            "Made Ground",
            "Stiff CLAY",
            "Weathered LIMESTONE",
        ]
        for description in descriptions:
            assert description in drawn

        # Markers agree too, at the same values.
        assert body["header"]["water_table"] == pytest.approx(3.2)
        assert body["header"]["termination_depth"] == pytest.approx(26.0)
        assert "Water Table at 3.20 m" in drawn
        assert "THE BOREHOLE WAS TERMINATED AT 26.00 m DEPTH" in drawn
        assert "CORE RECOVERY = 88%" in drawn
        assert "RQD = 61%" in drawn

        # And the N-values the preview shows are the ones placed on the sheet.
        n_values = [row["n_text"] for row in body["rows"] if row["kind"] == "spt"]
        assert n_values == ["9", "22"]
        for text in n_values:
            assert text in drawn

    def test_termination_depth_is_the_deepest_of_log_and_declaration(
        self, client, pool
    ):
        # Logged strata stop at 22 m; the location was drilled to 30 m. The log
        # must run to 30, or the last 8 m of hole would be missing.
        _seed(
            pool,
            loca=_loca(final_depth=Decimal("30.0")),
            geol=_geol((0.0, 22.0, "Made Ground")),
        )

        header = _report(client, pool)["header"]

        assert header["termination_depth"] == 30.0


# ---------------------------------------------------------------------------
# Pagination and the PDF itself
# ---------------------------------------------------------------------------


class TestPdfPagination:
    @pytest.mark.parametrize(
        "depth,pages",
        [(12.0, 1), (20.0, 1), (20.5, 2), (45.0, 3), (41.5, 3), (60.0, 3)],
    )
    def test_pages_are_twenty_metres(self, client, pool, depth, pages):
        _seed(
            pool,
            loca=_loca(final_depth=Decimal(str(depth))),
            geol=_geol((0.0, depth, "Made Ground")),
        )

        body = _report(client, pool)

        assert body["pdf_page_count"] == pages

    def test_pdf_has_one_page_per_twenty_metres(self, client, pool):
        _seed(
            pool,
            loca=_loca(final_depth=Decimal("45.0")),
            geol=_geol((0.0, 20.0, "A"), (20.0, 40.0, "B"), (40.0, 45.0, "C")),
        )

        pdf = _pdf(client, pool)

        assert pdf.content.startswith(PDF_MAGIC)
        # /Type /Pages is the tree node; subtract it from the /Type /Page count.
        pages = pdf.content.count(PDF_PAGE_MARKER) - pdf.content.count(
            b"/Type /Pages"
        )
        assert pages == 3, pdf.content.count(PDF_PAGE_MARKER)

    def test_no_data_is_a_404_not_an_empty_pdf(self, client, pool):
        _seed(pool, geol=(), spt=(), rock=(), loca=_loca(final_depth=None))

        response = client.get(f"{BASE}/pdf", headers=auth_header())

        assert response.status_code == 404
        assert "borelog" in response.json()["detail"].lower()

    def test_pdf_is_not_cached_by_the_browser(self, client, pool):
        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))

        response = _pdf(client, pool)

        # Project data behind a token must not survive in a shared cache.
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["content-type"] == "application/pdf"


# ---------------------------------------------------------------------------
# The renderer memo
# ---------------------------------------------------------------------------


class TestPdfMemo:
    def test_same_data_renders_once(self, client, pool, monkeypatch):
        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))

        from app.borelog_report import router as report_router

        calls = []
        real = report_router._renderer().render_borelog_pdf

        def counted(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        monkeypatch.setattr(report_router._renderer(), "render_borelog_pdf", counted)

        first = _pdf(client, pool)
        second = _pdf(client, pool)

        assert len(calls) == 1, "the second request re-rendered identical data"
        assert first.content == second.content

    def test_changed_data_renders_again(self, client, pool, monkeypatch):
        from app.borelog_report import router as report_router

        calls = []
        real = report_router._renderer().render_borelog_pdf
        monkeypatch.setattr(
            report_router._renderer(),
            "render_borelog_pdf",
            lambda *a, **k: (calls.append(1), real(*a, **k))[1],
        )

        _seed(pool, geol=_geol((0.0, 5.0, "Made Ground")))
        _pdf(client, pool)
        assert len(calls) == 1

        # A different depth range is a different log; the key must notice.
        _seed(pool, geol=_geol((0.0, 9.0, "Made Ground, deeper")))
        _pdf(client, pool)

        assert len(calls) == 2

    def test_fingerprint_tracks_the_data(self):
        from app.borelog_report.router import _fingerprint

        one = {"rows": [{"depth_from": 0.0}]}
        two = {"rows": [{"depth_from": 1.0}]}

        assert _fingerprint(one) == _fingerprint({"rows": [{"depth_from": 0.0}]})
        assert _fingerprint(one) != _fingerprint(two)


# ---------------------------------------------------------------------------
# layout.py in isolation -- the rules the renderer depends on
# ---------------------------------------------------------------------------


class TestLayoutRules:
    def test_columns_fill_the_printable_width(self):
        # 19 cm between the margins. If this drifts, the log no longer reaches
        # the page edge the way the v6 sheet did.
        assert sum(column.width_cm for column in COLUMNS) == 19.0

    def test_page_count(self):
        assert ReportData(
            header=ReportHeader(termination_depth=20.0)
        ).page_count == 1
        assert ReportData(
            header=ReportHeader(termination_depth=20.0),
            layers=(Layer(0.0, 20.0, "x"),),
        ).page_count == 1
        assert ReportData(
            header=ReportHeader(termination_depth=41.5),
            layers=(Layer(0.0, 41.5, "x"),),
        ).page_count == 3

    def test_soil_end_depth_marks_the_rock_contact(self):
        data = ReportData(
            header=ReportHeader(termination_depth=30.0),
            layers=(
                Layer(0.0, 10.0, "Made Ground"),
                Layer(10.0, 20.0, "SAND"),
                Layer(20.0, 30.0, "GRANITE", is_rock=True),
            ),
        )

        assert data.soil_end_depth == 20.0

    def test_all_rock_borehole_has_no_soil_column(self):
        """B4: an all-rock log has no soil span at all. Returning the deepest
        rock base here let every in-rock N-value keep plotting in the SPT
        columns, which belong to the rock logging block."""
        data = ReportData(
            header=ReportHeader(termination_depth=30.0),
            layers=(Layer(0.0, 30.0, "GRANITE", is_rock=True),),
        )

        assert data.soil_end_depth == 0.0

    def test_all_rock_borehole_drops_in_rock_spt_values(self):
        data = ReportData(
            header=ReportHeader(termination_depth=30.0),
            layers=(Layer(0.0, 30.0, "GRANITE", is_rock=True),),
            spt=(SptTest(5.0, n_value=12.0),),
        )

        rows = build_log_rows(data)

        assert not [row for row in rows if row.kind == "spt"]

    def test_spt_below_the_soil_rock_contact_is_dropped(self, client, pool):
        # An N-value in rock is logged against the coring run, not the borehole;
        # the v6 log stops drawing N-values at the contact.
        _seed(
            pool,
            loca=_loca(final_depth=Decimal("30.0")),
            geol=_geol((0.0, 10.0, "SAND")),
            rock=_rock((10.0, 30.0, 95.0, 80.0, "", "GRANITE")),
            spt=_spt((5.0, 2, 3, 4, 12.0), (15.0, 50, 50, 50, 50.0)),
        )

        body = _report(client, pool)

        spt_rows = [r for r in body["rows"] if r["kind"] == "spt"]
        assert len(spt_rows) == 1
        assert spt_rows[0]["spt_depth"] == 5.0

    def test_qualitative_spt_is_measured_at_its_start_depth(self):
        # A worded test has no 45 cm drive, so it plots at the depth recorded.
        assert SptTest(7.0, n_value="rb").is_qualitative
        assert SptTest(7.0, n_value="rb").test_depth == 7.0
        assert SptTest(7.0, n_value="hard rock").test_depth == 7.0
        assert SptTest(7.0, n_value=9.0).test_depth == pytest.approx(7.45)

    def test_qualitative_n_value_text(self):
        assert SptTest(1.0, n_value="rb").n_text == "SPT Rebound"
        assert SptTest(1.0, n_value="rb").n_plot_text == "RB"
        assert SptTest(1.0, n_value="soft rock").n_text == "Soft Rock"
        assert SptTest(1.0, n_value="hard rock").n_plot_text == "Hard Rock"

    def test_n_value_over_fifty(self):
        assert SptTest(1.0, n_value=51.0).n_text == ">50"
        assert SptTest(1.0, n_value=50.0).n_text == "50"
        assert SptTest(1.0, n_value=50.0).n_plot_text == ""

    def test_missing_percentage_reads_nil(self):
        # v6 printed NIL for a missing *or zero* recovery. Zero recovery is a
        # real value, but the report has to keep saying what the sheet says.
        assert format_pct(None) == "NIL"
        assert format_pct(0.0) == "NIL"
        assert format_pct(Decimal("0")) == "NIL"
        assert format_pct(92.4) == "92%"
        assert format_pct("not logged") == "NIL"

    def test_hatches_rotate_through_the_log(self, client, pool):
        _seed(
            pool,
            geol=_geol(*[(i * 2.0, i * 2.0 + 2.0, f"L{i}") for i in range(4)]),
        )

        hatches = [
            r["hatch"] for r in _report(client, pool)["rows"] if r["kind"] == "layer"
        ]

        assert hatches == ["/", "\\", "x", "-"]

    def test_hatches_are_unique_enough_to_tell_layers_apart(self):
        from app.borelog_report.layout import HATCH_PATTERNS

        assert len(HATCH_PATTERNS) == 9
        assert len(set(HATCH_PATTERNS)) == 9

    def test_markers_sit_at_their_own_depth(self):
        data = ReportData(
            header=ReportHeader(water_table=4.5, termination_depth=12.0),
            layers=(Layer(0.0, 6.0, "SAND"), Layer(6.0, 12.0, "CLAY")),
            spt=(SptTest(2.0, 1, 1, 1, 5.0),),
        )

        rows = {row.kind: row for row in build_log_rows(data)}

        assert rows["water_table"].sort_depth == 4.5
        assert rows["termination"].sort_depth == 12.0
        # The termination note is the last thing on the log.
        assert build_log_rows(data)[-1].kind == "termination"

    def test_thickness_is_the_span(self):
        row = build_log_rows(
            ReportData(
                header=ReportHeader(termination_depth=5.0),
                layers=(Layer(1.5, 4.0, "SAND"),),
            )
        )[0]

        assert row.thickness == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# The PDF renderer, on a known log
# ---------------------------------------------------------------------------


class TestLabelCollision:
    """Two labels closer than a text height would print over one another.

    Nothing upstream prevents it: an SPT depth only has to be >= 0, and a
    stratum can be a tenth of a metre thick. Measured on the rendered page, 6 pt
    text is about 0.212 cm tall, so two tests 0.2 m apart on a 20 m page -- only
    0.219 cm of separation -- are the first to touch. The renderer nudges each
    label deeper until it clears the one above it.
    """

    def test_the_gap_clears_a_text_height(self):
        from app.borelog_report.pdf_renderer import (
            _TEXT_HEIGHT_CM,
            MIN_LABEL_GAP_CM,
        )

        # Six point type. If the font size changes, the gap must follow it,
        # or the guard silently stops working for the new size.
        assert _TEXT_HEIGHT_CM == pytest.approx(6 / 72 * 2.54)
        assert MIN_LABEL_GAP_CM > _TEXT_HEIGHT_CM

    def test_isolated_labels_keep_their_exact_depth(self):
        from app.borelog_report.layout import MAX_DEPTH_PER_PAGE, PLOT_HEIGHT_CM
        from app.borelog_report.pdf_renderer import _nudge_down

        # Well separated: 5 cm apart on a 21.9 cm plot.
        y_top = PLOT_HEIGHT_CM / 2
        assert _nudge_down(y_top, [y_top - 5.0]) == y_top
        assert _nudge_down(y_top, []) == y_top

    def test_a_colliding_label_is_nudged_deeper_not_shallower(self):
        from app.borelog_report.pdf_renderer import MIN_LABEL_GAP_CM, _nudge_down

        # y falls as depth increases, so "deeper" is a smaller y.
        shallower = 10.0
        candidate = 9.9  # 0.1 cm below the label already placed

        nudged = _nudge_down(candidate, [shallower])

        assert nudged < candidate, "must move down the page, never up"
        assert abs(nudged - shallower) >= MIN_LABEL_GAP_CM

    def test_a_run_of_labels_settles_evenly(self):
        from app.borelog_report.pdf_renderer import MIN_LABEL_GAP_CM, _nudge_down

        # Six labels 0.05 cm apart, far below the gap.
        used = [20.0]
        placed = []
        for _ in range(5):
            y = _nudge_down(used[-1] - 0.05, used)
            placed.append(y)
            used.append(y)

        for earlier, later in zip(placed, placed[1:]):
            assert later < earlier, "order must be preserved top to bottom"
            assert abs(later - earlier) >= MIN_LABEL_GAP_CM

    def test_a_saturated_log_still_keeps_depth_order(self, monkeypatch):
        # Sixty tests in 6 m is more than a page can show legibly. The surplus
        # has to pile somewhere; it must at least stay in depth order and on the
        # page, rather than being drawn at random.
        from app.borelog_report.layout import MARGIN_CM

        report = ReportData(
            header=ReportHeader(termination_depth=6.0),
            layers=tuple(
                Layer(i * 1.0, (i + 1) * 1.0, f"Stratum {i}") for i in range(6)
            ),
            spt=tuple(
                SptTest(round(i * 0.1, 2), 3, 5, 7, 12.0) for i in range(60)
            ),
        )

        rows = _rendered_rows(monkeypatch, report)
        ys = [r["y"] for r in rows if r["text"].count("\u2013") == 1]

        # Slightly fewer than 60: the deepest tests fall below the soil/rock
        # contact and the log stops plotting N-values there, as v6 does.
        assert len(ys) >= 50, f"only {len(ys)} SPT rows were drawn"
        for earlier, later in zip(ys, ys[1:]):
            assert later <= earlier, "depth order broken"
        assert min(ys) >= MARGIN_CM - 1e-9, "a row fell off the page"

    def test_a_marker_cannot_be_pushed_off_the_page(self):
        from app.borelog_report.layout import MARGIN_CM
        from app.borelog_report.pdf_renderer import _nudge_down

        # More labels packed below this one than could ever be drawn on a page.
        crowded = [MARGIN_CM + i * 0.01 for i in range(200)]

        assert _nudge_down(MARGIN_CM + 0.005, crowded) >= MARGIN_CM

    def test_spt_rows_do_not_overprint_when_tests_are_tightly_spaced(
        self, monkeypatch
    ):
        # Tests every 0.1 m: inside the plotted range of a single page, and far
        # closer than their own text is tall.
        report = ReportData(
            header=ReportHeader(
                project_type="ROAD", project_location="X", termination_depth=6.0
            ),
            layers=tuple(
                Layer(i * 1.0, (i + 1) * 1.0, f"Stratum {i}") for i in range(6)
            ),
            spt=tuple(
                SptTest(round(i * 0.1, 2), 3, 5, 7, 12.0) for i in range(60)
            ),
        )

        from app.borelog_report.layout import MARGIN_CM
        from app.borelog_report.pdf_renderer import MIN_LABEL_GAP_CM

        rows = [
            row
            for row in _rendered_rows(monkeypatch, report)
            if row["text"].count("\u2013") == 1
        ]

        assert len(rows) > 30, "expected the dense log to be drawn"

        # Depth order is preserved: every row is placed deeper than the one
        # above it, never lifted back up into the stratum it was taken in.
        ys = [row["y"] for row in rows]

        # Depth order is preserved: every row is placed deeper than the one
        # above it, never lifted back up into the stratum it was taken in.
        for earlier, later in zip(ys, ys[1:]):
            assert later <= earlier, "depth order must be preserved"

        # Nothing is pushed off the page, however crowded it is.
        assert min(ys) >= MARGIN_CM - 1e-9, "a row was pushed below the margin"

        # Depth order holds, and nothing is pushed off the page, however
        # crowded the log is. The surplus necessarily piles against the
        # margin: a 20 m page carries 21.9 cm of plot, about 68 labels at this
        # gap, and this log has 60 tests inside 6 m needing 19 cm in 6.6 cm. No
        # placement renders that legibly, and the guard's job is to space what
        # it can rather than to pretend otherwise.
        assert min(ys) >= MARGIN_CM - 1e-9, "a row was pushed below the margin"

    def test_a_dense_but_feasible_log_has_no_overlap_at_all(self, monkeypatch):
        # One test every 0.30 m down a 15 m hole: 50 tests needing 16 cm inside
        # the 16.4 cm the page gives them. Tight, but it fits -- so every row
        # must be legible, which is the case that actually matters.
        report = ReportData(
            header=ReportHeader(
                project_type="ROAD", project_location="X", termination_depth=15.0
            ),
            layers=tuple(
                Layer(i * 3.0, (i + 1) * 3.0, f"Stratum {i}") for i in range(5)
            ),
            spt=tuple(
                SptTest(round(i * 0.30, 2), 3, 5, 7, 12.0) for i in range(50)
            ),
        )

        assert _count_overlaps(_rendered_rows(monkeypatch, report)) == 0

    def test_a_log_that_fits_is_fully_legible(self, monkeypatch):
        # The realistic case: SPT at 1 m centres in a 15 m hole. Every label
        # clears its neighbour and nothing is moved at all.
        report = ReportData(
            header=ReportHeader(
                project_type="ROAD",
                project_location="X",
                client_name="C",
                borehole_number="L1",
                termination_depth=15.0,
            ),
            layers=tuple(
                Layer(i * 3.0, (i + 1) * 3.0, f"Stratum {i}") for i in range(5)
            ),
            spt=tuple(SptTest(float(i), 3, 5, 7, 12.0) for i in range(1, 15)),
        )

        rows = _rendered_rows(monkeypatch, report)

        assert _count_overlaps(rows) == 0

        # And every SPT row sits at exactly the depth it was plotted at.
        from app.borelog_report.layout import MAX_DEPTH_PER_PAGE, depth_to_y

        for index in range(1, 15):
            text = f"{index:.2f} – {index + SPT_PENETRATION:.2f}"
            placed = [row["y"] for row in rows if row["text"] == text]
            assert len(placed) == 1, f"{text} was not drawn exactly once"
            expected = depth_to_y(
                index + SPT_PENETRATION, MAX_DEPTH_PER_PAGE
            ) + 0.01
            assert placed[0] == pytest.approx(expected, abs=1e-6), (
                f"{text} was moved off its true depth"
            )

    def test_thin_strata_do_not_overprint_their_depth_labels(self, monkeypatch):
        report = ReportData(
            header=ReportHeader(
                project_type="ROAD", project_location="X", termination_depth=1.2
            ),
            layers=tuple(
                Layer(round(i * 0.15, 2), round((i + 1) * 0.15, 2), f"Stratum {i}")
                for i in range(8)
            ),
        )

        rows = _rendered_rows(monkeypatch, report)
        # Both numeric columns: the stratum base and the thickness.
        labels = [row for row in rows if _is_numeric(row["text"])]

        assert len(labels) == 16, "expected a depth and a thickness per stratum"

        # Only the numbers are asserted. A 0.15 m band is 0.16 cm on the page
        # and 6 pt text is 0.21 cm tall, so a description cannot fit however it
        # is placed; v6 clips it with an ellipsis rather than nudging, and that
        # is left alone. The numbers are what this guard is for.
        assert _count_overlaps(labels) == 0

    def test_a_well_spaced_log_is_unmoved(self, monkeypatch):
        # The guard must not move anything when nothing collides: an everyday
        # log has to stay exactly where v6 put it.
        report = ReportData(
            header=ReportHeader(
                project_type="ROAD",
                project_location="Kilometre 12",
                client_name="Highways Dept",
                borehole_number="L1",
                water_table=4.5,
                termination_depth=18.0,
            ),
            layers=(
                Layer(0.0, 1.5, "Made Ground"),
                Layer(1.5, 6.0, "Sandy SILT"),
                Layer(6.0, 10.0, "Dense SAND"),
                Layer(10.0, 18.0, "Stiff CLAY"),
            ),
            spt=(
                SptTest(2.0, 2, 3, 4, 9.0),
                SptTest(4.0, 4, 6, 8, 18.0),
                SptTest(7.5, 10, 15, 20, 45.0),
                SptTest(11.0, 20, 25, 30, 50.0),
            ),
        )

        drawn = drawn_text(monkeypatch, report)

        assert "2.00 – 2.45" in drawn
        assert _count_overlaps(_rendered_rows(monkeypatch, report)) == 0

    def test_the_everyday_log_keeps_v6_positions_exactly(self, monkeypatch):
        # Not just collision-free: at its true depths, byte for byte what v6
        # would have drawn. Regression guard on the guard.
        from app.borelog_report.layout import (
            MAX_DEPTH_PER_PAGE,
            depth_to_y,
        )

        report = ReportData(
            header=ReportHeader(termination_depth=18.0),
            layers=(Layer(0.0, 1.5, "Made Ground"), Layer(1.5, 6.0, "Sandy SILT")),
            spt=(SptTest(2.0, 2, 3, 4, 9.0), SptTest(4.0, 4, 6, 8, 18.0)),
        )

        rows = _rendered_rows(monkeypatch, report)

        # A test at 2.00 m is plotted at 2.45 m, and must be drawn exactly there.
        expected = depth_to_y(2.0 + SPT_PENETRATION, MAX_DEPTH_PER_PAGE) + 0.01
        placed = [r["y"] for r in rows if r["text"] == "2.00 – 2.45"]

        assert len(placed) == 1
        assert placed[0] == pytest.approx(expected, abs=0.01)


class TestRendererOutput:
    def test_renders_a_real_pdf(self):
        from app.borelog_report.pdf_renderer import render_borelog_pdf

        pdf = render_borelog_pdf(_sample_report())

        assert pdf.startswith(PDF_MAGIC)
        assert pdf.rstrip().endswith(b"%%EOF")

    def test_renders_every_page_of_a_deep_log(self):
        from app.borelog_report.pdf_renderer import render_borelog_pdf

        pdf = render_borelog_pdf(_sample_report())

        pages = pdf.count(PDF_PAGE_MARKER) - pdf.count(b"/Type /Pages")
        assert pages == 3

    def test_draws_the_report_content(self, monkeypatch):
        text = drawn_text(monkeypatch, _sample_report())

        for expected in (
            "GEOTECHNICAL INVESTIGATION FOR THE PROPOSED",
            "ROAD RESURFACING AT Kilometre 12",
            "Client: Highways Dept",
            "Borehole No: L1",
            "Termination Depth: 41.50 m",
            "Ground Water Table: 4.50 m",
            "Made Ground",
            "Dense SAND",
            "Fresh GRANITE",
            "Water Table at 4.50 m",
            "THE BOREHOLE WAS TERMINATED AT 41.50 m DEPTH",
            "CORE RECOVERY = 92%",
            "RQD = 70%",
        ):
            assert expected in text, expected

    def test_renders_nothing_without_data(self):
        from app.borelog_report.pdf_renderer import render_borelog_pdf

        with pytest.raises(ValueError):
            render_borelog_pdf(ReportData())

    def test_survives_a_missing_logo(self):
        # The v6 script wrapped its logo read in try/except and carried on; a
        # deployment with no logo file still gets a report.
        from app.borelog_report.pdf_renderer import render_borelog_pdf

        pdf = render_borelog_pdf(_sample_report(), logo_bytes=None)

        assert pdf.startswith(PDF_MAGIC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_report() -> ReportData:
    return ReportData(
        header=ReportHeader(
            project_type="ROAD RESURFACING",
            project_location="Kilometre 12",
            client_name="Highways Dept",
            borehole_number="L1",
            boring_type="Rotary",
            drilling_start="01.02.2026",
            drilling_completion="03.02.2026",
            water_table=4.5,
            termination_depth=41.5,
        ),
        layers=(
            Layer(0.0, 1.5, "Made Ground"),
            Layer(1.5, 6.0, "Sandy SILT"),
            Layer(6.0, 10.0, "Dense SAND"),
            Layer(10.0, 18.0, "Stiff CLAY"),
            Layer(
                18.0,
                26.0,
                "Weathered GRANITE",
                is_rock=True,
                recovery=92.0,
                rqd=70.0,
                remark="Core run 4",
            ),
            Layer(
                26.0,
                41.5,
                "Fresh GRANITE",
                is_rock=True,
                recovery=100.0,
                rqd=85.0,
            ),
        ),
        spt=(
            SptTest(2.0, 2, 3, 4, 9.0),
            SptTest(4.0, 4, 6, 8, 18.0),
            SptTest(7.5, 10, 15, 20, 45.0),
            SptTest(11.0, 20, 25, 30, 50.0),
            SptTest(12.5, 25, 25, 25, 55.0),
        ),
    )


def _record_draws(monkeypatch) -> list[str]:
    """Start recording every string matplotlib is asked to draw.

    matplotlib embeds a subset font per document with no ToUnicode map, so text
    written into the PDF cannot be read back out of the bytes. Recording the
    draw calls is both readable and stricter: it asserts the strings were
    placed on the page, not merely that glyphs were emitted.

    Returns the live list, so a caller can record around whichever render it is
    about to make -- through a route, or by calling the renderer directly.
    """
    from matplotlib.axes import Axes

    written: list[str] = []
    original = Axes.text

    def recording_text(self, x, y, text, *args, **kwargs):
        written.append(str(text))
        return original(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Axes, "text", recording_text)
    return written


def drawn_text(monkeypatch, report) -> str:
    """Every string one direct render placed on the page."""
    written = _record_draws(monkeypatch)

    from app.borelog_report.pdf_renderer import render_borelog_pdf

    render_borelog_pdf(report)
    return "\n".join(written)


def _rendered_rows(monkeypatch, report) -> list[dict]:
    """Every text label the renderer placed, with its real glyph box on its page.

    Captured from the artist each `Axes.text` call returns, then measured with
    matplotlib's own renderer, so the boxes are the ones that would be printed.
    A label that collision avoidance moved is therefore reported where it
    actually landed rather than where its depth would have put it.

    One page only. The renderer builds a figure per PDF page and closes it
    before starting the next, and matplotlib then hands the same figure *number*
    to the replacement -- so page 2 and 3 content would be filed under page 1's
    number and compared against it, reporting every repeated header and column
    label as overlapping itself. Collision avoidance is per page by definition,
    so the logs under test here are all shallow enough to fit one sheet.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.axes import Axes

    from app.borelog_report.layout import MAX_DEPTH_PER_PAGE
    from app.borelog_report.pdf_renderer import render_borelog_pdf

    assert report.page_count == 1, (
        "this helper measures a single page; give it a shallower log"
    )

    artists: list[tuple[str, object, float, float]] = []
    original = Axes.text

    def recording_text(self, x, y, text, *args, **kwargs):
        artist = original(self, x, y, text, *args, **kwargs)
        artists.append((str(text), artist, float(x), float(y)))
        return artist

    monkeypatch.setattr(Axes, "text", recording_text)
    try:
        render_borelog_pdf(report)

        figure = plt.gcf()
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()

        rows = [
            {
                "text": text,
                # The data-space position the renderer chose -- what a test
                # comparing against a computed depth needs.
                "y": y,
                "x": x,
                # The box as printed, for overlap measurement.
                "box": artist.get_window_extent(renderer=renderer),
            }
            for text, artist, x, y in artists
        ]
    finally:
        monkeypatch.undo()
        plt.close("all")

    return rows


def _is_numeric(text: str) -> bool:
    """A depth or a thickness: digits and at most one decimal point."""
    stripped = text.strip()
    return stripped.count(".") <= 1 and stripped.replace(".", "", 1).isdigit()


#: Labels of the page furniture, not log content. The title and the header block
#: are placed by hand at fixed positions in v6 and never participate in
#: collision avoidance, so they are excluded rather than fixed.
_PAGE_FURNITURE = (
    "GEOTECHNICAL INVESTIGATION",
    "Client:",
    "Borehole No:",
    "Type of Boring:",
    "Termination Depth:",
    "Boring Start Date:",
    "Completion Date:",
    "Ground Water Table:",
    "Location:",
    "Soil Profile",
    "Description",
    "Thickness",
    "SPT",
    "15cm",
    "30cm",
    "45cm",
    "Depth",
)


def _is_log_content(text: str) -> bool:
    return bool(text.strip()) and not text.startswith(_PAGE_FURNITURE)


def _count_overlaps(rows: list[dict]) -> int:
    """Pairs of log labels whose glyph boxes cover the same pixels.

    Measured on the rendered page rather than inferred from the coordinates, so
    it catches a label that is clear of its neighbour by eye but still clips it,
    and it counts every collision -- including the ones the guard cannot fix,
    such as a description longer than the band it sits in -- so a regression
    anywhere shows up rather than being hidden by a per-column filter.
    """
    content = [row for row in rows if _is_log_content(row["text"])]

    overlaps = 0
    for index, first in enumerate(content):
        for second in content[index + 1 :]:
            a, b = first["box"], second["box"]
            if min(a.x1, b.x1) - max(a.x0, b.x0) > 0.5 and min(
                a.y1, b.y1
            ) - max(a.y0, b.y0) > 0.5:
                overlaps += 1
    return overlaps


# ---------------------------------------------------------------------------
# The v6 rock appendix -- the table that closes a report with core logging
# ---------------------------------------------------------------------------


def _pdf_pages(content: bytes):
    import io

    from pypdf import PdfReader

    return PdfReader(io.BytesIO(content)).pages


def _pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in _pdf_pages(content))


def _appendix_data(*rock_layers):
    return ReportData(
        header=ReportHeader(borehole_number="L1", termination_depth=26.0),
        layers=(Layer(0.0, 20.0, "SAND"), *rock_layers),
    )


class TestRockAppendixTable:
    def test_runs_with_nothing_but_depths_are_not_printed(self):
        """v6's `useful` filter: a CORE row that carries only depths is a
        workflow artefact, not a log entry."""
        from app.borelog_report.rock_appendix import rock_logging_rows

        data = _appendix_data(
            Layer(20.0, 21.0, "", is_rock=True),
            Layer(21.0, 22.0, "", is_rock=True, remark="weathered"),
            Layer(22.0, 23.0, "", is_rock=True, recovery=88.0),
            Layer(23.0, 26.0, "GRANITE", is_rock=True),
        )

        assert [layer.depth_from for layer in rock_logging_rows(data)] == [
            21.0,
            22.0,
            23.0,
        ]

    def test_no_rock_means_no_appendix(self):
        from app.borelog_report.rock_appendix import render_rock_appendix_pdf

        assert render_rock_appendix_pdf(_appendix_data()) is None

    def test_appendix_is_the_v6_table(self):
        from app.borelog_report.rock_appendix import render_rock_appendix_pdf

        appendix = render_rock_appendix_pdf(
            _appendix_data(
                Layer(
                    20.0,
                    26.0,
                    "Weathered LIMESTONE",
                    is_rock=True,
                    recovery=88.0,
                    rqd=61.0,
                    remark="Run 3",
                )
            )
        )

        assert appendix.startswith(PDF_MAGIC)
        text = " ".join(_pdf_text(appendix).split())
        assert "ROCK LOGGING (CORE RECOVERY & RQD)" in text
        assert "Appendix Page 1 of 1" in text
        assert "20.00 – 26.00" in text
        assert "Weathered LIMESTONE" in text
        assert "CORE RECOVERY = 88%" in text
        assert "RQD = 61%" in text
        assert "Run 3" in text

    def test_missing_recovery_prints_nil(self):
        from app.borelog_report.rock_appendix import render_rock_appendix_pdf

        appendix = render_rock_appendix_pdf(
            _appendix_data(Layer(20.0, 26.0, "", is_rock=True, remark="RC"))
        )

        text = " ".join(_pdf_text(appendix).split())
        assert "CORE RECOVERY = NIL" in text
        assert "RQD = NIL" in text

    def test_long_tables_paginate(self):
        from app.borelog_report.rock_appendix import render_rock_appendix_pdf

        data = _appendix_data(
            *(
                Layer(float(i), float(i) + 1.0, f"Run {i}", is_rock=True, recovery=90.0)
                for i in range(25)
            )
        )

        appendix = render_rock_appendix_pdf(data)

        pages = _pdf_pages(appendix)
        assert len(pages) == 2
        assert "Appendix Page 1 of 2" in " ".join(pages[0].extract_text().split())
        assert "Appendix Page 2 of 2" in " ".join(pages[1].extract_text().split())


class TestRockAppendixIsJoinedToThePdf:
    def test_appendix_pages_follow_the_log(self, client, pool):
        _seed(
            pool,
            geol=_geol((0.0, 20.0, "SAND")),
            rock=_rock((20.0, 26.0, 88.0, 61.0, "Run 3", "Weathered LIMESTONE")),
            loca=_loca(final_depth=Decimal("26.0")),
        )

        pdf = _pdf(client, pool)

        # 26 m of hole is two log pages; the appendix adds its own.
        pages = _pdf_pages(pdf.content)
        assert len(pages) == 3
        assert "ROCK LOGGING" not in " ".join(
            (page.extract_text() or "") for page in pages[:2]
        )
        assert "ROCK LOGGING (CORE RECOVERY & RQD)" in " ".join(
            pages[-1].extract_text().split()
        )

    def test_no_rock_no_appendix_page(self, client, pool):
        _seed(
            pool,
            geol=_geol((0.0, 20.0, "SAND")),
            loca=_loca(final_depth=Decimal("20.0")),
        )

        pdf = _pdf(client, pool)

        assert len(_pdf_pages(pdf.content)) == 1
        assert "ROCK LOGGING" not in _pdf_text(pdf.content)

    def test_the_memo_keeps_the_joined_document(self, client, pool):
        _seed(
            pool,
            geol=_geol((0.0, 20.0, "SAND")),
            rock=_rock((20.0, 26.0, 88.0, 61.0, "Run 3", "Weathered LIMESTONE")),
            loca=_loca(final_depth=Decimal("26.0")),
        )

        first = _pdf(client, pool)
        second = _pdf(client, pool)

        assert first.content == second.content
        assert len(_pdf_pages(second.content)) == 3


# ---------------------------------------------------------------------------
# The v6 soil-profile narrative and its .docx
# ---------------------------------------------------------------------------


def _narrative_data(**overrides):
    defaults = dict(
        header=ReportHeader(
            borehole_number="L1",
            water_table=3.2,
            termination_depth=26.0,
        ),
        layers=(
            Layer(0.0, 8.0, "Made Ground"),
            Layer(8.0, 20.0, "Stiff CLAY"),
            Layer(
                20.0,
                26.0,
                "Weathered LIMESTONE",
                is_rock=True,
                recovery=88.0,
                rqd=61.0,
            ),
        ),
        spt=(SptTest(1.5, n_value=9.0), SptTest(6.0, n_value=22.0)),
    )
    defaults.update(overrides)
    return ReportData(**defaults)


class TestSptSummaryForInterval:
    def test_no_tests_at_all(self):
        from app.borelog_report.profile_docx import spt_summary_for_interval

        assert (
            spt_summary_for_interval(0.0, 8.0, ())
            == "with no SPT conducted within this interval"
        )

    def test_tests_elsewhere_are_not_in_the_interval(self):
        from app.borelog_report.profile_docx import spt_summary_for_interval

        assert (
            spt_summary_for_interval(8.0, 20.0, (SptTest(1.5, n_value=9.0),))
            == "with no SPT recorded within this interval"
        )

    def test_a_test_belongs_to_where_its_drive_ends(self):
        # A test at 7.8 m is plotted at 8.25, so it reads in the 8-20 stratum.
        from app.borelog_report.profile_docx import spt_summary_for_interval

        assert (
            spt_summary_for_interval(8.0, 20.0, (SptTest(7.8, n_value=12.0),))
            == "with SPT N value 12"
        )

    def test_single_value_and_range(self):
        from app.borelog_report.profile_docx import spt_summary_for_interval

        assert (
            spt_summary_for_interval(0.0, 20.0, (SptTest(1.5, n_value=12.0),))
            == "with SPT N value 12"
        )
        assert (
            spt_summary_for_interval(
                0.0, 20.0, (SptTest(1.5, n_value=9.0), SptTest(6.0, n_value=22.0))
            )
            == "with SPT N value ranging from 9 to 22"
        )

    def test_worded_tests_outrank_numbers(self):
        from app.borelog_report.profile_docx import spt_summary_for_interval

        assert (
            spt_summary_for_interval(0.0, 20.0, (SptTest(1.0, n_value="rb"),))
            == "with SPT rebound recorded"
        )
        assert (
            spt_summary_for_interval(0.0, 20.0, (SptTest(1.0, n_value="hard rock"),))
            == "with hard rock (SPT not representative)"
        )
        assert (
            spt_summary_for_interval(0.0, 20.0, (SptTest(1.0, n_value="soft rock"),))
            == "with soft rock (SPT not representative)"
        )
        # A rebound anywhere in the stratum wins over the values beside it.
        assert (
            spt_summary_for_interval(
                0.0, 20.0, (SptTest(1.0, n_value=12.0), SptTest(2.0, n_value="rb"))
            )
            == "with SPT rebound recorded"
        )

    def test_bare_over_fifty_text(self):
        from app.borelog_report.profile_docx import spt_summary_for_interval

        assert (
            spt_summary_for_interval(0.0, 20.0, (SptTest(1.0, n_value=">50"),))
            == "with SPT N value 51"
        )


class TestComposeNarrative:
    def test_v6_prose_verbatim(self):
        from app.borelog_report.profile_docx import compose_narrative

        borehole, paragraph = compose_narrative(_narrative_data())

        assert borehole == "L1"
        assert paragraph == (
            "In L1, Made Ground extends from 0.00 m to 8.00 m, "
            "with SPT N value ranging from 9 to 22. "
            "Beneath this, Stiff CLAY extends from 8.00 m to 20.00 m, "
            "with no SPT recorded within this interval. "
            "This was followed by Weathered LIMESTONE extends from 20.00 m "
            "to 26.00 m, with core recovery of 88% and RQD of 61%. "
            "The borehole was terminated at 26.00 m in Weathered LIMESTONE. "
            "Groundwater was encountered at 3.20 m bgl during drilling."
        )

    def test_transitions_rotate(self):
        from app.borelog_report.profile_docx import compose_narrative

        data = _narrative_data(
            layers=tuple(
                Layer(float(i), float(i) + 1.0, f"L{i}") for i in range(7)
            ),
            spt=(),
        )

        _, paragraph = compose_narrative(data)

        for phrase in (
            "Beneath this,",
            "This was followed by",
            "Below this,",
            "Further below,",
            "Subsequently,",
        ):
            assert phrase in paragraph
        # The sixth stratum wraps back to the first phrase.
        assert paragraph.count("Beneath this,") == 2

    def test_blank_soil_is_skipped_but_blank_rock_is_not(self):
        from app.borelog_report.profile_docx import compose_narrative

        data = _narrative_data(
            layers=(
                Layer(0.0, 5.0, ""),
                Layer(5.0, 8.0, "GRANITE", is_rock=True, recovery=90.0, rqd=80.0),
            ),
            spt=(),
        )

        _, paragraph = compose_narrative(data)

        assert "In L1, GRANITE extends" in paragraph
        assert "with core recovery of 90% and RQD of 80%" in paragraph

    def test_no_water_is_reported_as_such(self):
        from app.borelog_report.profile_docx import compose_narrative

        data = _narrative_data(header=ReportHeader(borehole_number="L1"))

        _, paragraph = compose_narrative(data)

        assert "Groundwater was not encountered during drilling." in paragraph

    def test_termination_falls_back_to_the_last_stratum(self):
        from app.borelog_report.profile_docx import compose_narrative

        data = _narrative_data(
            header=ReportHeader(borehole_number="L1", water_table=None)
        )

        _, paragraph = compose_narrative(data)

        assert (
            "The borehole was terminated at 26.00 m in Weathered LIMESTONE."
            in paragraph
        )

    def test_missing_borehole_number_prints_bh(self):
        from app.borelog_report.profile_docx import compose_narrative

        data = _narrative_data(header=ReportHeader(termination_depth=26.0))

        borehole, paragraph = compose_narrative(data)

        assert borehole == "BH"
        assert paragraph.startswith("In BH, ")


class TestProfileDocxEndpoint:
    def _docx(self, client, pool):
        response = client.get(f"{BASE}/docx", headers=auth_header())
        assert response.status_code == 200, response.text
        return response

    def test_document_matches_the_narrative(self, client, pool):
        import io

        from docx import Document

        _seed(
            pool,
            geol=_geol((0.0, 8.0, "Made Ground"), (8.0, 20.0, "Stiff CLAY")),
            spt=_spt((1.5, 2, 3, 4, 9.0), (6.0, 6, 8, 10, 22.0)),
            rock=_rock((20.0, 26.0, 88.0, 61.0, "Run 3", "Weathered LIMESTONE")),
            loca=_loca(final_depth=Decimal("26.0"), water=Decimal("3.2")),
        )

        response = self._docx(client, pool)

        assert response.content.startswith(b"PK")
        assert (
            response.headers["content-type"]
            == "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
        assert response.headers["cache-control"] == "private, no-store"
        assert "_soil_profile.docx" in response.headers["content-disposition"]

        document = Document(io.BytesIO(response.content))
        texts = [paragraph.text for paragraph in document.paragraphs]

        assert texts[0] == "Soil Profile Description \u2014 L1"
        assert texts[1] == (
            "In L1, Made Ground extends from 0.00 m to 8.00 m, "
            "with SPT N value ranging from 9 to 22. "
            "Beneath this, Stiff CLAY extends from 8.00 m to 20.00 m, "
            "with no SPT recorded within this interval. "
            "This was followed by Weathered LIMESTONE extends from 20.00 m "
            "to 26.00 m, with core recovery of 88% and RQD of 61%. "
            "The borehole was terminated at 26.00 m in Weathered LIMESTONE. "
            "Groundwater was encountered at 3.20 m bgl during drilling."
        )
        assert texts[3] == "L1 \u2014 Stratigraphic Summary"
        assert texts[4] == (
            "01. 0.00\u20138.00 m: Made Ground, "
            "with SPT N value ranging from 9 to 22"
        )
        assert texts[5] == (
            "02. 8.00\u201320.00 m: Stiff CLAY, "
            "with no SPT recorded within this interval"
        )
        assert texts[6] == (
            "03. 20.00\u201326.00 m: Weathered LIMESTONE, "
            "with no SPT recorded within this interval"
        )

    def test_no_data_is_a_404_not_an_empty_document(self, client, pool):
        _seed(pool, geol=(), spt=(), rock=(), loca=_loca(final_depth=None))

        response = client.get(f"{BASE}/docx", headers=auth_header())

        assert response.status_code == 404
        assert "borelog" in response.json()["detail"].lower()

    def test_location_from_another_project_is_404(self, client, pool):
        route_users_by_id(pool, {1: make_user_row(id=1)})
        # No LOCA row routed: the location does not exist in P1.
        pool.route('"tdac"."ROCK_RECORD"', [])
        pool.route('"ags42"."GEOL"', [])
        pool.route('"ags42"."ISPT"', [])
        pool.route('"ags42"."PROJ"', _project())

        response = client.get(
            "/api/portfolio/projects/P1/locas/OTHER/borelog-report/docx",
            headers=auth_header(),
        )

        assert response.status_code == 404
