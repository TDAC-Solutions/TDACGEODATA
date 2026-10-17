"""The v6 rock appendix, appended to the log PDF as extra pages.

`Borelog_Report_with_Profile_and_RockIntegrated_v6.py` closed a report with a
standalone "ROCK LOGGING (CORE RECOVERY & RQD)" table whenever the rock profile
sheet carried any usable run (`_make_rock_appendix_pdf`). The port keeps the
table verbatim -- column widths, the 24-rows-a-page split, the CORE RECOVERY /
RQD cell, the page badge -- but returns bytes, and `pypdf` joins them behind the
pages matplotlib drew so one download is still one document.

What counts as "usable" is v6's rule: a run prints when it has any description,
remark, recovery or RQD at all. A CORE row that carries only depths is a
workflow artefact, not information, and is skipped rather than printed blank.

Both reportlab and pypdf are imported inside the functions, and the module
itself is imported by the router only on a PDF request, for the same reason
`pdf_renderer` is: the JSON preview must not pay for the renderer stack.
"""

from __future__ import annotations

import io
import math
from typing import Optional

from app.borelog_report.layout import ReportData, Layer, fmt_2dp, format_pct

#: v6's table title and page badge.
APPENDIX_TITLE = "ROCK LOGGING (CORE RECOVERY & RQD)"


def rock_logging_rows(data: ReportData) -> list[Layer]:
    """The rock runs worth printing, in depth order (the order `layers` is
    already in). A run with nothing but depths is not a log entry."""
    rows = []
    for layer in data.layers:
        if not layer.is_rock:
            continue
        if (
            layer.description.strip()
            or layer.remark.strip()
            or layer.recovery is not None
            or layer.rqd is not None
        ):
            rows.append(layer)
    return rows


def render_rock_appendix_pdf(data: ReportData) -> Optional[bytes]:
    """The appendix as a PDF, or None when there is no rock to print.

    One table row per run: "From – To", the description, the recovery and RQD
    pair, the remark. Pagination is v6's: a 10 mm row on the A4 sheet, at
    least 12 rows to a page, the header repeated on each.

    None rather than an empty PDF, so the caller can hand back the main log
    unchanged instead of a stray blank page.
    """
    rows = rock_logging_rows(data)
    if not rows:
        return None

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table, TableStyle

    width, height = A4
    margin_l = margin_r = 12 * mm
    margin_t = margin_b = 15 * mm

    col_widths = [
        30 * mm,
        75 * mm,
        40 * mm,
        (width - margin_l - margin_r) - (30 + 75 + 40) * mm,
    ]
    header = ["Depth (m)", "Rock Description", "Recovery & RQD", "Remark"]

    table_rows = []
    for layer in rows:
        table_rows.append(
            [
                f"{fmt_2dp(layer.depth_from)} \u2013 {fmt_2dp(layer.depth_to)}",
                layer.description.strip(),
                f"CORE RECOVERY = {format_pct(layer.recovery)}\n"
                f"RQD = {format_pct(layer.rqd)}",
                layer.remark.strip(),
            ]
        )

    usable_h = height - margin_t - margin_b - 20 * mm
    row_h = 10 * mm
    rows_per_page = max(12, int(usable_h // row_h))
    pages = max(1, math.ceil(len(table_rows) / rows_per_page))

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    for page in range(pages):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin_l, height - margin_t, APPENDIX_TITLE)
        c.setFont("Helvetica", 9)
        c.drawRightString(
            width - margin_r, height - margin_t, f"Appendix Page {page + 1} of {pages}"
        )

        start = page * rows_per_page
        end = min((page + 1) * rows_per_page, len(table_rows))
        data_rows = [header] + table_rows[start:end]

        table = Table(data_rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("ALIGN", (0, 0), (0, -1), "CENTER"),
                    ("ALIGN", (2, 1), (2, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )

        _, table_h = table.wrapOn(c, width - margin_l - margin_r, usable_h)
        table.drawOn(c, margin_l, height - margin_t - 10 * mm - table_h)

        c.showPage()

    c.save()
    return buffer.getvalue()


def append_pdf_pages(main_pdf: bytes, appendix_pdf: bytes) -> bytes:
    """`main_pdf` with every page of `appendix_pdf` appended behind it."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(main_pdf)).pages:
        writer.add_page(page)
    for page in PdfReader(io.BytesIO(appendix_pdf)).pages:
        writer.add_page(page)

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def render_with_appendix(main_pdf: bytes, data: ReportData) -> bytes:
    """The download the router serves: the log, plus the rock appendix when
    the hole has core runs to print."""
    appendix = render_rock_appendix_pdf(data)
    if appendix is None:
        return main_pdf
    return append_pdf_pages(main_pdf, appendix)
