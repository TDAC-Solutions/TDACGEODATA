"""The v6 log, drawn page by page, returning bytes instead of writing files.

This is `Borelog_Report_with_Profile_and_RockIntegrated_v6.py`'s page routine
with two mechanical substitutions and nothing else:

    v6 read `pd.read_excel(...)`      ->  here it is handed `ReportData`
    v6 `plt.savefig(path)` per page   ->  here it is `PdfPages`, one buffer

Every geometric decision -- page size, margins, the 19 cm column strip, the
column header band, the hatch rotation, the description wrap at 55 characters,
the water-table rule, the SPT dot placement, the row rules, the termination
note, the header text baselines -- is carried over from the script unchanged
and read from `layout.py`, which also feeds the on-screen preview. The script
itself is untouched.

Not imported at package level: matplotlib costs the better part of a second to
import and the JSON preview endpoint must not pay for it. The router imports
this module lazily, on the first PDF request.
"""

from __future__ import annotations

import io
import math
import threading
from typing import Any, Optional

from app.borelog_report.layout import (
    BY_ID,
    COL_HEADER_HEIGHT_CM,
    COLUMNS,
    HEADER_HEIGHT_CM,
    HATCH_PATTERNS,
    MARGIN_CM,
    MAX_DEPTH_PER_PAGE,
    PAGE_HEIGHT_CM,
    PAGE_WIDTH_CM,
    PLOT_HEIGHT_CM,
    PLOT_SATURATE_N,
    SPT_PENETRATION,
    SPT_PLOT_WIDTH_CM,
    TITLE_HEIGHT_CM,
    Layer,
    ReportData,
    SptTest,
    column_x,
    depth_to_y,
    fmt_2dp,
    format_pct,
    max_lines_for_height,
    wrap_to_chars,
)

#: v6 wrote the water-table rule as `col_x["Description"] .. + 6`, i.e. the
#: full width of the description column. Read from the column definition rather
#: than repeated, so widening the column widens the rule with it.
DESCRIPTION_WIDTH_CM = BY_ID["description"].width_cm

#: v6 printed the N-value column header on two lines.
_N_VALUE_LABEL = "SPT\nN-Value"

#: v6 wrapped a description at this width: a 6 cm column at 6 pt holds ~55
#: characters without touching the rule at its right edge.
_DESCRIPTION_WRAP_CHARS = 55

#: Baseline-to-baseline spacing of wrapped description lines, in cm.
_DESCRIPTION_LINE_GAP_CM = 0.28

# --- label collision avoidance ----------------------------------------------
#
# Everything in the log is drawn at its true depth, so two labels close enough
# to touch print on top of each other and neither can be read. Nothing upstream
# stops that: an SPT depth only has to be >= 0, so tests 0.1 m apart are
# accepted, and a stratum can be a tenth of a metre thick.
#
# The gaps below are derived from the text rather than guessed. Measured on the
# rendered page, 6 pt text stands about 0.212 cm tall, and the plotted depth of
# two tests 0.2 m apart on a 20 m page is 0.219 cm -- which is why labels first
# merge at around 0.2 m and not at the 0.5 m the spacing suggests. One and a
# half text heights clears the rows with room to read them as separate, while
# staying small enough that a nudged label is still recognisably at its own
# depth.
_TEXT_HEIGHT_CM = 6 / 72 * 2.54

#: Between two SPT rows, and between two depth labels in the Depth column.
#: 0.318 cm on a 21.9 cm plot is 0.29 m of separation.
MIN_LABEL_GAP_CM = _TEXT_HEIGHT_CM * 1.5


def _nudge_down(y: float, used: list[float], gap: float = MIN_LABEL_GAP_CM) -> float:
    """Return the y at which a label may be drawn without touching a used one.

    Always moves *deeper* -- to a smaller y, since y falls as depth increases --
    never shallower. Two reasons: a marker that rose could float above its own
    depth into the stratum above, reading as a test taken in the wrong material;
    and processing in depth order means every previously placed label is already
    shallower, so a downward move can only ever increase the gaps.

    Steps in whole gaps rather than to the exact minimum, so a run of close
    labels settles onto an even lattice instead of drifting by fractions.

    Clamped so a marker can never be pushed off the bottom of the plotted area,
    even in a log with more tests packed into it than the page can hold.
    """
    if not used:
        return y

    for step in range(len(used) + 2):
        candidate = y - step * gap
        if all(abs(candidate - previous) >= gap for previous in used):
            # Clears everything. Clamped only if it would fall off the page,
            # which cannot happen before the margin is reached, since y rises
            # with depth and the deepest label starts at or above MARGIN_CM.
            return max(candidate, MARGIN_CM)

    # The page is full: more labels than it can hold at this gap. Place this one
    # at the margin, in step with the last one placed rather than exactly on
    # top of it -- two labels at the identical y are indistinguishable, whereas
    # two a fraction apart are still countable.
    return max(min(y, used[-1] - gap * 0.25), MARGIN_CM)


#: matplotlib keeps process-global state -- the font cache, the current figure,
#: rcParams -- and mutates it during a draw. Two renders interleaved on two
#: threads can therefore corrupt each other: one closes a figure the other is
#: still building. Every render takes this lock, so concurrent requests queue
#: instead of racing. The router runs the render in a worker thread already, so
#: the event loop is untouched while they wait.
_RENDER_LOCK = threading.Lock()


def render_borelog_pdf(
    data: ReportData,
    logo_bytes: Optional[bytes] = None,
) -> bytes:
    """Render the report and return the PDF bytes.

    Pagination is the v6 one and the only one: `MAX_DEPTH_PER_PAGE` metres to a
    page, so a 45 m borehole is three pages.
    """
    if not data.layers:
        raise ValueError("There is no borelog data for this location yet.")

    import matplotlib

    matplotlib.use("Agg")  # no display on a server
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    termination_depth = data.termination_depth
    if termination_depth is None or termination_depth <= 0:
        termination_depth = max(layer.depth_to for layer in data.layers)
    if termination_depth <= 0:
        termination_depth = float(MAX_DEPTH_PER_PAGE)

    soil_end_depth = data.soil_end_depth
    if soil_end_depth is None:
        soil_end_depth = termination_depth

    col_x = column_x()
    num_pages = max(1, math.ceil(termination_depth / MAX_DEPTH_PER_PAGE))

    buffer = io.BytesIO()
    with _RENDER_LOCK, PdfPages(buffer) as pdf:
        for page in range(num_pages):
            start_depth = page * MAX_DEPTH_PER_PAGE
            end_depth = min((page + 1) * MAX_DEPTH_PER_PAGE, termination_depth)

            # add_axes([0, 0, 1, 1]) pins the drawing area to the full page, so
            # the centimetre coordinates below land where the script's
            # tight_layout() put them -- on the sheet edge, not inset.
            fig = plt.figure(figsize=(PAGE_WIDTH_CM / 2.54, PAGE_HEIGHT_CM / 2.54))
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(0, PAGE_WIDTH_CM)
            ax.set_ylim(0, PAGE_HEIGHT_CM)
            ax.axis("off")

            _draw_page(
                ax=ax,
                data=data,
                start_depth=start_depth,
                end_depth=end_depth,
                termination_depth=termination_depth,
                soil_end_depth=soil_end_depth,
                col_x=col_x,
                logo_bytes=logo_bytes,
            )

            pdf.savefig(fig)
            plt.close(fig)

    return buffer.getvalue()


def _draw_page(
    *,
    ax: Any,
    data: ReportData,
    start_depth: float,
    end_depth: float,
    termination_depth: float,
    soil_end_depth: float,
    col_x: dict[str, float],
    logo_bytes: Optional[bytes],
) -> None:
    import matplotlib.image as mpimg
    import matplotlib.patches as patches
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from matplotlib.patches import Rectangle

    header = data.header

    # -- page border -------------------------------------------------------
    ax.add_patch(
        Rectangle(
            (MARGIN_CM, MARGIN_CM),
            PAGE_WIDTH_CM - 2 * MARGIN_CM,
            PAGE_HEIGHT_CM - 2 * MARGIN_CM,
            linewidth=0.6,
            edgecolor="black",
            facecolor="none",
        )
    )

    # -- title ------------------------------------------------------------
    ax.text(
        PAGE_WIDTH_CM / 2,
        PAGE_HEIGHT_CM - MARGIN_CM - 0.2,
        header.title,
        ha="center",
        va="top",
        fontsize=10,
        fontweight="bold",
    )

    # -- logo. The script wrapped this in try/except and carried on without
    #    it; a deployment with no logo file still gets a report.
    if logo_bytes:
        try:
            logo = mpimg.imread(io.BytesIO(logo_bytes), format="png")
            imagebox = OffsetImage(logo, zoom=0.24)
            ax.add_artist(
                AnnotationBbox(
                    imagebox, (3.3, PAGE_HEIGHT_CM - 3.0), frameon=False
                )
            )
        except Exception:
            pass

    # -- header block. Two columns of four, both starting 2.5 cm down. ----
    header_texts_col1 = [
        f"Client: {header.client_name}",
        f"Borehole No: {header.borehole_number}",
        f"Type of Boring: {header.boring_type}",
        f"Termination Depth: {fmt_2dp(termination_depth)} m",
    ]
    header_texts_col2 = [
        f"Boring Start Date: {header.drilling_start}",
        f"Completion Date: {header.drilling_completion}",
        f"Ground Water Table: {header.water_table_text}",
        f"Location: {header.project_location}",
    ]

    for index, text in enumerate(header_texts_col1):
        ax.text(
            6.0,
            PAGE_HEIGHT_CM - 2.5 - index * 0.5,
            text,
            ha="left",
            va="top",
            fontsize=7,
        )
    for index, text in enumerate(header_texts_col2):
        ax.text(
            15.0,
            PAGE_HEIGHT_CM - 2.5 - index * 0.5,
            text,
            ha="left",
            va="top",
            fontsize=7,
        )

    # -- water table rule, on whichever page it falls ----------------------
    # Placement is v6's: at its own depth, dotted blue, across the description
    # column, label to the right of it. The zorder is the only addition, so a
    # nudged stratum description or SPT row can never print over the line a
    # reader is using to find the water strike.
    water_table = header.water_table
    if water_table is not None and start_depth <= water_table <= end_depth:
        wy = depth_to_y(water_table - start_depth, MAX_DEPTH_PER_PAGE)
        ax.hlines(
            wy,
            col_x["description"],
            col_x["description"] + DESCRIPTION_WIDTH_CM,
            linestyle="dotted",
            color="blue",
            linewidth=1,
            zorder=20,
        )
        ax.text(
            col_x["description"] + 0.1,
            wy + 0.15,
            f"Water Table at {water_table:.2f} m",
            fontsize=6,
            ha="left",
            color="blue",
            zorder=20,
        )

    # -- column header band ------------------------------------------------
    header_y_top = PAGE_HEIGHT_CM - (
        MARGIN_CM + TITLE_HEIGHT_CM + HEADER_HEIGHT_CM
    )
    header_y_bottom = header_y_top - COL_HEADER_HEIGHT_CM

    for column in COLUMNS:
        x0 = col_x[column.id]
        ax.add_patch(
            patches.Rectangle(
                (x0, header_y_bottom),
                column.width_cm,
                COL_HEADER_HEIGHT_CM,
                edgecolor="black",
                facecolor="white",
                linewidth=0.6,
            )
        )
        label = _N_VALUE_LABEL if column.id == "n_value" else column.label
        ax.text(
            x0 + column.width_cm / 2,
            header_y_bottom + COL_HEADER_HEIGHT_CM / 2,
            label,
            ha="center",
            va="center",
            fontsize=7,
            rotation=90 if column.rotated else 0,
        )

    # -- column rules ------------------------------------------------------
    table_bottom_y = depth_to_y(end_depth - start_depth, MAX_DEPTH_PER_PAGE)
    for column in COLUMNS:
        if column.id == "spt_plot":
            continue
        x1 = col_x[column.id] + column.width_cm
        ax.plot([x1, x1], [header_y_bottom, table_bottom_y], color="black", linewidth=0.3)

    # -- row rules ---------------------------------------------------------
    for layer in data.layers:
        bot = layer.depth_to
        if not (start_depth < bot <= end_depth):
            continue
        y = (
            PAGE_HEIGHT_CM
            - MARGIN_CM
            - TITLE_HEIGHT_CM
            - HEADER_HEIGHT_CM
            - COL_HEADER_HEIGHT_CM
            - (bot - start_depth) / MAX_DEPTH_PER_PAGE * PLOT_HEIGHT_CM
        )
        x_left = col_x["depth"]
        x_right = (
            col_x["spt_plot"] + SPT_PLOT_WIDTH_CM
            if layer.is_rock
            else col_x["thickness"] + 1
        )
        ax.plot([x_left, x_right], [y, y], color="black", linewidth=0.3)

    # -- layers ------------------------------------------------------------
    # Thin strata put their labels on top of one another, so the two numeric
    # columns are tracked and nudged separately: each only has to clear the
    # label above it in its own column.
    used_depth_label_ys: list[float] = []
    used_thickness_ys: list[float] = []

    for index, layer in enumerate(data.layers):
        top, bot = layer.depth_from, layer.depth_to
        if bot <= start_depth or top >= end_depth:
            continue

        clipped_top = max(top, start_depth)
        clipped_bot = min(bot, end_depth)
        y_top = depth_to_y(clipped_top - start_depth, MAX_DEPTH_PER_PAGE)
        y_bot = depth_to_y(clipped_bot - start_depth, MAX_DEPTH_PER_PAGE)
        y_mid = (y_top + y_bot) / 2

        if layer.is_rock:
            # Rock reads as a dark band on a heavier diagonal than any soil
            # hatch, but translucent with a solid outline. It was a flat black
            # fill, which is the usual convention and needed no legend -- but a
            # core run that overlaps a soil stratum painted over it and the
            # layer underneath vanished, which read as a broken render.
            ax.add_patch(
                patches.Rectangle(
                    (col_x["profile"], y_bot),
                    1,
                    y_top - y_bot,
                    facecolor=(0.0, 0.0, 0.0, 0.32),
                    edgecolor="black",
                    hatch="\\",
                    linewidth=0.6,
                )
            )
        else:
            ax.add_patch(
                patches.Rectangle(
                    (col_x["profile"], y_bot),
                    1,
                    y_top - y_bot,
                    facecolor="white",
                    hatch=HATCH_PATTERNS[index % len(HATCH_PATTERNS)],
                    edgecolor="black",
                    linewidth=0.3,
                )
            )

        # Description, wrapped to the column and clipped to the row. Where a
        # row is too short for its text the last visible line takes an
        # ellipsis, so a truncated description never reads as a complete one.
        cell_h = max(0.0, y_top - y_bot)
        lines = wrap_to_chars(layer.description, _DESCRIPTION_WRAP_CHARS)
        if lines:
            max_lines = max_lines_for_height(cell_h, _DESCRIPTION_LINE_GAP_CM)
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                if len(lines[-1]) > 3:
                    lines[-1] = lines[-1].rstrip()[:-1] + "\u2026"
                else:
                    lines[-1] = lines[-1] + "\u2026"

            y_start = y_top - 0.15
            for line_index, line in enumerate(lines):
                ax.text(
                    col_x["description"] + 0.1,
                    y_start - line_index * _DESCRIPTION_LINE_GAP_CM,
                    line,
                    fontsize=6,
                    ha="left",
                    va="top",
                )

        # Depth is printed at the base of the row, matching the rules. Nudged
        # deeper if the stratum above ended close enough that the two numbers
        # would merge, for the same reason the SPT rows are nudged.
        depth_y = _nudge_down(y_bot + 0.2, used_depth_label_ys)
        used_depth_label_ys.append(depth_y)

        ax.text(
            col_x["depth"] + 0.5,
            depth_y,
            f"{bot:.2f}",
            ha="center",
            va="top",
            fontsize=6,
        )
        # Thickness is centred in its own band and nudged the same way, tracked
        # separately: it is a different column, so it only has to clear the
        # thicknesses above it, not the depth labels.
        thickness_y = _nudge_down(y_mid, used_thickness_ys)
        used_thickness_ys.append(thickness_y)

        ax.text(
            col_x["thickness"] + 0.5,
            thickness_y,
            f"{layer.thickness:.2f}",
            ha="center",
            va="center",
            fontsize=6,
        )

        # Rock runs take over the SPT columns for their interval: the block is
        # painted white to erase the vertical rules inside it, then filled with
        # the recovery figures.
        if layer.is_rock:
            _draw_rock_block(
                ax=ax,
                col_x=col_x,
                layer=layer,
                y_top=y_top,
                y_bot=y_bot,
                y_mid=y_mid,
                patches=patches,
            )

    # -- SPT ---------------------------------------------------------------
    # Tests closer together than a text height would print over one another, so
    # each is nudged deeper until it clears the ones already on the page. An
    # isolated test is untouched and still draws at its exact depth.
    used_spt_ys: list[float] = []

    for test in data.spt:
        start_d = test.depth
        if start_d > soil_end_depth + 1e-6:
            continue

        plot_d = test.depth if test.is_qualitative else start_d + SPT_PENETRATION

        if not (start_depth <= plot_d <= end_depth):
            continue

        y_true = depth_to_y(plot_d - start_depth, MAX_DEPTH_PER_PAGE)
        y = _nudge_down(y_true, used_spt_ys)
        used_spt_ys.append(y)
        y_shift = 0.01

        ax.text(
            col_x["spt_depth"] + 1,
            y + y_shift,
            test.depth_text,
            ha="center",
            va="bottom",
            fontsize=6,
        )

        for column_id, value in (
            ("blows_15", test.blows_15),
            ("blows_30", test.blows_30),
            ("blows_45", test.blows_45),
        ):
            if value is None:
                continue
            ax.text(
                col_x[column_id] + 0.5,
                y + y_shift,
                f"{int(value)}",
                ha="center",
                va="bottom",
                fontsize=6,
            )

        _draw_spt_value(
            ax=ax, test=test, col_x=col_x, y=y, y_shift=y_shift
        )

        # The row rule beneath the test. Drawn at the *nudged* y, so the rule
        # stays attached to the values it belongs to: nudging the text but not
        # its rule would leave a row's underline drifting up under its neighbour.
        # At the termination depth the rule runs the full width of the plot
        # column, closing the log.
        check_depth = test.test_depth
        if not (start_depth <= check_depth <= end_depth):
            continue

        y_sep = y
        x_end = (
            col_x["spt_plot"] + SPT_PLOT_WIDTH_CM
            if abs(check_depth - termination_depth) < 0.01
            else col_x["n_value"] + 1
        )
        ax.hlines(y_sep, col_x["spt_depth"], x_end, linewidth=0.3, color="black")

    # -- termination note --------------------------------------------------
    # Text and position are v6's; zorder added so a nudged SPT row or stratum
    # label sitting just above the base of the hole cannot print over the note
    # that closes the log.
    if start_depth <= termination_depth <= end_depth:
        ty = depth_to_y(termination_depth - start_depth, MAX_DEPTH_PER_PAGE)
        ax.text(
            PAGE_WIDTH_CM / 2,
            ty - 0.5,
            f"THE BOREHOLE WAS TERMINATED AT {termination_depth:.2f} m DEPTH",
            ha="center",
            fontsize=6.5,
            zorder=20,
        )


def _draw_rock_block(*, ax, col_x, layer: Layer, y_top, y_bot, y_mid, patches) -> None:
    """Recovery and RQD, printed over the SPT columns for a rock interval."""
    x0 = col_x["spt_depth"]
    width = (col_x["spt_plot"] + SPT_PLOT_WIDTH_CM) - x0

    ax.add_patch(
        patches.Rectangle(
            (x0, y_bot),
            width,
            y_top - y_bot,
            facecolor="white",
            edgecolor="black",
            linewidth=0.3,
            zorder=5,
        )
    )

    lines = [
        f"CORE RECOVERY = {format_pct(layer.recovery)}",
        f"RQD = {format_pct(layer.rqd)}",
    ]
    remark = str(layer.remark or "").strip()
    if remark:
        lines.append(remark)

    ax.text(
        x0 + width / 2,
        y_mid,
        "\n".join(lines),
        ha="center",
        va="center",
        fontsize=6,
        zorder=6,
    )


def _draw_spt_value(*, ax, test: SptTest, col_x, y: float, y_shift: float) -> None:
    """The N-value cell and its dot in the plot column."""
    n_x = col_x["n_value"] + 0.5
    plot_x = col_x["spt_plot"]

    if test.is_qualitative:
        ax.text(
            n_x,
            y + y_shift,
            test.n_text,
            ha="center",
            va="bottom",
            fontsize=6,
            color="black",
        )
        # v6 anchored the worded labels differently: RB centred in the column,
        # the rock labels running left from it so a long word cannot spill.
        annotation = test.n_plot_text
        if annotation == "RB":
            ax.text(plot_x + 3, y + 0.05, annotation, color="red", fontsize=6, ha="center")
        elif annotation:
            ax.text(plot_x + 3, y + 0.05, annotation, color="red", fontsize=6, ha="left")
        return

    value = test.numeric_n
    if value is None:
        ax.text(
            n_x,
            y + y_shift,
            str(test.n_value),
            ha="center",
            va="bottom",
            fontsize=6,
        )
        return

    ax.text(
        n_x,
        y + y_shift,
        ">50" if value > 50 else f"{value:.0f}",
        ha="center",
        va="bottom",
        fontsize=6,
    )

    x_plot = plot_x + (min(max(value, 0.0), PLOT_SATURATE_N) / 60.0) * SPT_PLOT_WIDTH_CM
    ax.plot(x_plot, y + 0.2, "ro", markersize=2.5)
    if value > 50:
        ax.text(x_plot + 0.5, y + 0.2, ">50", color="red", fontsize=6, ha="left")