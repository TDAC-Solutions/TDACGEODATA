"""Single registry for the three field datasets.

The parser, the validators, and both write paths all describe the same three
things: the Pydantic row model, the AGS target table with its columns, and
the source row keys that fill them. Declaring that once here stops the model
map, table specs, row map, validator branches, and route literal from
drifting apart — the failure mode that made six INSERT statements out of
three and a five-shape key set out of one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from pydantic import ValidationError

from app.spreadsheet_import.errors import SpreadsheetValidationError
from app.spreadsheet_import.models import (
    BorelogRow,
    FieldDataset,
    RockProfileRow,
    SPTImportRow,
)


@dataclass(frozen=True)
class DatasetSpec:
    """Everything one field dataset needs for validation and persistence."""

    name: str
    label: str
    count_key: str
    table: str
    model: type
    kind: str  # "interval" (depth from/to) or "spt"
    # (source row key, AGS column) in INSERT order; source key 0 is the depth.
    fields: tuple[tuple[str, str], ...]

    @property
    def source_columns(self) -> tuple[str, ...]:
        return tuple(source for source, _ in self.fields)

    @property
    def db_columns(self) -> tuple[str, ...]:
        return tuple(column for _, column in self.fields)

    @property
    def key_columns(self) -> tuple[str, ...]:
        """Columns whose combination must be unique among imported rows."""
        if self.kind == "interval":
            return ("depth_from", "depth_to")
        return ("spt_depth",)

    def insert_sql(self, on_conflict: bool = False) -> str:
        columns = ", ".join(f'"{column}"' for column in self.db_columns)
        placeholders = ", ".join(
            f"${index}" for index in range(3, len(self.fields) + 3)
        )
        sql = (
            f'INSERT INTO "ags42"."{self.table}" '
            f'("PROJ_ID", "LOCA_ID", {columns}) '
            f"VALUES ($1, $2, {placeholders})"
        )
        return f"{sql} ON CONFLICT DO NOTHING" if on_conflict else sql

    def values(
        self, project_id: str, loca_id: str, row: Dict[str, Any]
    ) -> tuple:
        """Bind parameters in insert order for one normalized row."""
        return (
            project_id,
            loca_id,
            *(row.get(source) for source in self.source_columns),
        )


FIELD_DATASETS: Dict[str, DatasetSpec] = {
    "borelog": DatasetSpec(
        name="borelog",
        label="Borelog",
        count_key="geol_rows",
        table="GEOL",
        model=BorelogRow,
        kind="interval",
        fields=(
            ("depth_from", "GEOL_TOP"),
            ("depth_to", "GEOL_BASE"),
            ("soil_description", "GEOL_DESC"),
            ("sand_clay", "GEOL_GEOL"),
        ),
    ),
    "rock_profile": DatasetSpec(
        name="rock_profile",
        label="Rock profile",
        count_key="core_rows",
        table="CORE",
        model=RockProfileRow,
        kind="interval",
        fields=(
            ("depth_from", "CORE_TOP"),
            ("depth_to", "CORE_BASE"),
            ("recovery", "CORE_PREC"),
            ("rqd", "CORE_RQD"),
            ("remark", "CORE_REM"),
        ),
    ),
    "spt": DatasetSpec(
        name="spt",
        label="SPT",
        count_key="spt_rows",
        table="ISPT",
        model=SPTImportRow,
        kind="spt",
        fields=(
            ("spt_depth", "ISPT_TOP"),
            ("blows_15", "ISPT_INC1"),
            ("blows_30", "ISPT_INC2"),
            ("blows_45", "ISPT_INC3"),
            ("n_value", "ISPT_NVAL"),
        ),
    ),
}


def get_dataset(dataset: str) -> DatasetSpec:
    spec = FIELD_DATASETS.get(dataset)
    if spec is None:
        raise SpreadsheetValidationError(
            f"Unknown field dataset {dataset!r}."
        )
    return spec


def normalize_rows(
    dataset: FieldDataset, rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Validate one CSV table payload against its typed Pydantic row model."""
    model = get_dataset(dataset).model
    normalized = []
    for index, row in enumerate(rows, start=1):
        try:
            normalized.append(model.model_validate(row).model_dump())
        except ValidationError as error:
            # Read the first message defensively. error.errors() can be
            # empty and an entry need not carry "msg"; indexing blindly
            # raised inside this handler, which masked the real validation
            # problem as a 500.
            errors = error.errors()
            if errors and isinstance(errors[0], dict) and errors[0].get("msg"):
                detail = errors[0]["msg"]
            else:
                detail = str(error)
            raise SpreadsheetValidationError(
                f"{dataset} row {index} is invalid: {detail}"
            ) from None
    return normalized
