from datetime import date
from decimal import Decimal

from typing import Optional

from pydantic import BaseModel, Field


class ProjectMetadataCreate(BaseModel):
    road_reference: str | None = None
    chainage_text: str | None = None
    structure_reference: str | None = None
    selected_boreholes: str | None = None
    project_type: str | None = None

    report_type: str | None = None
    report_title: str | None = None
    report_volume_title: str | None = None
    document_reference: str | None = None
    revision: str | None = None
    report_date: date | None = None
    issue_status: str | None = None

    tdac_company_name: str | None = None
    groundwater_basis: str | None = None

    design_standard_basis: str | None = None
    factor_of_safety_basis: str | None = None
    load_combination_basis: str | None = None
    construction_verification_requirement: str | None = None
    pile_load_test_requirement: str | None = None


class ProjectCreate(BaseModel):
    project_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    project_location: str = Field(min_length=1)
    project_client: str = Field(min_length=1)

    consultant_name: str = Field(min_length=1)
    contractor_name: str = Field(min_length=1)

    metadata: ProjectMetadataCreate | None = None


class ProjectUpdate(BaseModel):
    project_name: str = Field(min_length=1)
    project_location: str = Field(min_length=1)
    project_client: str = Field(min_length=1)


class ProjectOverviewUpdate(BaseModel):
    project_name: str = Field(min_length=1)
    project_location: str = Field(min_length=1)
    project_client: str = Field(min_length=1)

    consultant_name: str = Field(min_length=1)
    contractor_name: str = Field(min_length=1)

    road_reference: str = Field(min_length=1)
    chainage_text: str = Field(min_length=1)
    structure_reference: str = Field(min_length=1)
    selected_boreholes: str = Field(min_length=1)

    report_type: str = Field(min_length=1)
    report_title: str = Field(min_length=1)
    report_volume_title: str = Field(min_length=1)
    document_reference: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    report_date: date
    issue_status: str = Field(min_length=1)

    tdac_company_name: str = Field(min_length=1)
    groundwater_basis: str = Field(min_length=1)

    design_standard_basis: str = ""
    factor_of_safety_basis: str = ""
    load_combination_basis: str = ""
    construction_verification_requirement: str = ""
    pile_load_test_requirement: str = ""


class LocaCreate(BaseModel):
    loca_id: str = Field(min_length=1)
    loca_type: str = Field(min_length=1)

    start_date: date | None = None
    end_date: date | None = None
    final_depth: Optional[Decimal] = Field(default=None, gt=0)

    # Survey and siting data. Every one of these already has a home in
    # ags42."LOCA" (the standard AGS location table), so none of them
    # introduces a schema change. All are optional because a borehole
    # record is often entered long before the surveyor's coordinates
    # arrive; the modal only sends what was actually typed.
    ground_level: Optional[Decimal] = None       # LOCA_GL  - RL, metres
    easting: Optional[Decimal] = None            # LOCA_NATE
    northing: Optional[Decimal] = None           # LOCA_NATN
    latitude: Optional[str] = None               # LOCA_LAT - text in AGS
    longitude: Optional[str] = None              # LOCA_LON - text in AGS
    groundwater_depth: Optional[Decimal] = Field(default=None, ge=0)
