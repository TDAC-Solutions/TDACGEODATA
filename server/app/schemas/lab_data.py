from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class LabTestCreate(BaseModel):
    loca_id: str
    samp_id: str
    specimen_ref: str
    test_type: str
    method_definition_id: UUID
    laboratory: str
    technician: str | None = None
    test_started_at: datetime | None = None
    test_completed_at: datetime | None = None


class LabRevisionSave(BaseModel):
    """A calculated draft for one test revision.

    The snapshots are stored verbatim in lab.test_revision so the exact raw
    readings, calculation output and validation findings are reproducible.
    """

    raw_input_snapshot: dict[str, Any] = Field(default_factory=dict)
    calculation_output_snapshot: dict[str, Any] | None = None
    validation_snapshot: dict[str, Any] | None = None
    revision_reason: str | None = None


class LabReviewAction(BaseModel):
    reason: str | None = None


class LabCalculateRequest(BaseModel):
    """Dry-run the server calculation engine against raw readings.

    raw_input_snapshot is optional: when omitted, the engine recalculates the
    stored revision's raw snapshot (the same authoritative path a save
    takes, without persisting anything).
    """

    raw_input_snapshot: dict[str, Any] | None = None


class LabTestBulkCreate(BaseModel):
    """Multi-select registration: one LabTestCreate per ticked test type.

    The batch commits in one transaction, so a duplicate or an invalid
    method rolls the whole selection back rather than leaving the sample
    half-registered. Every test must reference the SAME sample; the
    service rejects mixed batches so a hand-crafted request cannot insert
    every test against whichever sample happened to come first.
    """

    tests: list[LabTestCreate] = Field(min_length=1)