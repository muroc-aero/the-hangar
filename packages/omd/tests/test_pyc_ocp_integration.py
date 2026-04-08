"""Integration tests for pyCycle-OCP coupling (Path 1 and Path 2).

Tests both approaches to coupling pyCycle propulsion into OCP missions:
- Path 1 (surrogate): Pre-computed Kriging surrogates from pyCycle decks
- Path 2 (direct): Native pyCycle Groups embedded in OCP's solver chain

These tests verify that the slot mechanism, surrogate generation, and
guess_nonlinear convergence fix all work correctly.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest


pytestmark = [pytest.mark.slow]


# ---------------------------------------------------------------------------
# Path 1: Surrogate-coupled tests
# ---------------------------------------------------------------------------


class TestPyCycleSurrogateDeck:
    """Test surrogate deck generation and I/O."""

    def test_turbojet_deck_generation(self):
        """Generate a small turbojet deck and verify outputs."""
        from hangar.omd.pyc.surrogate import generate_deck

        grid = {
            "alt_ft": [0.0, 10000.0],
            "MN": [0.1, 0.3],
            "throttle": [0.7, 1.0],
        }
        deck = generate_deck(archetype="turbojet", grid_spec=grid)

        assert "thrust_lbf" in deck
        assert "fuel_flow_lbm_s" in deck
        assert "converged" in deck
        assert len(deck["alt_ft"]) == 8  # 2x2x2

        mask = deck["converged"]
        assert mask.sum() >= 4, f"Need at least 4 converged points, got {mask.sum()}"

        # Physical sanity: thrust and fuel flow positive for converged points
        assert (deck["thrust_lbf"][mask] > 0).all()
        assert (deck["fuel_flow_lbm_s"][mask] > 0).all()

    def test_deck_save_load(self, tmp_path):
        """Round-trip deck save/load via .npz."""
        from hangar.omd.pyc.surrogate import generate_deck, save_deck, load_deck

        grid = {
            "alt_ft": [0.0, 10000.0],
            "MN": [0.1, 0.3],
            "throttle": [0.8, 1.0],
        }
        deck = generate_deck(archetype="turbojet", grid_spec=grid)

        path = tmp_path / "test_deck.npz"
        save_deck(deck, path)
        loaded = load_deck(path)

        for key in deck:
            np.testing.assert_array_equal(deck[key], loaded[key])


class TestPyCycleSurrogateSlot:
    """Test surrogate propulsion slot in an OpenMDAO problem."""

    def test_surrogate_group_standalone(self):
        """PyCycleSurrogateGroup produces reasonable thrust/fuel_flow."""
        from hangar.omd.pyc.surrogate import PyCycleSurrogateGroup

        nn = 3
        prob = om.Problem(reports=False)
        prob.model.add_subsystem("prop", PyCycleSurrogateGroup(
            nn=nn,
            archetype="turbojet",
            grid_spec={
                "alt_ft": [0.0, 10000.0],
                "MN": [0.1, 0.3],
                "throttle": [0.7, 1.0],
            },
        ), promotes=["*"])
        prob.setup()

        prob.set_val("fltcond|h", [0.0, 1524.0, 3048.0])
        prob.set_val("fltcond|M", [0.15, 0.2, 0.25])
        prob.set_val("throttle", [1.0, 0.85, 0.7])
        prob.run_model()

        thrust = prob.get_val("thrust", units="kN")
        fuel = prob.get_val("fuel_flow", units="kg/s")

        # Thrust should be in a reasonable range for a turbojet
        assert (thrust > 10.0).all(), f"Thrust too low: {thrust}"
        assert (thrust < 100.0).all(), f"Thrust too high: {thrust}"
        assert (fuel > 0.1).all(), f"Fuel flow too low: {fuel}"
        assert (fuel < 5.0).all(), f"Fuel flow too high: {fuel}"

        # Higher throttle should give more thrust
        assert thrust[0] > thrust[2], "Full throttle should give more thrust"

        prob.cleanup()

    def test_surrogate_from_saved_deck(self, tmp_path):
        """PyCycleSurrogateGroup works with a pre-saved deck."""
        from hangar.omd.pyc.surrogate import (
            generate_deck, save_deck, PyCycleSurrogateGroup,
        )

        # Generate and save
        grid = {
            "alt_ft": [0.0, 10000.0],
            "MN": [0.1, 0.3],
            "throttle": [0.7, 1.0],
        }
        deck = generate_deck(archetype="turbojet", grid_spec=grid)
        deck_path = tmp_path / "turbojet.npz"
        save_deck(deck, deck_path)

        # Use saved deck
        nn = 2
        prob = om.Problem(reports=False)
        prob.model.add_subsystem("prop", PyCycleSurrogateGroup(
            nn=nn,
            deck_path=str(deck_path),
        ), promotes=["*"])
        prob.setup()

        prob.set_val("fltcond|h", [0.0, 1524.0])
        prob.set_val("fltcond|M", [0.2, 0.2])
        prob.set_val("throttle", [1.0, 0.8])
        prob.run_model()

        thrust = prob.get_val("thrust", units="kN")
        assert (thrust > 0).all()
        prob.cleanup()


# ---------------------------------------------------------------------------
# Path 2: Direct-coupled tests
# ---------------------------------------------------------------------------


class TestDirectPyCycleTurbojetSlot:
    """Test direct-coupled pyCycle turbojet propulsion slot."""

    def test_direct_group_builds_and_runs(self):
        """_DirectPyCyclePropGroup can be set up and run standalone."""
        from hangar.omd.slots import _DirectPyCyclePropGroup

        nn = 2
        prob = om.Problem(reports=False)
        grp = _DirectPyCyclePropGroup(
            nn=nn,
            design_alt=0.0,
            design_MN=0.000001,
            design_Fn=11800.0,
            design_T4=2370.0,
            thermo_method="CEA",
        )
        prob.model.add_subsystem("prop", grp, promotes=["*"])
        prob.setup()

        # Apply initial guesses (critical for convergence)
        grp.apply_initial_guesses(prob)

        # Set flight conditions
        prob.set_val("fltcond|h", np.array([0.0, 0.0]))  # sea level (meters)
        prob.set_val("fltcond|M", np.array([0.1, 0.1]))
        prob.set_val("throttle", np.array([1.0, 0.8]))

        prob.run_model()

        thrust = prob.get_val("thrust", units="kN")
        fuel = prob.get_val("fuel_flow", units="kg/s")

        # Should produce positive, physically reasonable values
        assert (thrust > 0).all(), f"Thrust not positive: {thrust}"
        assert (fuel > 0).all(), f"Fuel not positive: {fuel}"

        # Full throttle should give more thrust
        assert thrust[0] > thrust[1], (
            f"Full throttle ({thrust[0]:.1f} kN) should exceed "
            f"80% throttle ({thrust[1]:.1f} kN)"
        )

        prob.cleanup()

    def test_slot_provider_interface(self):
        """Slot provider returns correctly shaped outputs."""
        from hangar.omd.slots import get_slot_provider

        provider = get_slot_provider("pyc/turbojet")
        assert provider.slot_name == "propulsion"
        assert "ac|propulsion|engine|rating" in provider.removes_fields

        comp, prom_in, prom_out = provider(
            nn=2,
            flight_phase="cruise",
            config={"design_alt": 0.0, "design_MN": 0.000001},
        )
        assert "fltcond|h" in prom_in
        assert "thrust" in prom_out


class TestDirectPyCycleHBTFSlot:
    """Test direct-coupled pyCycle HBTF propulsion slot."""

    def test_hbtf_group_builds_and_runs(self):
        """_DirectPyCycleHBTFPropGroup can be set up and run standalone."""
        from hangar.omd.slots import _DirectPyCycleHBTFPropGroup

        nn = 2
        prob = om.Problem(reports=False)
        grp = _DirectPyCycleHBTFPropGroup(
            nn=nn,
            design_alt=35000.0,
            design_MN=0.8,
            design_Fn=5900.0,
            design_T4=2857.0,
            thermo_method="CEA",
        )
        prob.model.add_subsystem("prop", grp, promotes=["*"])
        prob.setup()

        grp.apply_initial_guesses(prob)

        # Cruise conditions (meters)
        prob.set_val("fltcond|h", np.array([10668.0, 10668.0]))  # 35000 ft
        prob.set_val("fltcond|M", np.array([0.8, 0.8]))
        prob.set_val("throttle", np.array([1.0, 0.7]))

        prob.run_model()

        thrust = prob.get_val("thrust", units="kN")
        fuel = prob.get_val("fuel_flow", units="kg/s")

        assert (thrust > 0).all(), f"HBTF thrust not positive: {thrust}"
        assert (fuel > 0).all(), f"HBTF fuel not positive: {fuel}"

        prob.cleanup()

    def test_hbtf_slot_provider_interface(self):
        """HBTF slot provider returns correctly shaped outputs."""
        from hangar.omd.slots import get_slot_provider

        provider = get_slot_provider("pyc/hbtf")
        assert provider.slot_name == "propulsion"

        comp, prom_in, prom_out = provider(
            nn=2,
            flight_phase="cruise",
            config={},
        )
        assert "fltcond|h" in prom_in
        assert "thrust" in prom_out


# ---------------------------------------------------------------------------
# Slot design variable exposure
# ---------------------------------------------------------------------------


class TestSlotDesignVariables:
    """Verify slot providers expose design variables through var_paths."""

    def test_turbojet_slot_exposes_dvs(self):
        """pyc/turbojet provider declares comp_PR, comp_eff, turb_eff."""
        from hangar.omd.slots import get_slot_provider

        provider = get_slot_provider("pyc/turbojet")
        dvs = getattr(provider, "design_variables", {})
        assert "comp_PR" in dvs
        assert "comp_eff" in dvs
        assert "turb_eff" in dvs

    def test_vlm_drag_slot_exposes_dvs(self):
        """oas/vlm provider declares twist_cp."""
        from hangar.omd.slots import get_slot_provider

        provider = get_slot_provider("oas/vlm")
        dvs = getattr(provider, "design_variables", {})
        assert "twist_cp" in dvs

    def test_surrogate_slot_has_no_dvs(self):
        """pyc/surrogate exposes no DVs (baked into deck)."""
        from hangar.omd.slots import get_slot_provider

        provider = get_slot_provider("pyc/surrogate")
        dvs = getattr(provider, "design_variables", {})
        assert len(dvs) == 0

    def test_ocp_factory_collects_slot_dvs(self):
        """OCP factory includes slot DVs in metadata var_paths."""
        from hangar.omd.factories.ocp import build_ocp_basic_mission

        config = {
            "aircraft_template": "caravan",
            "architecture": "turboprop",
            "num_nodes": 3,
            "_defer_setup": True,
            "slots": {
                "propulsion": {
                    "provider": "pyc/turbojet",
                    "config": {
                        "design_alt": 0,
                        "design_MN": 0.000001,
                        "design_Fn": 4000,
                        "design_T4": 2370,
                        "thermo_method": "TABULAR",
                    },
                },
            },
        }

        prob, metadata = build_ocp_basic_mission(config, {})
        var_paths = metadata["var_paths"]

        # Slot DVs should be present with phase-prefixed paths
        assert "comp_PR" in var_paths
        assert "climb.propmodel." in var_paths["comp_PR"]
        assert "comp_eff" in var_paths
        assert "turb_eff" in var_paths


# ---------------------------------------------------------------------------
# Weight slot provider
# ---------------------------------------------------------------------------


class TestWeightSlot:
    """Verify parametric weight slot provider."""

    def test_parametric_weight_standalone(self):
        """_ParametricWeightGroup sums component weights to OEW."""
        from hangar.omd.slots import _ParametricWeightGroup

        prob = om.Problem(reports=False)
        prob.model.add_subsystem("wt", _ParametricWeightGroup(
            W_struct_default=600.0,
            W_engine_default=250.0,
            W_systems_default=900.0,
            W_payload_equip_default=350.0,
        ), promotes=["*"])
        prob.setup()
        prob.run_model()

        oew = float(prob.get_val("OEW", units="kg"))
        np.testing.assert_allclose(oew, 600 + 250 + 900 + 350)
        prob.cleanup()

    def test_weight_slot_provider_interface(self):
        """ocp/parametric-weight registers as a weight slot."""
        from hangar.omd.slots import get_slot_provider

        provider = get_slot_provider("ocp/parametric-weight")
        assert provider.slot_name == "weight"
        assert len(provider.removes_fields) == 0

        comp, prom_in, prom_out = provider(
            nn=3, flight_phase="cruise",
            config={"W_struct": 700.0, "W_engine": 300.0},
        )
        assert "OEW" in prom_out

    def test_weight_slot_in_ocp_factory(self):
        """OCP factory with weight slot produces valid OEW."""
        from hangar.omd.factories.ocp import build_ocp_basic_mission

        config = {
            "aircraft_template": "caravan",
            "architecture": "turboprop",
            "num_nodes": 3,
            "mission_params": {
                "cruise_altitude_ft": 18000,
                "mission_range_NM": 250,
                "climb_vs_ftmin": 850,
                "climb_Ueas_kn": 104,
                "cruise_Ueas_kn": 129,
                "descent_vs_ftmin": 400,
                "descent_Ueas_kn": 100,
            },
            "slots": {
                "weight": {
                    "provider": "ocp/parametric-weight",
                    "config": {
                        "W_struct": 600.0,
                        "W_engine": 250.0,
                        "W_systems": 900.0,
                        "W_payload_equip": 350.0,
                    },
                },
            },
        }

        prob, metadata = build_ocp_basic_mission(config, {})
        prob.run_model()

        oew = float(np.atleast_1d(prob.get_val("climb.OEW", units="kg"))[0])
        np.testing.assert_allclose(oew, 600 + 250 + 900 + 350, rtol=1e-6)

        # Mission should still produce positive fuel burn
        fuel_burn = float(np.atleast_1d(
            prob.get_val("descent.fuel_used_final", units="kg")
        )[0])
        assert fuel_burn > 0, f"Fuel burn should be positive: {fuel_burn}"

        prob.cleanup()


# ---------------------------------------------------------------------------
# guess_nonlinear verification
# ---------------------------------------------------------------------------


class TestGuessNonlinear:
    """Verify guess_nonlinear works on archetypes."""

    def test_turbojet_guess_nonlinear_exists(self):
        """Turbojet has guess_nonlinear method."""
        from hangar.omd.pyc.archetypes import Turbojet
        assert hasattr(Turbojet, "guess_nonlinear")

    def test_hbtf_guess_nonlinear_exists(self):
        """HBTF has guess_nonlinear method."""
        from hangar.omd.pyc.hbtf import HBTF
        assert hasattr(HBTF, "guess_nonlinear")

    def test_turbojet_converges_with_guess_nonlinear(self):
        """Turbojet design point converges (guess_nonlinear active)."""
        from hangar.omd.pyc.archetypes import Turbojet
        from hangar.omd.pyc.defaults import (
            DEFAULT_TURBOJET_PARAMS,
            DEFAULT_TURBOJET_DESIGN_GUESSES,
        )

        prob = om.Problem(reports=False)
        prob.model = Turbojet(params=DEFAULT_TURBOJET_PARAMS)
        prob.setup(check=False)

        prob.set_val("fc.alt", 0.0, units="ft")
        prob.set_val("fc.MN", 0.000001)
        prob.set_val("comp.PR", 13.5)
        prob.set_val("comp.eff", 0.83)
        prob.set_val("turb.eff", 0.86)
        prob.set_val("balance.Fn_target", 11800.0, units="lbf")
        prob.set_val("balance.T4_target", 2370.0, units="degR")

        dg = DEFAULT_TURBOJET_DESIGN_GUESSES
        prob.set_val("balance.FAR", dg["FAR"])
        prob.set_val("balance.W", dg["W"])
        prob.set_val("balance.turb_PR", dg["turb_PR"])

        prob.run_model()

        Fn = float(prob.get_val("perf.Fn", units="lbf"))
        np.testing.assert_allclose(Fn, 11800.0, rtol=1e-4)

        prob.cleanup()


# ---------------------------------------------------------------------------
# Full OCP mission convergence tests
# ---------------------------------------------------------------------------


class TestFullMissionConvergence:
    """Full OCP BasicMission with pyCycle propulsion slot.

    These tests use pre-generated surrogate decks to avoid the ~20 min
    deck generation time during the test itself.
    """

    def test_surrogate_mission_converges(self, tmp_path):
        """BasicMission with pyc/surrogate produces positive fuel burn.

        Uses a turbojet designed at moderate altitude (10000 ft, MN=0.3)
        so the off-design envelope covers the mission profile. TABULAR
        thermo for robustness.
        """
        from hangar.omd.pyc.surrogate import generate_deck, save_deck
        from hangar.omd.factories.ocp import build_ocp_basic_mission

        # Design the engine at conditions closer to the cruise point
        design_conds = {
            "alt": 10000.0,  # ft
            "MN": 0.3,
            "Fn_target": 4000.0,  # lbf
            "T4_target": 2370.0,  # degR
        }

        # Grid covers the Caravan flight envelope
        grid = {
            "alt_ft": [0.0, 5000.0, 10000.0, 15000.0, 20000.0],
            "MN": [0.05, 0.15, 0.25, 0.35, 0.45],
            "throttle": [0.3, 0.65, 1.0],
        }
        deck = generate_deck(
            archetype="turbojet",
            design_conditions=design_conds,
            engine_params={"thermo_method": "TABULAR"},
            grid_spec=grid,
        )
        deck_path = tmp_path / "turbojet.npz"
        save_deck(deck, deck_path)

        # Verify enough converged points for Kriging
        n_converged = deck["converged"].sum()
        assert n_converged >= 20, (
            f"Need at least 20 converged deck points, got {n_converged}"
        )

        config = {
            "aircraft_template": "caravan",
            "architecture": "turboprop",
            "num_nodes": 3,
            "mission_params": {
                "cruise_altitude_ft": 15000,
                "mission_range_NM": 200,
                "climb_vs_ftmin": 850,
                "climb_Ueas_kn": 104,
                "cruise_Ueas_kn": 129,
                "descent_vs_ftmin": 400,
                "descent_Ueas_kn": 100,
            },
            "solver_settings": {"maxiter": 50},
            "slots": {
                "propulsion": {
                    "provider": "pyc/surrogate",
                    "config": {
                        "deck_path": str(deck_path),
                    },
                },
            },
        }

        prob, metadata = build_ocp_basic_mission(config, {})
        # Factory already calls setup() and set_val() when defer_setup=False
        prob.run_model()

        fuel_burn = float(np.atleast_1d(
            prob.get_val("descent.fuel_used_final", units="kg")
        )[0])
        assert fuel_burn > 0, f"Fuel burn should be positive: {fuel_burn}"

        for phase in ["climb", "cruise", "descent"]:
            thrust = np.atleast_1d(prob.get_val(f"{phase}.thrust", units="kN"))
            assert (thrust > 0).all(), f"{phase} thrust not positive: {thrust}"

        prob.cleanup()

    def test_direct_turbojet_mission_convergence(self):
        """BasicMission with pyc/turbojet (direct coupling).

        Tests that the outer Newton can drive throttle while pyCycle's
        inner Newton converges. Uses TABULAR thermo for speed.
        """
        from hangar.omd.factories.ocp import build_ocp_basic_mission

        config = {
            "aircraft_template": "caravan",
            "architecture": "turboprop",
            "num_nodes": 3,
            "mission_params": {
                "cruise_altitude_ft": 18000,
                "mission_range_NM": 250,
                "climb_vs_ftmin": 850,
                "climb_Ueas_kn": 104,
                "cruise_Ueas_kn": 129,
                "descent_vs_ftmin": 400,
                "descent_Ueas_kn": 100,
            },
            "solver_settings": {"maxiter": 25},
            "slots": {
                "propulsion": {
                    "provider": "pyc/turbojet",
                    "config": {
                        "design_alt": 0,
                        "design_MN": 0.000001,
                        "design_Fn": 4000,
                        "design_T4": 2370,
                        "thermo_method": "TABULAR",
                    },
                },
            },
        }

        prob, metadata = build_ocp_basic_mission(config, {})
        # Factory already calls setup() and set_val() when defer_setup=False

        # Apply initial guesses for pyCycle convergence
        for phase in metadata.get("phases", []):
            subsys = prob.model._get_subsystem(f"{phase}.propmodel")
            if subsys is not None and hasattr(subsys, "apply_initial_guesses"):
                subsys.apply_initial_guesses(prob)

        prob.run_model()

        fuel_burn = float(np.atleast_1d(
            prob.get_val("descent.fuel_used_final", units="kg")
        )[0])
        assert fuel_burn > 0, f"Fuel burn should be positive: {fuel_burn}"

        for phase in ["climb", "cruise", "descent"]:
            thrust = np.atleast_1d(prob.get_val(f"{phase}.thrust", units="kN"))
            assert (thrust > 0).all(), f"{phase} thrust not positive: {thrust}"

        prob.cleanup()


# ---------------------------------------------------------------------------
# Three-tool composition (OCP + OAS + pyCycle)
# ---------------------------------------------------------------------------


class TestThreeToolMission:
    """Test OCP mission with both drag and propulsion slots filled."""

    def test_three_tool_factory_builds(self):
        """OCP factory accepts both drag and propulsion slots without error."""
        from hangar.omd.factories.ocp import build_ocp_basic_mission

        config = {
            "aircraft_template": "caravan",
            "architecture": "turboprop",
            "num_nodes": 3,
            "_defer_setup": True,
            "slots": {
                "drag": {
                    "provider": "oas/vlm",
                    "config": {"num_x": 2, "num_y": 7, "num_twist": 4},
                },
                "propulsion": {
                    "provider": "pyc/surrogate",
                    "config": {
                        "archetype": "turbojet",
                        "design_alt": 0,
                        "design_MN": 0.000001,
                        "design_Fn": 4000,
                        "design_T4": 2370,
                    },
                },
            },
        }

        prob, metadata = build_ocp_basic_mission(config, {})

        # Both slot DVs should be in var_paths
        var_paths = metadata["var_paths"]
        assert "twist_cp" in var_paths, (
            f"twist_cp not in var_paths: {list(var_paths.keys())}"
        )

        # Declared slots should reflect defaults (not the active providers)
        assert metadata["declared_slots"]["drag"]["default"] == "PolarDrag"
        assert metadata["declared_slots"]["propulsion"]["default"] == "turboprop"

    @pytest.mark.xfail(
        reason=(
            "Three-tool coupling (VLM surrogate drag + pyCycle surrogate "
            "propulsion) produces a singular Jacobian in the DirectSolver. "
            "Both surrogates provide FD-based partials that together make "
            "the Newton system ill-conditioned. Needs solver research: "
            "NLBGS, or direct-coupled drag instead of surrogate."
        ),
        strict=False,
    )
    def test_three_tool_surrogate_mission(self, tmp_path):
        """Full three-tool mission: OAS VLM drag + pyCycle surrogate propulsion."""
        from hangar.omd.pyc.surrogate import generate_deck, save_deck
        from hangar.omd.factories.ocp import build_ocp_basic_mission

        # Generate deck with design at moderate altitude
        grid = {
            "alt_ft": [0.0, 5000.0, 10000.0, 15000.0, 20000.0],
            "MN": [0.05, 0.15, 0.25, 0.35, 0.45],
            "throttle": [0.3, 0.65, 1.0],
        }
        deck = generate_deck(
            archetype="turbojet",
            design_conditions={
                "alt": 10000.0, "MN": 0.3, "Fn_target": 4000.0, "T4_target": 2370.0,
            },
            engine_params={"thermo_method": "TABULAR"},
            grid_spec=grid,
        )
        deck_path = tmp_path / "turbojet.npz"
        save_deck(deck, deck_path)

        config = {
            "aircraft_template": "caravan",
            "architecture": "turboprop",
            "num_nodes": 3,
            "mission_params": {
                "cruise_altitude_ft": 15000,
                "mission_range_NM": 200,
                "climb_vs_ftmin": 850,
                "climb_Ueas_kn": 104,
                "cruise_Ueas_kn": 129,
                "descent_vs_ftmin": 400,
                "descent_Ueas_kn": 100,
            },
            "solver_settings": {"maxiter": 50},
            "slots": {
                "drag": {
                    "provider": "oas/vlm",
                    "config": {"num_x": 2, "num_y": 7, "num_twist": 4},
                },
                "propulsion": {
                    "provider": "pyc/surrogate",
                    "config": {"deck_path": str(deck_path)},
                },
            },
        }

        prob, metadata = build_ocp_basic_mission(config, {})
        prob.run_model()

        fuel_burn = float(np.atleast_1d(
            prob.get_val("descent.fuel_used_final", units="kg")
        )[0])
        assert fuel_burn > 0, f"Fuel burn should be positive: {fuel_burn}"

        for phase in ["climb", "cruise", "descent"]:
            thrust = np.atleast_1d(prob.get_val(f"{phase}.thrust", units="kN"))
            assert (thrust > 0).all(), f"{phase} thrust not positive: {thrust}"
            drag = np.atleast_1d(prob.get_val(f"{phase}.drag", units="N"))
            assert (drag > 0).all(), f"{phase} drag not positive: {drag}"

        prob.cleanup()
