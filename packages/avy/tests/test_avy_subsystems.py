"""Unit tests for the external subsystem registry + OAS wing-mass builder.

Config validation, resampling, and the driver-knob seam are aviary-free
and run in any venv; builder construction tests importorskip aviary and
run for real via .venv-avy.
"""

from __future__ import annotations

import numpy as np
import pytest

from hangar.avy.subsystems import (
    EXTERNAL_SUBSYSTEMS,
    build_external_subsystems,
    list_external_subsystems_info,
    validate_subsystem_spec,
)
from hangar.avy.subsystems.oas_wing_mass import (
    _nested_driver_knobs,
    _resample,
    resolve_config,
)


class TestResolveConfig:
    def test_defaults_complete(self):
        resolved = resolve_config(None)
        assert resolved["cruise_mach"] == 0.785
        assert resolved["fuel_lbm"] == 40044.0
        assert len(resolved["box_upper_x"]) == 51
        assert len(resolved["twist_cp"]) == 4
        assert resolved["sub_opt_tol"] is None

    def test_unknown_key_suggests(self):
        with pytest.raises(ValueError, match="cruise_mach"):
            resolve_config({"cruise_mac": 0.8})

    def test_wrong_array_length_rejected(self):
        with pytest.raises(ValueError, match="length 4"):
            resolve_config({"twist_cp": [0.0, 1.0]})

    def test_coarse_counts_resample_defaults(self):
        resolved = resolve_config({"num_box_cp": 15, "num_twist_cp": 3})
        assert len(resolved["box_upper_y"]) == 15
        assert len(resolved["skin_thickness_cp"]) == 3
        # endpoints preserved by linear resampling
        assert resolved["box_upper_x"][0] == pytest.approx(0.1)
        assert resolved["box_upper_x"][-1] == pytest.approx(0.6)

    def test_explicit_array_must_match_counts(self):
        with pytest.raises(ValueError, match="length 15"):
            resolve_config({"num_box_cp": 15, "box_upper_x": list(np.linspace(0.1, 0.6, 51))})

    def test_fuel_none_means_deck_driven(self):
        assert resolve_config({"fuel_lbm": None})["fuel_lbm"] is None

    def test_scalar_type_checked(self):
        with pytest.raises(ValueError, match="must be a number"):
            resolve_config({"cruise_mach": "fast"})

    def test_knob_validation(self):
        with pytest.raises(ValueError, match="sub_opt_max_iter"):
            resolve_config({"sub_opt_max_iter": 0})
        assert resolve_config({"sub_opt_tol": 1e-6})["sub_opt_tol"] == 1e-6


def test_resample_identity_and_endpoints():
    vals = [1.0, 2.0, 4.0, 8.0]
    assert _resample(vals, 4) == vals
    down = _resample(vals, 3)
    assert down[0] == 1.0 and down[-1] == 8.0 and len(down) == 3


class TestRegistry:
    def test_listing_is_json_safe(self):
        info = list_external_subsystems_info()
        assert "oas_wing_mass" in info
        entry = info["oas_wing_mass"]
        assert "advanced_single_aisle" in entry["supported_decks"]
        assert "cruise_mach" in entry["config_keys"]
        assert not any(callable(v) for v in entry.values())

    def test_unknown_name_suggests(self):
        with pytest.raises(ValueError, match="oas_wing_mass"):
            validate_subsystem_spec("oas_wing_mas")

    def test_validate_returns_resolved(self):
        resolved = validate_subsystem_spec("oas_wing_mass", {"cruise_mach": 0.78})
        assert resolved["cruise_mach"] == 0.78


def test_nested_driver_knobs_reach_the_driver():
    om = pytest.importorskip("openmdao.api")

    prob = om.Problem()
    prob.model.add_subsystem(
        "comp", om.ExecComp("y = (x - 3.0)**2"), promotes=["*"]
    )
    prob.model.add_design_var("x", lower=-10, upper=10)
    prob.model.add_objective("y")
    prob.driver = om.ScipyOptimizeDriver(optimizer="SLSQP")
    prob.driver.options["tol"] = 1e-9
    prob.setup()

    with _nested_driver_knobs(tol=1e-3, max_iter=7):
        prob.run_driver()
    assert prob.driver.options["tol"] == 1e-3
    assert prob.driver.options["maxiter"] == 7

    # seam restored: a later run must not be re-patched
    prob.driver.options["tol"] = 1e-9
    prob.run_driver()
    assert prob.driver.options["tol"] == 1e-9


class TestBuilderInAviaryVenv:
    @pytest.fixture(autouse=True)
    def _needs_stack(self):
        pytest.importorskip("aviary")
        pytest.importorskip("openaerostruct")
        pytest.importorskip("ambiance")

    def _setup_group(self, config=None):
        import openmdao.api as om

        (builder,) = build_external_subsystems(
            [{"name": "oas_wing_mass", "config": config or {}}]
        )
        import aviary.api as av

        prob = om.Problem()
        prob.model.add_subsystem(
            "wing_mass", builder.build_pre_mission(av.AviaryValues()), promotes=["*"]
        )
        prob.setup()
        return prob

    def test_config_values_reach_component_inputs(self):
        prob = self._setup_group({"cruise_mach": 0.78, "engine_mass_lbm": 8000.0})
        prob.final_setup()  # resolve connections without running a sub-opt
        assert prob.get_val("wing_mass.aerostructures.cruise_Mach").item() == 0.78
        # unit conversion applied on the connection (config lbm -> component kg)
        got = prob.get_val("wing_mass.aerostructures.engine_mass", units="lbm").item()
        assert got == pytest.approx(8000.0)

    def test_wing_mass_promoted_onto_aviary_variable(self):
        import aviary.api as av

        prob = self._setup_group()
        promoted = {
            meta["prom_name"]
            for _, meta in prob.model.list_outputs(prom_name=True, out_stream=None)
        }
        assert av.Aircraft.Wing.MASS in promoted

    def test_deck_driven_fuel_promotes_capacity(self):
        import aviary.api as av

        prob = self._setup_group({"fuel_lbm": None})
        promoted_inputs = {
            meta["prom_name"]
            for _, meta in prob.model.list_inputs(prom_name=True, out_stream=None)
        }
        assert av.Aircraft.Fuel.WING_FUEL_MASS_CAPACITY in promoted_inputs

    def test_coarse_smoke_config_builds(self):
        prob = self._setup_group({"num_box_cp": 15, "num_twist_cp": 3})
        val = prob.get_val("wing_mass.aerostructures.box_upper_x")
        assert val.shape == (15,)


class TestWingMesh:
    """WP4: parametric mesh + deck-derived planform."""

    def test_trapezoid_planform_recovers_area(self):
        from hangar.avy.subsystems.wing_mesh import trapezoid_planform

        pf = trapezoid_planform(span_m=34.2, area_m2=124.7, taper_ratio=0.28, sweep_deg=25.0)
        area = 2 * pf["half_span_m"] * (pf["root_chord_m"] + pf["tip_chord_m"]) / 2
        assert area == pytest.approx(124.7)
        # degenerate kink: chord on the straight taper line
        eta = pf["kink_location_m"] / pf["half_span_m"]
        on_line = pf["root_chord_m"] + (pf["tip_chord_m"] - pf["root_chord_m"]) * eta
        assert pf["kink_chord_m"] == pytest.approx(on_line)

    def test_trapezoid_planform_rejects_garbage(self):
        from hangar.avy.subsystems.wing_mesh import trapezoid_planform

        with pytest.raises(ValueError, match="Implausible"):
            trapezoid_planform(span_m=-1, area_m2=100, taper_ratio=0.3, sweep_deg=25)
        with pytest.raises(ValueError, match="kink_eta"):
            trapezoid_planform(34, 120, 0.3, 25, kink_eta=1.5)

    def test_parametric_mesh_shape_and_sanity(self):
        from hangar.avy.subsystems.wing_mesh import (
            UPSTREAM_PLANFORM,
            mesh_sanity_issues,
            parametric_mesh,
        )

        mesh = parametric_mesh(**UPSTREAM_PLANFORM)
        assert mesh.shape == (2, 7, 3)
        assert mesh_sanity_issues(mesh) == []

    def test_mesh_sanity_catches_bad_mesh(self):
        from hangar.avy.subsystems.wing_mesh import mesh_sanity_issues

        bad = np.zeros((2, 7, 3))  # zero chords, non-monotonic span
        assert mesh_sanity_issues(bad)

    def test_mesh_source_mapping(self):
        from hangar.avy.subsystems.oas_wing_mass import mesh_source

        assert mesh_source(None) == "upstream-hardcoded"
        assert mesh_source({"planform": "deck"}) == "deck-derived"
        assert mesh_source({"planform": {"half_span_m": 18.0}}) == "config"

    def test_planform_config_validation(self):
        with pytest.raises(ValueError, match="planform keys"):
            resolve_config({"planform": {"half_spam_m": 18.0}})
        with pytest.raises(ValueError, match="planform must be"):
            resolve_config({"planform": "dek"})
        resolved = resolve_config({"planform": "deck", "kink_eta": 0.35})
        assert resolved["planform"] == "deck"

    def test_parametric_mesh_matches_upstream_bit_exact(self):
        """The lift-and-parameterize refactor changed nothing (1e-10)."""
        pytest.importorskip("aviary")
        pytest.importorskip("openaerostruct")
        from aviary.models.external_subsystems.open_aero_struct.OAS_wing_mass_analysis import (
            user_mesh,
        )

        from hangar.avy.subsystems.wing_mesh import UPSTREAM_PLANFORM, parametric_mesh

        ours = parametric_mesh(**UPSTREAM_PLANFORM)
        theirs = user_mesh()
        assert np.allclose(ours, theirs, atol=1e-10, rtol=0)
        assert np.array_equal(ours, theirs)  # same ops, same order -> exact

    def test_deck_derived_planform_from_large_single_aisle(self):
        """Second-deck sanity: deck read + trapezoid derivation + mesh."""
        pytest.importorskip("aviary")
        from aviary.utils.process_input_decks import create_vehicle

        from hangar.avy.subsystems.wing_mesh import (
            mesh_sanity_issues,
            parametric_mesh,
            planform_from_deck,
        )

        values, _ = create_vehicle(
            "models/aircraft/large_single_aisle_1/large_single_aisle_1_FLOPS.csv"
        )
        pf = planform_from_deck(values)
        mesh = parametric_mesh(**pf)
        assert mesh_sanity_issues(mesh) == []
        # 737-class wing: half span ~17 m, root chord meters not millimeters
        assert 12 < pf["half_span_m"] < 25
        assert 3 < pf["root_chord_m"] < 12

    @pytest.mark.slow
    def test_deck_derived_sub_opt_plausible_wing_mass(self, tmp_path, monkeypatch):
        """End-to-end WP4: deck-derived planform through a real sub-opt.

        Order-of-magnitude check, not a golden -- the point is that the
        wingbox solves on a planform that is not the advanced single
        aisle's, and returns a transport-plausible wing mass.
        """
        pytest.importorskip("aviary")
        pytest.importorskip("openaerostruct")
        pytest.importorskip("ambiance")
        from aviary.utils.process_input_decks import create_vehicle

        from hangar.avy.subsystems.oas_wing_mass import run_wing_mass_sub_opt

        values, _ = create_vehicle(
            "models/aircraft/large_single_aisle_1/large_single_aisle_1_FLOPS.csv"
        )
        monkeypatch.chdir(tmp_path)  # OAS writes reports cwd-relative
        wing_mass_lbm = run_wing_mass_sub_opt(
            {"planform": "deck", "fuel_lbm": 35000.0}, aviary_values=values
        )
        print(f"\ndeck-derived large-single-aisle wing mass: {wing_mass_lbm:.1f} lbm")
        assert 5000 < wing_mass_lbm < 60000
