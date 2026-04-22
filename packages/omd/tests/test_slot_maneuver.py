"""Tests for the top-level `maneuver` slot.

Covers the first of three multi-tool composition fixes (see
``packages/omd/MULTI_TOOL_COMPOSITION_PLAN.md``). The ``oas/maneuver``
provider wraps OpenConcept's ``Aerostruct`` in a one-shot sizing case
with an alpha-finding balance so a structural stress constraint can be
enforced at (e.g.) 2.5g while the mission runs at cruise conditions.

Tests are split by cost: provider-metadata and declarative-wiring
checks stay fast; anything that stands up a b738 mission is marked
``slow`` so ``pytest -m 'not slow'`` still validates the slot
mechanism end-to-end.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest


# ---------------------------------------------------------------------------
# Provider registration and attributes (fast -- no openconcept mission)
# ---------------------------------------------------------------------------


class TestProviderMetadata:

    def test_oas_maneuver_provider_registered(self):
        from hangar.omd.slots import list_slot_providers, get_slot_provider
        assert "oas/maneuver" in list_slot_providers()
        fn = get_slot_provider("oas/maneuver")
        assert fn.slot_scope == "top_level"
        assert fn.slot_name == "maneuver"

    def test_existing_providers_default_to_per_phase(self):
        from hangar.omd.slots import list_slot_providers, get_slot_provider
        for name in list_slot_providers():
            if name == "oas/maneuver":
                continue
            fn = get_slot_provider(name)
            assert getattr(fn, "slot_scope", "per_phase") == "per_phase", (
                f"Provider {name} is missing slot_scope='per_phase'"
            )

    def test_required_connections_declared(self):
        """oas/maneuver declares its W_wing tap as a required_connections
        entry so the builder wires it without special-casing in the
        factory code."""
        from hangar.omd.slots import get_slot_provider
        fn = get_slot_provider("oas/maneuver")
        conns = getattr(fn, "required_connections", [])
        assert conns, "oas/maneuver must declare required_connections"
        entry = next(
            (c for c in conns if c.get("when_config") == "wire_wing_weight"),
            None,
        )
        assert entry is not None, (
            "wire_wing_weight connection must be declared on the provider"
        )
        assert "{first_phase}" in entry["src"]
        assert "{slot_name}" in entry["tgt"]


# ---------------------------------------------------------------------------
# Standalone _OasManeuverGroup behavior
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestManeuverGroupStandalone:

    def _build(self):
        from hangar.omd.slots import _OasManeuverGroup
        prob = om.Problem(reports=False)
        prob.model.add_subsystem(
            "m",
            _OasManeuverGroup(
                num_x=2, num_y=5, num_twist=3, num_toverc=3,
                num_skin=3, num_spar=3,
            ),
            promotes=["*"],
        )
        prob.model.nonlinear_solver = om.NewtonSolver(
            solve_subsystems=True, maxiter=20, iprint=0,
        )
        prob.model.linear_solver = om.DirectSolver()
        prob.setup(check=False)
        return prob

    def test_computes_failure(self):
        prob = self._build()
        prob.set_val("ac|geom|wing|S_ref", 124.6, units="m**2")
        prob.set_val("ac|geom|wing|AR", 9.45)
        prob.set_val("ac|geom|wing|taper", 0.159)
        prob.set_val("ac|geom|wing|c4sweep", 25.0, units="deg")
        prob.set_val("ac|geom|wing|twist", [-2.0, 0.0, 2.0], units="deg")
        prob.set_val("ac|geom|wing|toverc", [0.12, 0.12, 0.12])
        prob.set_val(
            "ac|geom|wing|skin_thickness", [0.005, 0.010, 0.015], units="m",
        )
        prob.set_val(
            "ac|geom|wing|spar_thickness", [0.005, 0.0075, 0.010], units="m",
        )
        prob.set_val("ac|weights|MTOW", 79002.0, units="kg")
        prob.set_val("ac|weights|orig_W_wing", 6561.57, units="kg")
        prob.set_val("load_factor", 2.5)
        prob.run_model()

        failure = float(np.atleast_1d(prob.get_val("failure")).flat[0])
        assert np.isfinite(failure), f"failure not finite: {failure}"


# ---------------------------------------------------------------------------
# Builder integration: slot partition + top-level wiring
# ---------------------------------------------------------------------------


def _b738_with_maneuver_plan(include_maneuver: bool) -> dict:
    slots: dict = {
        "drag": {
            "provider": "oas/aerostruct",
            "config": {
                "num_x": 2, "num_y": 6,
                "num_twist": 3, "num_toverc": 3,
                "num_skin": 3, "num_spar": 3,
            },
        },
    }
    if include_maneuver:
        slots["maneuver"] = {
            "provider": "oas/maneuver",
            "config": {
                "num_x": 2, "num_y": 6,
                "num_twist": 3, "num_toverc": 3,
                "num_skin": 3, "num_spar": 3,
                "mach": 0.8,
                "altitude_ft": 20000.0,
                "load_factor": 2.5,
            },
        }
    return {
        "id": "test-maneuver",
        "name": "B738 maneuver slot test",
        "version": 1,
        "components": [
            {
                "id": "mission",
                "type": "ocp/BasicMission",
                "config": {
                    "aircraft_template": "b738",
                    "architecture": "twin_turbofan",
                    "num_nodes": 3,
                    "mission_params": {
                        "cruise_altitude_ft": 35000.0,
                        "mission_range_NM": 300.0,
                        "climb_vs_ftmin": 1500.0,
                        "climb_Ueas_kn": 230.0,
                        "cruise_Ueas_kn": 270.0,
                        "descent_vs_ftmin": 1500.0,
                        "descent_Ueas_kn": 250.0,
                    },
                    "slots": slots,
                },
            },
        ],
    }


@pytest.mark.slow
class TestBuilderSlotPartition:
    """The builder must keep per_phase slots inside each phase and
    wire top_level slots as siblings of `analysis`."""

    def test_top_level_slot_sibling_of_analysis(self):
        from hangar.omd.materializer import materialize
        plan = _b738_with_maneuver_plan(include_maneuver=True)
        prob, meta = materialize(plan)

        # `analysis` subsystem exists under the AnalysisGroup root
        analysis = prob.model._get_subsystem("analysis")
        assert analysis is not None

        # `maneuver` exists as sibling
        maneuver = prob.model._get_subsystem("maneuver")
        assert maneuver is not None

        # `maneuver` is NOT pushed down into the phase's acmodel
        for phase in ("climb", "cruise", "descent"):
            pushed = prob.model._get_subsystem(
                f"analysis.{phase}.acmodel.maneuver",
            )
            assert pushed is None, (
                f"top_level slot incorrectly inserted at "
                f"analysis.{phase}.acmodel.maneuver"
            )

    def test_drag_slot_still_per_phase(self):
        from hangar.omd.materializer import materialize
        plan = _b738_with_maneuver_plan(include_maneuver=True)
        prob, _ = materialize(plan)
        for phase in ("climb", "cruise", "descent"):
            drag = prob.model._get_subsystem(f"analysis.{phase}.acmodel.drag")
            assert drag is not None, (
                f"per_phase drag slot missing at analysis.{phase}.acmodel.drag"
            )

    def test_plan_without_maneuver_unchanged(self):
        """Regression: the existing drag-only slot path still works."""
        from hangar.omd.materializer import materialize
        plan = _b738_with_maneuver_plan(include_maneuver=False)
        prob, _ = materialize(plan)
        assert prob.model._get_subsystem("maneuver") is None
        for phase in ("climb", "cruise", "descent"):
            drag = prob.model._get_subsystem(f"analysis.{phase}.acmodel.drag")
            assert drag is not None


# ---------------------------------------------------------------------------
# Result extraction: failure_maneuver surfaces in summary["slots"]
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestManeuverAnalysisRun:
    """Run analysis mode on a minimal b738 + maneuver plan and verify
    the failure_maneuver output is computed and reasonable."""

    def test_failure_maneuver_finite_after_analysis(self):
        from hangar.omd.materializer import materialize
        from hangar.omd.run import _extract_slot_results
        plan = _b738_with_maneuver_plan(include_maneuver=True)
        prob, meta = materialize(plan)
        prob.run_model()
        slots_summary = _extract_slot_results(
            prob,
            active_slots=meta.get("active_slots", {}),
            phases=meta.get("phases", ["climb", "cruise", "descent"]),
            comp_prefix="",
        )
        assert "maneuver" in slots_summary, (
            f"expected 'maneuver' in extracted slots, got keys "
            f"{list(slots_summary)}"
        )
        failure = slots_summary["maneuver"]["failure"]
        assert np.isfinite(failure), f"failure_maneuver not finite: {failure}"

    def test_var_paths_exposes_failure_maneuver(self):
        """The builder must make `failure_maneuver` resolvable as a
        short name so plans can constrain it by that name."""
        from hangar.omd.materializer import materialize
        plan = _b738_with_maneuver_plan(include_maneuver=True)
        _, meta = materialize(plan)
        var_paths = meta.get("var_paths", {})
        assert var_paths.get("failure_maneuver") == "failure_maneuver", (
            f"var_paths missing failure_maneuver: {var_paths}"
        )
