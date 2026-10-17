"""
Field-workbook import schemas.

The workbook shape produced by app.spreadsheet_import.field_parser and the
bodies for the two import endpoints that commit it:

  ProjectExcelImport -> "Add New Project" page (creates PROJ + first LOCA)
  LocaExcelImport    -> Overview "import" (adds a LOCA to an existing project)

Field mapping is fixed by the existing AGS data contract (see
schemas/field_data.py); importing introduces no new database columns:

  Borelog row  -> GEOL (GEOL_TOP, GEOL_BASE, GEOL_DESC, GEOL_GEOL)
  Rock row     -> CORE (CORE_TOP, CORE_BASE, CORE_PREC, CORE_RQD, CORE_REM)
  SPT row      -> ISPT (ISPT_TOP, ISPT_INC1..INC3, ISPT_NVAL)
  Project info -> PROJ (PROJ_LOC, PROJ_CLNT) + LOCA (LOCA_ID, LOCA_STAR,
                  LOCA_ENDD, LOCA_FDEP, LOCA_TYPE)
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# The canonical field-dataset keys. Every layer that keys off a dataset name
# reads this one alias; the registry in app.spreadsheet_import.datasets
# carries the per-dataset detail.
FieldDataset = Literal["borelog", "rock_profile", "spt"]


class ProjectInfoData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_type: Optional[str] = None
    project_location: Optional[str] = None
    client_name: Optional[str] = None
    borehole_number: Optional[str] = None
    # Sheets do not carry it today, but a project-scoped export may state
    # which project it belongs to; the loca import verifies it on commit.
    project_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # Decimal, not float: JSON numbers are parsed to their exact decimal
    # digits, so 5.8 stays 5.8 through the round trip and asyncpg stores
    # exactly that in NUMERIC columns (a float would land as
    # 5.79999999999999982236431605997495353221893310546875).
    final_depth: Optional[Decimal] = None


class BorelogRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depth_from: Decimal
    depth_to: Decimal
    soil_description: Optional[str] = None
    sand_clay: Optional[str] = None


class RockProfileRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depth_from: Decimal
    depth_to: Decimal
    rock_description: Optional[str] = None
    recovery: Optional[Decimal] = None
    rqd: Optional[Decimal] = None
    remark: Optional[str] = None


class SPTImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spt_depth: Decimal
    blows_15: Optional[Decimal] = None
    blows_30: Optional[Decimal] = None
    blows_45: Optional[Decimal] = None
    n_value: Optional[Decimal] = None


class ImportedWorkbook(BaseModel):
    project_info: ProjectInfoData = Field(default_factory=ProjectInfoData)
    borelog: List[BorelogRow] = Field(default_factory=list)
    rock_profile: List[RockProfileRow] = Field(default_factory=list)
    spt: List[SPTImportRow] = Field(default_factory=list)


class ProjectMetadataImport(BaseModel):
    """Project metadata carried by the current Add Project form."""

    road_reference: Optional[str] = None
    chainage_text: Optional[str] = None
    structure_reference: Optional[str] = None
    selected_boreholes: Optional[str] = None

    project_type: Optional[str] = None
    report_type: Optional[str] = None
    report_title: Optional[str] = None
    report_volume_title: Optional[str] = None
    document_reference: Optional[str] = None
    revision: Optional[str] = None
    report_date: Optional[date] = None
    issue_status: Optional[str] = None

    tdac_company_name: Optional[str] = None
    groundwater_basis: Optional[str] = None
    design_standard_basis: Optional[str] = None
    factor_of_safety_basis: Optional[str] = None
    load_combination_basis: Optional[str] = None
    construction_verification_requirement: Optional[str] = None
    pile_load_test_requirement: Optional[str] = None


class ProjectExcelImport(BaseModel):
    """Commit body for the Add New Project page.

    Form values override the sheet when present, so a user can correct a
    prefilled field before submitting; anything left blank falls back to
    the workbook's ProjectInfo sheet.
    """

    project_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)

    project_location: Optional[str] = None
    project_client: Optional[str] = None
    consultant_name: Optional[str] = None
    contractor_name: Optional[str] = None

    borehole_id: Optional[str] = None
    borehole_type: str = "BH"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    final_depth: Optional[Decimal] = None

    metadata: Optional[ProjectMetadataImport] = None
    workbook: ImportedWorkbook


class LocaExcelImport(BaseModel):
    """Commit body for the Overview import (location into an open project).

    The location identity comes from the workbook itself; only the type,
    which the sheet does not carry, is supplied here.
    """

    borehole_type: str = "BH"
    workbook: ImportedWorkbook


class FieldTableImport(BaseModel):
    """One CSV field table appended to an existing project location."""

    dataset: FieldDataset
    rows: List[Dict[str, Any]] = Field(default_factory=list)
