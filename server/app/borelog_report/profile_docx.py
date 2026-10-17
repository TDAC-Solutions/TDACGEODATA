"""The v6 soil-profile narrative, as a Word document.

`create_profile_docx()` in `Borelog_Report_with_Profile_and_RockIntegrated_v6.py`
wrote `{file}_Soil_Profile.docx`: a title, one paragraph that walks every
stratum in depth order with the SPT result(s) falling inside it, and a numbered
stratigraphic summary. The port keeps the prose -- the transition phrases, the
NIL / rebound / soft-and-hard-rock clauses, the ">50" rule, the termination and
groundwater sentences -- and reads it from `ReportData` instead of a workbook,
so the narrative cannot disagree with the log it describes.

Blank soil intervals are skipped exactly as v6 skipped them; rock runs are kept
even when their description is empty, because recovery and RQD are the point of
a core run.

`python-docx` is imported inside `render_profile_docx`, so this module costs
nothing until a .docx is actually requested. The prose helpers above it are
plain functions over layout's dataclasses and are unit-testable on their own.
"""

from __future__ import annotations

import io
from typing import Optional

from app.borelog_report.layout import SPT_PENETRATION, Layer, ReportData, SptTest

#: v6's transition vocabulary for layers after the first, reused in order.
_TRANSITIONS = (
    "Beneath this,",
    "This was followed by",
    "Below this,",
    "Further below,",
    "Subsequently,",
)


def _numeric_spt(test: SptTest) -> Optional[float]:
    """The test as a number, or None. v6 also accepted a literal ">50" as 51,
    which its `_numeric_spt` did; the app stores numbers, but a workbook-fed
    value can still arrive as text."""
    value = test.numeric_n
    if value is not None:
        return value
    if ">" in test.label:
        return 51.0
    return None


def spt_summary_for_interval(
    depth_from: float,
    depth_to: float,
    tests: tuple[SptTest, ...],
    penetration: float = SPT_PENETRATION,
) -> str:
    """v6's `_spt_summary_for_interval`, as a clause starting "with ...".

    A test belongs to the stratum its *test* depth falls in -- the base of the
    45 cm drive for a driven test, the start depth for a worded one -- so this
    is the same placement the log draws at, not the same as comparing the
    start depths.
    """
    if not tests:
        return "with no SPT conducted within this interval"

    in_interval = [
        test for test in tests if depth_from <= test.test_depth < depth_to
    ]
    if not in_interval:
        return "with no SPT recorded within this interval"

    values: list[float] = []
    rebound = False
    hard_rock = False
    soft_rock = False
    over_50 = False

    for test in in_interval:
        label = test.label
        if label in ("rb", "rebound"):
            rebound = True
            continue
        if label == "hard rock":
            hard_rock = True
            continue
        if label == "soft rock":
            soft_rock = True
            continue

        value = _numeric_spt(test)
        if value is None:
            continue
        if value >= 50:
            over_50 = True
        values.append(value)

    if rebound:
        return "with SPT rebound recorded"
    if hard_rock:
        return "with hard rock (SPT not representative)"
    if soft_rock:
        return "with soft rock (SPT not representative)"
    if over_50 and not values:
        return "with SPT N value greater than 50"
    if not values:
        return "with no SPT recorded within this interval"

    smallest, largest = min(values), max(values)
    if round(smallest) == round(largest):
        return f"with SPT N value {int(round(smallest))}"
    return (
        f"with SPT N value ranging from {int(round(smallest))} "
        f"to {int(round(largest))}"
    )


def _rock_pct(value: Optional[float]) -> str:
    """v6's `_fmt` for the rock sentence: NIL when not logged, otherwise a
    whole percentage."""
    if value is None:
        return "NIL"
    try:
        return f"{int(value)}%"
    except (TypeError, ValueError):
        return "NIL"


def narrated_layers(data: ReportData) -> list[Layer]:
    """The strata the narrative names, in order: v6 skipped a soil interval
    with a blank description, but kept a rock run with one."""
    return [
        layer
        for layer in data.layers
        if layer.description.strip() or layer.is_rock
    ]


def _stratum_sentence(
    prefix: str, layer: Layer, tests: tuple[SptTest, ...]
) -> str:
    description = layer.description.strip()
    if layer.is_rock:
        tail = (
            f"with core recovery of {_rock_pct(layer.recovery)} "
            f"and RQD of {_rock_pct(layer.rqd)}."
        )
    else:
        tail = f"{spt_summary_for_interval(layer.depth_from, layer.depth_to, tests)}."
    return (
        f"{prefix} {description} extends from {layer.depth_from:.2f} m "
        f"to {layer.depth_to:.2f} m, {tail}"
    )


def compose_narrative(data: ReportData) -> tuple[str, str]:
    """The borehole label and the narrative paragraph, exactly as v6 wrote
    them: first stratum "In {bh}, ...", the rest through the transitions,
    then termination and groundwater sentences."""
    layers = narrated_layers(data)

    borehole = str(data.header.borehole_number).strip()
    if borehole in ("", "None", "nan"):
        borehole = "BH"

    water_table = data.header.water_table
    if water_table is None:
        groundwater = "Groundwater was not encountered during drilling."
    else:
        groundwater = (
            f"Groundwater was encountered at {float(water_table):.2f} m bgl "
            "during drilling."
        )

    termination = data.header.termination_depth
    last_material = (
        layers[-1].description.strip() if layers else "the encountered material"
    )

    lines: list[str] = []
    if layers:
        lines.append(_stratum_sentence(f"In {borehole},", layers[0], data.spt))
    for index, layer in enumerate(layers[1:], start=1):
        phrase = _TRANSITIONS[(index - 1) % len(_TRANSITIONS)]
        lines.append(_stratum_sentence(phrase, layer, data.spt))

    if termination is not None:
        lines.append(
            f"The borehole was terminated at {termination:.2f} m "
            f"in {last_material}."
        )
    elif layers:
        lines.append(
            f"The borehole was terminated at {layers[-1].depth_to:.2f} m "
            f"in {last_material}."
        )

    lines.append(groundwater)
    return borehole, " ".join(lines)


def render_profile_docx(data: ReportData) -> bytes:
    """The .docx bytes: title, narrative paragraph, numbered summary.

    Font sizes and emphasis are v6's: a 12 pt bold title, the narrative at
    11 pt, a bold summary heading, and one numbered line per stratum carrying
    the same "with ..." clause as the narrative.
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    borehole, paragraph = compose_narrative(data)

    document = Document()

    title = document.add_paragraph(f"Soil Profile Description \u2014 {borehole}")
    title.runs[0].bold = True
    title.runs[0].font.size = Pt(12)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT

    narrative = document.add_paragraph(paragraph)
    if narrative.runs:
        narrative.runs[0].font.size = Pt(11)

    document.add_paragraph("")
    heading = document.add_paragraph(f"{borehole} \u2014 Stratigraphic Summary")
    heading.runs[0].bold = True

    for index, layer in enumerate(narrated_layers(data), start=1):
        with_text = spt_summary_for_interval(
            layer.depth_from, layer.depth_to, data.spt
        )
        document.add_paragraph(
            f"{index:02d}. {layer.depth_from:.2f}\u2013{layer.depth_to:.2f} m: "
            f"{layer.description.strip()}, {with_text}"
        )

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
