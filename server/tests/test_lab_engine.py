"""The TDAC Basic Lab Developer Package's own unit tests, ported to the
server's lab_engine package.

The engine files are verbatim ports, so these tests must keep passing
unchanged (module imports aside). If one of these fails after an engine
update, the port has drifted from the verified package -- that is the point
of keeping them.

The legacy sieve fixture (example_kesavapuram_sieve.json) referenced by the
package's grain-size test is not shipped in the package; that one test is
omitted here and its coverage is replaced by the mass-reconciliation and
duplicate-sieve tests in this same file, which run against the synthetic
fixture that IS shipped.
"""

import copy
import json
from pathlib import Path
import unittest

from app.lab_engine import grain_size, particle_density, atterberg
from app.lab_engine.suite import build_combined_borehole_summary
from app.lab_engine.common import InputError

# grain_size.py defines its own InputError locally (the verbatim port keeps
# it); it is a ValueError sibling, not a subclass of common.InputError. The
# negative grain-size tests assert on the class the module actually raises,
# exactly like the package's own test did.
from app.lab_engine.grain_size import InputError as GrainInputError

HERE = Path(__file__).parent / "fixtures" / "lab_engine"


def _tests(name):
    return json.loads((HERE / name).read_text())["tests"]


def _first(name):
    return _tests(name)[0]


class GrainSizeTests(unittest.TestCase):
    def test_synthetic_hydro_whole_sample_link_and_d10(self):
        r = grain_size.process_test(_first("example_synthetic_sieve_hydrometer.json"))
        h = r["hydrometer"]["rows"]
        self.assertAlmostEqual(h[0]["passing_pct"], 15.625)
        self.assertAlmostEqual(h[2]["passing_pct"], 10)
        self.assertAlmostEqual(r["d_values"]["D10_mm"], h[2]["size_mm"])
        self.assertAlmostEqual(r["fractions_profile"]["fines_pct"], 25)
        self.assertEqual(
            len(grain_size.build_borehole_summary([r], "DEMO-BH")["rows"]), 1
        )

    def test_mass_reconciliation_is_enforced(self):
        x = copy.deepcopy(_first("example_synthetic_sieve_hydrometer.json"))
        x["sieve"]["TDAC_SIEVE_ROWS"][0]["TDAC_RETAINED_G"] += 2
        with self.assertRaisesRegex(GrainInputError, "reconcile"):
            grain_size.process_test(x)

    def test_duplicate_and_unordered_sieves_are_rejected(self):
        x = copy.deepcopy(_first("example_synthetic_sieve_hydrometer.json"))
        x["sieve"]["TDAC_SIEVE_ROWS"][1]["GRAT_SIZE"] = 4.75
        with self.assertRaisesRegex(GrainInputError, "decreasing"):
            grain_size.process_test(x)

    def test_iso_hydro_cannot_use_only_75_micron_anchor(self):
        x = copy.deepcopy(_first("example_synthetic_sieve_hydrometer.json"))
        x["sieve"]["TDAC_SIEVE_ROWS"][-1]["GRAT_SIZE"] = 0.075
        with self.assertRaisesRegex(GrainInputError, "observed 0.063 mm"):
            grain_size.process_test(x)

    def test_blank_or_unphysical_hydro_is_rejected(self):
        x = copy.deepcopy(_first("example_synthetic_sieve_hydrometer.json"))
        x["hydrometer"]["TDAC_READINGS"][0]["TDAC_RAW_READING"] = 50
        with self.assertRaisesRegex(GrainInputError, "concentration"):
            grain_size.process_test(x)
        x = copy.deepcopy(_first("example_synthetic_sieve_hydrometer.json"))
        x["hydrometer"]["TDAC_READINGS"][0]["TDAC_ELAPSED_MIN"] = 0
        with self.assertRaisesRegex(GrainInputError, "positive"):
            grain_size.process_test(x)


class ParticleDensityTests(unittest.TestCase):
    def test_fluid_pycnometer_and_replicates(self):
        r = particle_density.process_test(_first("example_specific_gravity.json"))
        self.assertAlmostEqual(
            r["trials"][0]["specific_gravity"], 25 / 9.7, places=8
        )
        self.assertTrue(r["replicate_pass"])
        self.assertFalse(r["issue_eligible"])
        self.assertAlmostEqual(
            r["ags_candidate"]["LPDN"]["LPDN_PDEN"], r["particle_density_kg_m3"]
        )

    def test_invalid_mass_order_and_gas_profile(self):
        x = copy.deepcopy(_first("example_specific_gravity.json"))
        x["trials"][0]["TDAC_M3_PYC_SOIL_FLUID_G"] = 180
        with self.assertRaisesRegex(InputError, "displaced-fluid"):
            particle_density.process_test(x)
        x = copy.deepcopy(_first("example_specific_gravity.json"))
        x["method"] = "gas_pycnometer"
        with self.assertRaisesRegex(InputError, "ISO"):
            particle_density.process_test(x)

    def test_iso_gas_volume_route(self):
        x = copy.deepcopy(_first("example_specific_gravity.json"))
        x["standard_profile"] = "ISO_17892_3_2015"
        x["method"] = "gas_pycnometer"
        x["TDAC_TOLERANCE_BASIS"] = "particle_density_kg_m3"
        x["TDAC_REPLICATE_TOLERANCE"] = 20
        x["trials"] = [
            {"TDAC_DRY_SOIL_MASS_G": 26.50, "TDAC_PARTICLE_VOLUME_CM3": 10.00,
             "TDAC_TEMPERATURE_C": 20, "TDAC_REFERENCE_WATER_DENSITY_KG_M3": 998.2},
            {"TDAC_DRY_SOIL_MASS_G": 26.55, "TDAC_PARTICLE_VOLUME_CM3": 10.00,
             "TDAC_TEMPERATURE_C": 20, "TDAC_REFERENCE_WATER_DENSITY_KG_M3": 998.2},
        ]
        r = particle_density.process_test(x)
        self.assertAlmostEqual(r["particle_density_kg_m3"], 2652.5)
        self.assertTrue(r["replicate_pass"])


class AtterbergTests(unittest.TestCase):
    def test_casagrande_ll_pl_indices(self):
        r = atterberg.process_test(_first("example_atterberg.json"))
        self.assertAlmostEqual(r["LL_pct"], 45.0, delta=0.001)
        self.assertAlmostEqual(r["PL_pct"], 24.5, places=4)
        self.assertAlmostEqual(r["PI_pct"], 20.5, delta=0.001)
        self.assertAlmostEqual(r["flow_index"], 12.0, delta=0.01)
        self.assertAlmostEqual(
            r["liquidity_index"], (32 - 24.5) / 20.5, delta=0.0001
        )
        self.assertFalse(r["issue_eligible"])

    def test_fall_cone_and_nonplastic_category(self):
        r = atterberg.process_test(_tests("example_atterberg.json")[1])
        self.assertTrue(r["liquid_limit"]["reference_bracketed"])
        self.assertGreater(r["LL_pct"], r["PL_pct"])
        x = copy.deepcopy(_tests("example_atterberg.json")[1])
        x["plastic_limit"] = {"TDAC_NON_PLASTIC": True, "TDAC_PL_TRIALS": []}
        r = atterberg.process_test(x)
        self.assertEqual(r["ags_candidate"]["LLPL"]["LLPL_PI"], "NP")
        self.assertIsNone(r["PI_pct"])

    def test_bad_tin_masses_are_rejected(self):
        x = copy.deepcopy(_first("example_atterberg.json"))
        x["liquid_limit"]["TDAC_LL_TRIALS"][0]["TDAC_CONTAINER_WET_G"] = 29
        with self.assertRaisesRegex(InputError, "wet >= dry"):
            atterberg.process_test(x)


class CombinedSummaryTests(unittest.TestCase):
    def test_join_by_sample_depth(self):
        g = grain_size.process_test(_first("example_synthetic_sieve_hydrometer.json"))
        d = particle_density.process_test(_first("example_specific_gravity.json"))
        a = [atterberg.process_test(x) for x in _tests("example_atterberg.json")]
        s = build_combined_borehole_summary([g], [d], a, "DEMO-BH")
        self.assertEqual(len(s["rows"]), 2)
        self.assertIsNotNone(s["rows"][0]["grain_size"])
        self.assertIsNotNone(s["rows"][0]["particle_density"])
        self.assertIsNotNone(s["rows"][0]["atterberg"])
        self.assertIsNone(s["rows"][1]["grain_size"])


if __name__ == "__main__":
    unittest.main()
