"""
Field Data schemas.

Field Data is sourced from the AGS4 geotechnical tables that already back
the rest of the application (see app/portfolio_service.py, which reads
"ags42"."PROJ" and "ags42"."LOCA"). The column mapping below is fixed by
the application's data contract and must not be changed:

    Borehole / Drilling
        depth_from        -> GEOL.GEOL_TOP
        depth_to          -> GEOL.GEOL_BASE
        soil_description  -> GEOL.GEOL_DESC
        sand_clay         -> GEOL.GEOL_GEOL
        avg_n_value       -> derived from ISPT.ISPT_NVAL (see field_data_service)

    Sampling / Coring
        depth_from        -> CORE.CORE_TOP
        depth_to          -> CORE.CORE_BASE
        rock_description  -> GEOL.GEOL_DESC (same source column as Soil Description)
        recovery          -> CORE.CORE_PREC
        rqd               -> CORE.CORE_RQD
        remark            -> CORE.CORE_REM

    SPT
        spt_depth  -> ISPT.ISPT_TOP
        blows_15   -> ISPT.ISPT_INC1
        blows_30   -> ISPT.ISPT_INC2
        blows_45   -> ISPT.ISPT_INC3
        n_value    -> ISPT.ISPT_NVAL
"""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.rock_metrics import PIECE_UNITS, RockValidationError, compute_rock_metrics, pieces_to_cm


class BoreholeRecord(BaseModel):
    depth_from: Decimal = Field(ge=0)
    depth_to: Optional[Decimal] = Field(default=None, gt=0)
    soil_description: Optional[str] = None
    sand_clay: Optional[str] = None
    avg_n_value: Optional[Decimal] = None


def _reject_inverted_interval(model):
    """GEOL strata run downward: the base must be below the top.

    Without this, depth_from=5 with depth_to=1 is accepted and written to
    ags42."GEOL". Every downstream read then treats the interval as empty:
    the LATERAL that averages ISPT over [GEOL_TOP, GEOL_BASE) matches
    nothing so avg_n_value comes back NULL, and the borehole log draws a
    band with a negative height -- an invisible one, or a bar growing the
    wrong way. This is the same failure the Rock interval check refuses.
    """
    if model.depth_to is None:
        return model
    if model.depth_to <= model.depth_from:
        raise ValueError(
            "Depth To must be greater than Depth From "
            f"(got {model.depth_to} <= {model.depth_from})."
        )
    return model


class BoreholeRecordUpdate(BaseModel):
    """Payload for editing a Borehole / Drilling (GEOL) record.

    depth_from is included because the user may edit the "Depth From"
    value itself; the *current* depth_from used to identify which row to
    update is taken from the URL path, not from this body.
    """

    depth_from: Decimal = Field(ge=0)
    depth_to: Optional[Decimal] = Field(default=None, gt=0)
    soil_description: Optional[str] = None
    sand_clay: Optional[str] = None

    _interval = model_validator(mode="after")(_reject_inverted_interval)


class BoreholeRecordCreate(BaseModel):
    """Payload for adding a new Borehole / Drilling (GEOL) record.

    avg_n_value is intentionally excluded — it is a derived/computed
    value (see field_data_service.get_borehole_records), not a real
    column, so it cannot be created directly.
    """

    depth_from: Decimal = Field(ge=0)
    depth_to: Optional[Decimal] = Field(default=None, gt=0)
    soil_description: Optional[str] = None
    sand_clay: Optional[str] = None

    _interval = model_validator(mode="after")(_reject_inverted_interval)


class SPTRecord(BaseModel):
    spt_depth: Decimal = Field(ge=0)
    blows_15: Optional[Decimal] = Field(default=None, ge=0)
    blows_30: Optional[Decimal] = Field(default=None, ge=0)
    blows_45: Optional[Decimal] = Field(default=None, ge=0)
    n_value: Optional[Decimal] = None
    status: Optional[str] = None


class SPTRecordUpdate(BaseModel):
    spt_depth: Decimal = Field(ge=0)
    blows_15: Optional[Decimal] = Field(default=None, ge=0)
    blows_30: Optional[Decimal] = Field(default=None, ge=0)
    blows_45: Optional[Decimal] = Field(default=None, ge=0)
    # n_value is intentionally excluded here too - see SPTRow.


class SPTRow(BaseModel):
    """One row of the SPT entry grid. n_value/SPTN is never accepted from
    the client - it is always computed and validated on the backend from
    blows_15/30/45 (see field_data_service._compute_spt_n)."""

    spt_depth: Decimal = Field(ge=0)
    blows_15: Optional[Decimal] = Field(default=None, ge=0)
    blows_30: Optional[Decimal] = Field(default=None, ge=0)
    blows_45: Optional[Decimal] = Field(default=None, ge=0)


class SPTBulkCreate(BaseModel):
    """Payload for submitting the SPT entry grid. Only populated rows
    (spt_depth filled in) should be included - blank grid rows are a
    frontend-only concept and are never sent here."""

    records: list[SPTRow]


class SPTReject(BaseModel):
    reason: Optional[str] = None


class SPTPendingRecord(BaseModel):
    sample_id: str
    spt_depth: Decimal = Field(ge=0)
    blows_15: Optional[Decimal] = Field(default=None, ge=0)
    blows_30: Optional[Decimal] = Field(default=None, ge=0)
    blows_45: Optional[Decimal] = Field(default=None, ge=0)
    n_value: Optional[Decimal] = None
    status: str
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    # Set when the row is in the queue because of an edit rather than a fresh
    # submission, from the latest SAMPLE_EDITED audit event for this sample.
    last_edited_by: Optional[str] = None
    last_edited_at: Optional[str] = None


class SoilRecord(BaseModel):
    """Sampling & Coring -> Soil. Sourced from approved SPT (ISPT) records
    only - SPT is the source of truth, so this carries the same Sample ID
    generated when the SPT row was submitted."""

    sample_id: str
    depth_from: Decimal = Field(ge=0)
    blows_15: Optional[Decimal] = Field(default=None, ge=0)
    blows_30: Optional[Decimal] = Field(default=None, ge=0)
    blows_45: Optional[Decimal] = Field(default=None, ge=0)
    n_value: Optional[Decimal] = None


class SamplingRecord(BaseModel):
    depth_from: Decimal = Field(ge=0)
    depth_to: Optional[Decimal] = Field(default=None, gt=0)
    rock_description: Optional[str] = None
    recovery: Optional[Decimal] = Field(default=None, ge=0, le=100)
    rqd: Optional[Decimal] = Field(default=None, ge=0, le=100)
    remark: Optional[str] = None


class SamplingRecordUpdate(BaseModel):
    depth_from: Decimal = Field(ge=0)
    depth_to: Optional[Decimal] = Field(default=None, gt=0)
    # Sourced from GEOL.GEOL_DESC (shared with Borehole / Drilling). Editing
    # it here updates the underlying geology interval that overlaps this
    # sample run, same as editing "Soil Description" on the Borehole tab.
    rock_description: Optional[str] = None
    recovery: Optional[Decimal] = Field(default=None, ge=0, le=100)
    rqd: Optional[Decimal] = Field(default=None, ge=0, le=100)
    remark: Optional[str] = None


class SamplingRecordCreate(BaseModel):
    """Payload for adding a new Sampling / Coring (CORE) record.

    rock_description is intentionally excluded — CORE has no column for
    it (it is only ever sourced from an overlapping GEOL interval, which
    a brand-new sample run will not yet have). Add/edit the geology
    interval from the Borehole / Drilling tab instead.
    """

    depth_from: Decimal = Field(ge=0)
    depth_to: Optional[Decimal] = Field(default=None, gt=0)
    recovery: Optional[Decimal] = Field(default=None, ge=0, le=100)
    rqd: Optional[Decimal] = Field(default=None, ge=0, le=100)
    remark: Optional[str] = None


# ---------------------------------------------------------------------------
# Rock (Field Data > Rock). Mirrors the SPT workflow models.
#
#   depth_from      -> CORE.CORE_TOP
#   depth_to        -> CORE.CORE_BASE
#   recovery        -> CORE.CORE_PREC  (percent, DERIVED from the pieces)
#   rqd             -> CORE.CORE_RQD   (DERIVED from the pieces)
#   rock_type       -> GEOL.GEOL_DESC  (interval depth_from .. depth_to)
#   lift_no         -> tdac.ROCK_RECORD.LIFT_NO           (TDAC-specific)
#   pieces          -> tdac.ROCK_PIECE.LENGTH_CM, one row per Block Number
#
# recovery/rqd are outputs, not inputs: see RockRow.
# ---------------------------------------------------------------------------

class RockRow(BaseModel):
    """One Rock run. Used for both new submissions and edits.

    Recovery and RQD are NOT accepted here. They were hand-typed and could
    disagree with the pieces they claimed to describe; they are now derived
    server-side from `pieces` (see app/rock_metrics.py), so a client cannot
    send a percentage that its own lengths do not support.
    """

    depth_from: Decimal = Field(ge=0)
    depth_to: Decimal = Field(gt=0)
    rock_type: str = Field(min_length=1)
    lift_no: Optional[str] = None
    # Each value is one core piece, in entry order. Order is the Block Number.
    pieces: list[Decimal] = Field(default_factory=list)
    # What the numbers above are denominated in. "cm" is the default and the
    # canonical stored unit; "m" is accepted so an engineer can type metres.
    piece_unit: str = "cm"

    @field_validator("rock_type")
    @classmethod
    def _rock_type_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Type of Rock is required.")
        return value

    @field_validator("lift_no")
    @classmethod
    def _lift_no_trim(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("pieces")
    @classmethod
    def _pieces_non_negative(cls, value: list[Decimal]) -> list[Decimal]:
        for piece in value:
            if piece < 0:
                raise ValueError("Piece lengths cannot be negative.")
        return value

    @field_validator("piece_unit")
    @classmethod
    def _known_unit(cls, value: str) -> str:
        value = (value or "cm").strip().lower()
        if value not in PIECE_UNITS:
            raise ValueError(
                f"piece_unit must be one of {', '.join(PIECE_UNITS)}."
            )
        return value

    @model_validator(mode="after")
    def _depth_to_below_depth_from(self):
        if self.depth_to <= self.depth_from:
            raise ValueError("Run Depth To must be greater than Run Depth From.")
        return self

    @model_validator(mode="after")
    def _pieces_fit_the_run(self):
        # Catch the impossible case at the edge, so the user gets a field
        # error naming the row rather than a 500 from the service.
        try:
            compute_rock_metrics(
                pieces_to_cm(self.pieces, self.piece_unit),
                self.depth_from,
                self.depth_to,
            )
        except RockValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RockBulkCreate(BaseModel):
    """Only populated rows are sent - blank grid rows never reach the API, so
    they never create records or consume a Sample ID."""

    records: list[RockRow]


class RockRecordUpdate(RockRow):
    pass


class RockReject(BaseModel):
    reason: Optional[str] = None
