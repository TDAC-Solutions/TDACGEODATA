"""
TDAC laboratory calculation engines, ported verbatim from the TDAC Basic Lab
Developer Package v0.1.0.

Engine modules (calculation bodies byte-identical to the verified package;
only import lines changed):
    common.py            shared validation / regression / PDF helpers
    grain_size.py        PSD  (sieve + hydrometer, IS 2720-4 / ISO 17892-4)
    particle_density.py  Gs   (pycnometer, IS 2720-3 / ISO 17892-3)
    atterberg.py         LL/PL (Casagrande + fall cone, IS 2720-5 / ISO 17892-12)
    suite.py             combined borehole summary across the three

New integration files (the only code written for this app):
    adapters.py          Results Entry snapshot <-> engine record translation
    pdf.py               renders a stored revision to PDF bytes over HTTP

Contract with the rest of the server:
    - The engines are the calculation authority for PSD, PARTICLE_DENSITY and
      ATTERBERG. lab_data_service.save_lab_revision recomputes the calculation
      snapshot server-side for those three test types, so the browser's local
      engine is a preview only and can never become the released value.
    - SHRINKAGE_LIMIT, TRIAXIAL_UU and CONSOLIDATION are not in the package;
      they keep the client-supplied snapshot exactly as before.
    - The engines always emit report_status "DRAFT / FOR REVIEW" and gate
      issue_eligible behind method_verified / equipment_calibration_verified.
      Approval is the app's review workflow, never the engine's.
"""

from app.lab_engine.common import InputError
from app.lab_engine.adapters import (
    SUPPORTED_TESTS,
    engine_input,
    engine_output,
    run_engine,
)

__all__ = [
    "InputError",
    "SUPPORTED_TESTS",
    "engine_input",
    "engine_output",
    "run_engine",
]
