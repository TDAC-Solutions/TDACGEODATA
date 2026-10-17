"""The borelog report's layout contract, shared by the screen and the paper.

`Borelog_Report_with_Profile_and_RockIntegrated_v6.py` drew a depth-proportioned
geotechnical log with matplotlib and read its data from an Excel workbook. That
script is left exactly as it is. What lived in it as *content* -- the column
set, the page geometry, the 20 m page split, the 45 cm SPT drive, the hatch
rotation, the water-table and termination markers -- lives here instead, as
plain data and pure functions with no HTTP, no database and no matplotlib
import. The v6 drawing routine is in `pdf_renderer.py` and reads its geometry
from the constants in this module.

Two consumers, one definition:

    preview (JSON)  ->  build_log_rows()  ->  one continuous table
    paper  (PDF)    ->  render_borelog_pdf()  ->  one row per 20 m

Because both are driven by `COLUMNS` and `build_log_rows`, the preview and the
PDF cannot drift: there is no second place where a column, a header or a
derived value (thickness, test depth, the >50 rule) is written down.

Deliberately pandas-free. The v6 script only used pandas to read the workbook;
feeding plain dataclasses removes the dependency, removes the per-cell dtype
conversions, and makes the module usable from any caller that can build a list
of `Layer` and `SptTest` objects.
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional

# ---------------------------------------------------------------------------
# Page geometry. Values are the v6 script's, verbatim, in centimetres.
# ---------------------------------------------------------------------------

PAGE_WIDTH_CM = 21
PAGE_HEIGHT_CM = 29.7
MARGIN_CM = 1
TITLE_HEIGHT_CM = 2
HEADER_HEIGHT_CM = 2
COL_HEADER_HEIGHT_CM = 1.8
PLOT_HEIGHT_CM = PAGE_HEIGHT_CM - (
    2 * MARGIN_CM + TITLE_HEIGHT_CM + HEADER_HEIGHT_CM + COL_HEADER_HEIGHT_CM
)

#: Depth covered by one PDF page. The report splits here and only here; the
#: on-screen preview deliberately does not split at all.
MAX_DEPTH_PER_PAGE = 20

#: Standard SPT drive, 45 cm. An N-value is recorded at the *base* of the
#: drive, which is why a test at 1.50 m is drawn at 1.95 m.
SPT_PENETRATION = 0.45

#: Width of the "SPT Plot" column, the strip the N-value dots sit in.
SPT_PLOT_WIDTH_CM = 4

#: The N-value axis runs 0..PLOT_MAX_N across the plot column, and the scale
#: saturates at PLOT_SATURATE_N -- so the " >50 " case still draws inside the
#: column instead of running off the page.
PLOT_MAX_N = 60
PLOT_SATURATE_N = 40

#: v6 rotated the hatch pattern through this list, one entry per layer.
HATCH_PATTERNS = ("/", "\\", "x", "-", "+", ".", "*", "o", "O")

#: The N-values the v6 script carried as words rather than numbers.
QUALITATIVE_SPT_LABELS = ("rb", "rebound", "soft rock", "hard rock")


# ---------------------------------------------------------------------------
# Columns. One definition; the PDF lays them out at `width_cm`, and the web
# table turns the same widths into flex proportions, so the two agree by
# construction rather than by convention.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportColumn:
    id: str
    #: Printed verbatim, one list entry per printed line.
    label_lines: tuple[str, ...]
    width_cm: float
    #: v6 printed the Depth / Soil Profile / Thickness headers turned on their
    #: side; the web table stacks the word instead, which reads better at
    #: screen widths and costs no information.
    rotated: bool = False

    @property
    def label(self) -> str:
        return " ".join(self.label_lines)

    @property
    def percent_of_plot(self) -> float:
        """Width as a percentage of the printable area (19 cm)."""
        return (self.width_cm / PLOT_WIDTH_CM) * 100.0


#: Printable width: page width less both margins. The column widths below add
#: up to exactly this, which is what lets the log fill the page edge to edge.
PLOT_WIDTH_CM = PAGE_WIDTH_CM - 2 * MARGIN_CM

COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("depth", ("Depth",), 1, rotated=True),
    ReportColumn("profile", ("Soil", "Profile"), 1, rotated=True),
    ReportColumn("description", ("Description",), 6),
    ReportColumn("thickness", ("Thickness",), 1, rotated=True),
    ReportColumn("spt_depth", ("SPT Depth",), 2),
    ReportColumn("blows_15", ("15cm",), 1),
    ReportColumn("blows_30", ("30cm",), 1),
    ReportColumn("blows_45", ("45cm",), 1),
    ReportColumn("n_value", ("SPT", "N-Value"), 1),
    ReportColumn("spt_plot", ("SPT Plot",), SPT_PLOT_WIDTH_CM),
)

COLUMN_IDS: tuple[str, ...] = tuple(column.id for column in COLUMNS)

BY_ID: dict[str, ReportColumn] = {column.id: column for column in COLUMNS}


# ---------------------------------------------------------------------------
# Report content. Dataclasses, not DataFrames: cheaper to build, cheaper to
# serialise, and impossible to mutate by accident mid-render.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layer:
    """One geology interval. Soil rows come from ags42.GEOL, rock rows from
    the Rock workflow (CORE joined back to its GEOL interval)."""

    depth_from: float
    depth_to: float
    description: str = ""
    is_rock: bool = False
    recovery: Optional[float] = None
    rqd: Optional[float] = None
    remark: str = ""

    @property
    def thickness(self) -> float:
        return self.depth_to - self.depth_from


@dataclass(frozen=True)
class SptTest:
    """One SPT test. `n_value` is a float; the qualitative v6 labels (RB, soft
    rock, hard rock) are accepted as text for callers that still carry them."""

    depth: float
    blows_15: Optional[float] = None
    blows_30: Optional[float] = None
    blows_45: Optional[float] = None
    n_value: Any = None

    # -- derived, exactly as v6 computed them ------------------------------

    @property
    def label(self) -> str:
        return str(self.n_value).strip().lower()

    @property
    def is_qualitative(self) -> bool:
        """A worded test occupies the row at its start depth; a driven test is
        recorded at the base of the 45 cm drive."""
        return self.label in QUALITATIVE_SPT_LABELS

    @property
    def test_depth(self) -> float:
        return self.depth if self.is_qualitative else self.depth + SPT_PENETRATION

    @property
    def depth_text(self) -> str:
        if self.is_qualitative:
            return fmt_2dp(self.depth)
        return f"{fmt_2dp(self.depth)} \u2013 {fmt_2dp(self.depth + SPT_PENETRATION)}"

    @property
    def numeric_n(self) -> Optional[float]:
        try:
            return float(self.n_value)
        except (TypeError, ValueError):
            return None

    @property
    def n_text(self) -> str:
        """What the N-value cell prints."""
        if self.label == "rb":
            return "SPT Rebound"
        if self.label == "hard rock":
            return "Hard Rock"
        if self.label == "soft rock":
            return "Soft Rock"

        value = self.numeric_n
        if value is None:
            return str(self.n_value)
        return ">50" if value > 50 else f"{value:.0f}"

    @property
    def n_plot_text(self) -> str:
        """The annotation beside the dot in the SPT Plot column."""
        if self.label == "rb":
            return "RB"
        if self.label in ("hard rock", "soft rock"):
            return "Hard Rock" if self.label == "hard rock" else "Soft Rock"

        value = self.numeric_n
        if value is None:
            return ""
        return ">50" if value > 50 else ""

    @property
    def n_plot_fraction(self) -> Optional[float]:
        """Where the dot sits across the plot column, 0..1, saturating at 40.

        This is v6's `min(N, 40) / 60 * 4` against a 4 cm column, i.e. the same
        position -- the web table puts the dot at exactly this fraction.
        """
        value = self.numeric_n
        if value is None:
            return None
        return min(max(value, 0.0), PLOT_SATURATE_N) / PLOT_MAX_N


@dataclass(frozen=True)
class ReportHeader:
    """The block v6 printed above the log."""

    project_type: str = ""
    project_location: str = ""
    client_name: str = ""
    borehole_number: str = ""
    boring_type: str = "Rotary"
    drilling_start: str = ""
    drilling_completion: str = ""
    water_table: Optional[float] = None
    termination_depth: Optional[float] = None

    @property
    def title(self) -> str:
        return (
            "GEOTECHNICAL INVESTIGATION FOR THE PROPOSED\n"
            f"{self.project_type} AT {self.project_location}"
        )

    @property
    def water_table_text(self) -> str:
        if self.water_table is None:
            return "Not met with"
        return f"{self.water_table:.2f} m"


@dataclass(frozen=True)
class ReportData:
    """Everything one borehole's report is made of."""

    header: ReportHeader = field(default_factory=ReportHeader)
    layers: tuple[Layer, ...] = ()
    spt: tuple[SptTest, ...] = ()

    # -- derived -----------------------------------------------------------

    @property
    def soil_end_depth(self) -> Optional[float]:
        """Deepest base of a non-rock interval. SPT below this is rock and the
        v6 log stops drawing N-values there, handing the columns to the rock
        logging block instead."""
        soil = [layer.depth_to for layer in self.layers if not layer.is_rock]
        if soil:
            return max(soil)

        if self.layers:
            # All-rock borehole: there is no soil column at all, so every
            # N-value sits in rock and none of them plots. Returning the
            # deepest rock base here let every in-rock SPT value keep
            # plotting as if the rock were soil.
            return 0.0

        return None

    @property
    def termination_depth(self) -> Optional[float]:
        return self.header.termination_depth

    @property
    def page_count(self) -> int:
        """Depth-based pagination: 20 m to a page, as v6."""
        termination = self.termination_depth
        if termination is None or termination <= 0:
            return 1
        return max(1, math.ceil(termination / MAX_DEPTH_PER_PAGE))


# ---------------------------------------------------------------------------
# The continuous row list. This is the preview's table body *and* the JSON
# contract, so the client never has to re-derive anything.
# ---------------------------------------------------------------------------

RowKind = Literal["layer", "spt", "water_table", "termination"]


@dataclass(frozen=True)
class LogRow:
    kind: RowKind
    sort_depth: float

    # layer / marker fields, all optional
    depth_from: Optional[float] = None
    depth_to: Optional[float] = None
    thickness: Optional[float] = None
    description: str = ""
    is_rock: bool = False
    recovery: Optional[float] = None
    rqd: Optional[float] = None
    remark: str = ""
    recovery_text: str = ""
    rqd_text: str = ""
    hatch: str = ""

    # spt fields
    spt_depth: Optional[float] = None
    spt_depth_text: str = ""
    #: Where the result is *plotted*: the base of the 45 cm drive, or the start
    #: depth for a worded test. Both the PDF and the web log place the value at
    #: this depth, so the two agree on where a test belongs in the hole.
    spt_test_depth: Optional[float] = None
    blows_15: Optional[int] = None
    blows_30: Optional[int] = None
    blows_45: Optional[int] = None
    n_value: Optional[float] = None
    n_text: str = ""
    n_plot_text: str = ""
    n_plot_fraction: Optional[float] = None

    # marker fields
    label: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "depth_from": self.depth_from,
            "depth_to": self.depth_to,
            "thickness": self.thickness,
            "description": self.description,
            "is_rock": self.is_rock,
            "recovery": self.recovery,
            "rqd": self.rqd,
            "remark": self.remark,
            "recovery_text": self.recovery_text,
            "rqd_text": self.rqd_text,
            "hatch": self.hatch,
            "spt_depth": self.spt_depth,
            "spt_depth_text": self.spt_depth_text,
            "spt_test_depth": self.spt_test_depth,
            "blows_15": self.blows_15,
            "blows_30": self.blows_30,
            "blows_45": self.blows_45,
            "n_value": self.n_value,
            "n_text": self.n_text,
            "n_plot_text": self.n_plot_text,
            "n_plot_fraction": self.n_plot_fraction,
            "label": self.label,
        }


def build_log_rows(
    data: ReportData,
    *,
    spt_penetration: float = SPT_PENETRATION,
) -> list[LogRow]:
    """Interleave layers, SPT tests and the two markers into one depth-ordered
    list. Layers are emitted by `data.layers` order (already sorted by depth);
    SPT rows drop below the soil/rock contact exactly as v6 did.

    `spt_penetration` is accepted for callers holding an older drive length;
    the value is threaded through the computed test depths only.
    """
    rows: list[LogRow] = []

    for index, layer in enumerate(data.layers):
        rows.append(
            LogRow(
                kind="layer",
                sort_depth=layer.depth_from,
                depth_from=layer.depth_from,
                depth_to=layer.depth_to,
                thickness=layer.thickness,
                description=layer.description,
                is_rock=layer.is_rock,
                recovery=layer.recovery,
                rqd=layer.rqd,
                remark=layer.remark,
                recovery_text=format_pct(layer.recovery),
                rqd_text=format_pct(layer.rqd),
                hatch=HATCH_PATTERNS[index % len(HATCH_PATTERNS)],
            )
        )

    soil_end = data.soil_end_depth
    for test in data.spt:
        # Below the soil/rock contact the columns belong to the rock logging
        # block; v6 stopped plotting N-values there and so does this.
        if soil_end is not None and test.depth > soil_end + 1e-6:
            continue

        test_depth = (
            test.depth if test.is_qualitative else test.depth + spt_penetration
        )

        rows.append(
            LogRow(
                kind="spt",
                sort_depth=test_depth,
                depth_from=test.depth,
                spt_depth=test.depth,
                spt_depth_text=(
                    test.depth_text
                    if spt_penetration == SPT_PENETRATION
                    else _depth_text(test, spt_penetration)
                ),
                spt_test_depth=test_depth,
                blows_15=_as_int(test.blows_15),
                blows_30=_as_int(test.blows_30),
                blows_45=_as_int(test.blows_45),
                n_value=test.numeric_n,
                n_text=test.n_text,
                n_plot_text=test.n_plot_text,
                n_plot_fraction=test.n_plot_fraction,
            )
        )

    water_table = data.header.water_table
    if water_table is not None:
        rows.append(
            LogRow(
                kind="water_table",
                sort_depth=water_table,
                label=f"Water Table at {water_table:.2f} m",
            )
        )

    termination = data.header.termination_depth
    if termination is not None:
        rows.append(
            LogRow(
                kind="termination",
                sort_depth=termination,
                label=f"THE BOREHOLE WAS TERMINATED AT {termination:.2f} m DEPTH",
            )
        )

    # Depth first; at an identical depth the stratum is printed before the
    # test taken in it, which is how the log reads on paper.
    rows.sort(key=lambda row: (row.sort_depth, 0 if row.kind == "layer" else 1))
    return rows


# ---------------------------------------------------------------------------
# Formatters. v6's, verbatim.
# ---------------------------------------------------------------------------


def fmt_2dp(value: Any) -> str:
    """Two decimal places, or blank. v6's `_fmt_2dp`."""
    try:
        if value is None:
            return ""
        number = float(value)
        if math.isnan(number):
            return ""
        return f"{number:.2f}"
    except (TypeError, ValueError):
        return ""


def format_pct(value: Any) -> str:
    """A percentage, or NIL. v6 printed NIL for a missing or zero reading --
    zero recovery is a real (and alarming) value, but the script treated it as
    "not logged", and the report has to keep saying what the script says."""
    try:
        if value is None:
            return "NIL"
        number = float(value)
        if math.isnan(number) or abs(number) < 1e-9:
            return "NIL"
        return f"{number:.0f}%"
    except (TypeError, ValueError):
        return "NIL"


def wrap_to_chars(text: Any, max_chars: int) -> list[str]:
    """v6's `_wrap_to_chars`: keeps a description inside its column."""
    stripped = str(text or "").strip()
    if not stripped:
        return []
    return textwrap.wrap(
        stripped, width=max_chars, break_long_words=False, break_on_hyphens=False
    )


def column_x() -> dict[str, float]:
    """Left edge of every column, in centimetres from the page's left margin.

    Single definition, so the PDF and any other geometry consumer agree.
    """
    positions: dict[str, float] = {}
    cursor = MARGIN_CM
    for column in COLUMNS:
        positions[column.id] = cursor
        cursor += column.width_cm
    return positions


def depth_to_y(depth: float, max_depth: float) -> float:
    """Centimetres above the page's bottom edge for a depth on the page."""
    return MARGIN_CM + (PLOT_HEIGHT_CM * (1 - depth / max_depth))


def max_lines_for_height(cell_height_cm: float, line_gap_cm: float = 0.28) -> int:
    """How many wrapped description lines fit in a row of this height."""
    return max(1, int((max(0.0, cell_height_cm) - 0.2) // line_gap_cm))


def columns_as_json() -> list[dict[str, Any]]:
    """The column set for the client, so it never hard-codes a header."""
    return [
        {
            "id": column.id,
            "label_lines": list(column.label_lines),
            "label": column.label,
            "percent": round(column.percent_of_plot, 4),
            "rotated": column.rotated,
        }
        for column in COLUMNS
    ]


def report_to_json(data: ReportData, rows: Optional[Iterable[LogRow]] = None) -> dict:
    """The preview payload. Same shape the router returns."""
    header = data.header
    resolved = list(rows) if rows is not None else build_log_rows(data)

    return {
        "header": {
            "title": header.title,
            "project_type": header.project_type,
            "project_location": header.project_location,
            "client_name": header.client_name,
            "borehole_number": header.borehole_number,
            "boring_type": header.boring_type,
            "drilling_start": header.drilling_start,
            "drilling_completion": header.drilling_completion,
            "water_table": header.water_table,
            "water_table_text": header.water_table_text,
            "termination_depth": header.termination_depth,
        },
        "columns": columns_as_json(),
        # `rows` is the depth-ordered stream, for anything that reads the log
        # top to bottom as one sequence.
        "rows": [row.to_json() for row in resolved],
        # `layers` and `spt` are the same content split by kind, because the
        # depth-proportional web log draws each column from its own stream:
        # a stratum is a block, an SPT test is a point on the same axis. Both
        # are projections of the rows above, so they cannot disagree.
        "layers": [row.to_json() for row in resolved if row.kind == "layer"],
        "spt": [row.to_json() for row in resolved if row.kind == "spt"],
        "summary": {
            "layer_count": len(data.layers),
            "spt_count": len(resolved_row_kind(resolved, "spt")),
            "rock_count": len([l for l in data.layers if l.is_rock]),
            "max_depth_per_page": MAX_DEPTH_PER_PAGE,
            "page_count": data.page_count,
        },
    }


def resolved_row_kind(rows: Iterable[LogRow], kind: RowKind) -> list[LogRow]:
    return [row for row in rows if row.kind == kind]


def _depth_text(test: SptTest, penetration: float) -> str:
    if test.is_qualitative:
        return fmt_2dp(test.depth)
    return f"{fmt_2dp(test.depth)} \u2013 {fmt_2dp(test.depth + penetration)}"


def _as_int(value: Any) -> Optional[int]:
    """Blow counts print as whole numbers; v6 called int() on them."""
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None