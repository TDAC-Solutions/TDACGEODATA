"""Borelog report for Field Data -> Overview.

Ported from `Borelog_Report_with_Profile_and_RockIntegrated_v6.py`, which stays
exactly as it is. What moved here is its *layout*: the 19 cm column strip, the
page geometry, the 20 m page split, the 45 cm SPT drive, the hatch rotation and
the water-table and termination markers, now driven by the project's own
database instead of an input workbook.

    layout.py        the report's contract: columns, page geometry, the
                     depth-ordered row list, and every derived value. Plain
                     data and pure functions -- no HTTP, no database, no
                     matplotlib.
    data_source.py   Postgres reads, shaped into layout's types.
    pdf_renderer.py  layout's types -> PDF bytes, 20 m a page.
    rock_appendix.py the v6 ROCK LOGGING (CORE RECOVERY & RQD) table,
                     appended behind the log's own pages.
    profile_docx.py  the v6 soil-profile narrative and numbered summary,
                     as a Word document.
    router.py        the JSON preview, the PDF and the DOCX.

The preview and the PDF are two renderings of one `build_log_rows()` result,
so a value cannot differ between the screen and the paper.
"""

from app.borelog_report.data_source import ReportDataNotFound, fetch_report_data
from app.borelog_report.layout import (
    COLUMNS,
    MAX_DEPTH_PER_PAGE,
    SPT_PENETRATION,
    Layer,
    LogRow,
    ReportData,
    ReportHeader,
    SptTest,
    build_log_rows,
    report_to_json,
)

__all__ = [
    "COLUMNS",
    "MAX_DEPTH_PER_PAGE",
    "SPT_PENETRATION",
    "Layer",
    "LogRow",
    "ReportData",
    "ReportDataNotFound",
    "ReportHeader",
    "SptTest",
    "build_log_rows",
    "fetch_report_data",
    "report_to_json",
]