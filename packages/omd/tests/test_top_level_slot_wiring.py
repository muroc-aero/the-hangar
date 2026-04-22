"""Fast smoke tests for the top-level slot mechanism.

The ``oas/maneuver`` integration tests in ``test_slot_maneuver.py``
are marked ``slow`` because they instantiate a full b738 mission. This
module exercises the slot partition + declarative connection logic
with a synthetic provider so a ``pytest -m 'not slow'`` run still
protects the wiring that Fix 1 introduced.

A synthetic provider is registered at module scope for the duration
of the test module only; the registration is rolled back on teardown.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

from hangar.omd import slots as _slots


# ---------------------------------------------------------------------------
# Synthetic top-level slot provider (no openconcept dependency)
# ---------------------------------------------------------------------------


class _EchoGroup(om.Group):
    """Minimal top-level slot payload: echoes two promoted inputs to
    two renamed outputs so the integration can be observed without any
    external physics package."""

    def setup(self) -> None:
        self.add_subsystem(
            "echo",
            om.ExecComp(
                ["widget = AR * 2.0",
                 "structural_surrogate = MTOW * 0.001"],
                AR={"val": 1.0},
                MTOW={"val": 1000.0, "units": "kg"},
                structural_surrogate={"units": "kg"},
            ),
            promotes_inputs=[("AR", "ac|geom|wing|AR"),
                             ("MTOW", "ac|weights|MTOW")],
            promotes_outputs=["widget", "structural_surrogate"],
        )


def _fake_top_level_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    return (
        _EchoGroup(),
        ["ac|geom|wing|AR", "ac|weights|MTOW"],
        [("widget", "widget_out"),
         ("structural_surrogate", "surrogate_out")],
    )


_fake_top_level_provider.slot_name = "surrogate"
_fake_top_level_provider.slot_scope = "top_level"
_fake_top_level_provider.removes_fields = []
_fake_top_level_provider.adds_fields = {}
_fake_top_level_provider.design_variables = {}
_fake_top_level_provider.result_paths = {
    "widget": "widget_out",
    "surrogate": "surrogate_out",
}
_fake_top_level_provider.required_connections = [
    {
        "when_config": "wire_taper",
        "src": "taper_source.taper",
        "tgt": "{slot_name}.taper_in",
    },
]


@pytest.fixture(autouse=True)
def _register_fake_provider():
    # Force registry init, then patch in the fake provider. Avoids the
    # _ensure_builtins path that would otherwise load openconcept.
    _slots._ensure_builtins()
    _slots._PROVIDERS["test/fake-toplevel"] = _fake_top_level_provider
    try:
        yield
    finally:
        _slots._PROVIDERS.pop("test/fake-toplevel", None)


# ---------------------------------------------------------------------------
# Bare wiring: build an AnalysisGroup-like container and exercise the
# partition + declarative-connection pipeline directly.
# ---------------------------------------------------------------------------


class _FakeAnalysis(om.Group):
    """Stands in for the OCP mission subsystem in the smoke tests."""

    def setup(self) -> None:
        ivc = self.add_subsystem(
            "dummy", om.IndepVarComp(), promotes_outputs=["*"],
        )
        ivc.add_output("ac|geom|wing|AR", val=9.45)
        ivc.add_output("ac|weights|MTOW", val=79000.0, units="kg")


def _build_group_with_slot(slot_cfg: dict) -> om.Problem:
    """Replicate the top-level slot wiring a mission builder would do."""
    from hangar.omd.slots import get_slot_provider

    class Wrapper(om.Group):
        def setup(self):
            dv_comp = self.add_subsystem(
                "dv_comp", om.IndepVarComp(), promotes_outputs=["*"],
            )
            dv_comp.add_output("ac|geom|wing|AR", val=9.45)
            dv_comp.add_output("ac|weights|MTOW", val=79000.0, units="kg")
            self.add_subsystem(
                "analysis", _FakeAnalysis(), promotes_inputs=[], promotes_outputs=[],
            )
            prov = get_slot_provider(slot_cfg["provider"])
            assert getattr(prov, "slot_scope", "per_phase") == "top_level"
            subgrp, prom_in, prom_out = prov(
                nn=1, flight_phase=None, config=slot_cfg.get("config", {}),
            )
            self.add_subsystem(
                slot_cfg.get("slot_name", "slot"),
                subgrp,
                promotes_inputs=prom_in,
                promotes_outputs=prom_out,
            )

    prob = om.Problem(model=Wrapper(), reports=False)
    prob.setup(check=False)
    return prob


class TestSlotPartition:

    def test_top_level_slot_is_sibling_of_analysis(self):
        prob = _build_group_with_slot({
            "provider": "test/fake-toplevel",
            "slot_name": "surrogate",
            "config": {},
        })
        try:
            assert prob.model._get_subsystem("analysis") is not None
            assert prob.model._get_subsystem("surrogate") is not None
            # NOT under analysis (that would be a per_phase slot)
            assert prob.model._get_subsystem("analysis.surrogate") is None
        finally:
            prob.cleanup()

    def test_shared_inputs_feed_from_root(self):
        """Promoted inputs on the slot must pick up root-level IVC."""
        prob = _build_group_with_slot({
            "provider": "test/fake-toplevel",
            "slot_name": "surrogate",
            "config": {},
        })
        try:
            prob.run_model()
            widget = float(np.atleast_1d(prob.get_val("widget_out")).flat[0])
            surrogate = float(np.atleast_1d(
                prob.get_val("surrogate_out"),
            ).flat[0])
            # AR=9.45, MTOW=79000 kg per dv_comp defaults.
            assert abs(widget - 18.9) < 1e-8
            assert abs(surrogate - 79.0) < 1e-8
        finally:
            prob.cleanup()


# ---------------------------------------------------------------------------
# Declarative required_connections
# ---------------------------------------------------------------------------


class TestRequiredConnectionsGating:
    """Directly exercise ``resolve_required_connections`` so the
    OCP-builder-side logic is covered without standing up a mission."""

    def test_gate_off_drops_connection(self):
        from hangar.omd.slots import (
            get_slot_provider,
            resolve_required_connections,
        )
        prov = get_slot_provider("test/fake-toplevel")
        # wire_taper not set -> gated connection is dropped
        conns = resolve_required_connections(
            prov, slot_name="surrogate", first_phase="climb", config={},
        )
        assert conns == []

    def test_gate_on_emits_substituted_connection(self):
        from hangar.omd.slots import (
            get_slot_provider,
            resolve_required_connections,
        )
        prov = get_slot_provider("test/fake-toplevel")
        conns = resolve_required_connections(
            prov, slot_name="surrogate", first_phase="climb",
            config={"wire_taper": True},
        )
        assert conns == [("taper_source.taper", "surrogate.taper_in")]

    def test_oas_maneuver_provider_substitution(self):
        """Spot-check the real oas/maneuver provider formatting."""
        from hangar.omd.slots import (
            get_slot_provider,
            resolve_required_connections,
        )
        prov = get_slot_provider("oas/maneuver")
        conns = resolve_required_connections(
            prov, slot_name="maneuver", first_phase="climb",
            config={"wire_wing_weight": True},
        )
        assert (
            "analysis.climb.ac|weights|W_wing",
            "maneuver.kg_to_N.W_wing",
        ) in conns


class TestSlotEnumWarning:
    """Unknown slot names trigger a validator warning (Fix 1 follow-up)."""

    def test_known_slot_passes(self):
        from hangar.omd.plan_validate import validate_slot_names
        plan = {
            "components": [{
                "id": "mission",
                "type": "ocp/BasicMission",
                "config": {
                    "slots": {
                        "drag": {"provider": "oas/vlm"},
                        "maneuver": {"provider": "oas/maneuver"},
                    },
                },
            }],
        }
        assert validate_slot_names(plan) == []

    def test_typo_flagged(self):
        from hangar.omd.plan_validate import validate_slot_names
        plan = {
            "components": [{
                "id": "mission",
                "type": "ocp/BasicMission",
                "config": {
                    "slots": {"manuever": {"provider": "oas/maneuver"}},
                },
            }],
        }
        findings = validate_slot_names(plan)
        assert findings, "expected a finding for the misspelled slot"
        assert "manuever" in findings[0].message
        assert "maneuver" in findings[0].suggestions
