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
