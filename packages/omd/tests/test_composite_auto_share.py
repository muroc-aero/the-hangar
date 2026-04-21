"""Tests for Fix 3 Phase 3a: auto-derived shared_vars from factory contracts.

The plan-level ``composition_policy: auto`` flag makes the materializer
walk each component's :class:`FactoryContract.produces` and hoist names
that appear in two or more components into the root ``shared_ivc``.
User-declared ``shared_vars`` still win by name, and ``no_auto_share``
blocks an individual name from auto-hoisting. Default policy
(``explicit``) keeps Fix 2 behavior byte-identical.

These tests monkeypatch contracts on the paraboloid factory so the
composite scenarios stay fast (no OAS or OCP setup). The helper
``validate_contract_integrity`` in ``tests/_contract_integrity.py``
covers real factories separately.
"""

from __future__ import annotations

import pytest

from hangar.omd.factory_metadata import FactoryContract, VarSpec
from hangar.omd.factories.paraboloid import build_paraboloid


@pytest.fixture
def paraboloid_with_shared_contract(monkeypatch):
    """Temporarily redeclare paraboloid's contract to produce `x`.

    Paraboloid has no internal IVC for `x`, but ``skip_fields=[x]``
    is a no-op for it (`x` is already an unconnected promoted
    input). This fixture lets the auto-share tests treat the
    paraboloid as a toy producer without standing up OAS/OCP.
    """
    original = getattr(build_paraboloid, "contract", None)
    build_paraboloid.contract = FactoryContract(
        produces={"x": VarSpec(default=0.0, description="shared x")},
        consumes={"y": VarSpec(default=0.0)},
    )
    try:
        yield
    finally:
        if original is None:
            del build_paraboloid.contract
        else:
            build_paraboloid.contract = original


def _two_paraboloid_plan(**extra) -> dict:
    plan = {
        "metadata": {"id": "auto", "name": "auto", "version": 1},
        "components": [
            {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
            {"id": "b", "type": "paraboloid/Paraboloid", "config": {}},
        ],
    }
    plan.update(extra)
    return plan


class TestAutoDerivation:

    def test_auto_hoists_overlapping_produces(
        self, paraboloid_with_shared_contract,
    ):
        from hangar.omd.materializer import materialize
        plan = _two_paraboloid_plan(composition_policy="auto")
        prob, meta = materialize(plan)
        try:
            # The shared_ivc subsystem appears because `x` is declared
            # produced by both a and b.
            assert prob.model._get_subsystem("shared_ivc") is not None
            assert meta["shared_var_paths"]["x"] == "x"
            prob.set_val("a.y", -4.0)
            prob.set_val("b.y", -4.0)
            prob.set_val("x", 3.0)
            prob.run_model()
            # Both consumers see x=3, y=-4; paraboloid yields -15.
            assert abs(float(prob.get_val("a.f_xy")) - (-15.0)) < 1e-8
            assert abs(float(prob.get_val("b.f_xy")) - (-15.0)) < 1e-8
        finally:
            prob.cleanup()

    def test_explicit_policy_matches_fix2(
        self, paraboloid_with_shared_contract,
    ):
        from hangar.omd.materializer import materialize
        # Default (composition_policy unset == "explicit"): no auto
        # shared_ivc even though both components declare `x`.
        plan = _two_paraboloid_plan()
        prob, meta = materialize(plan)
        try:
            assert prob.model._get_subsystem("shared_ivc") is None
            assert "x" not in meta.get("shared_var_paths", {})
        finally:
            prob.cleanup()

    def test_no_auto_share_blocks_hoist(
        self, paraboloid_with_shared_contract,
    ):
        from hangar.omd.materializer import materialize
        plan = _two_paraboloid_plan(
            composition_policy="auto",
            no_auto_share=["x"],
        )
        prob, meta = materialize(plan)
        try:
            assert prob.model._get_subsystem("shared_ivc") is None
        finally:
            prob.cleanup()

    def test_user_shared_wins(self, paraboloid_with_shared_contract):
        from hangar.omd.materializer import materialize
        # User declared the same name explicitly -- auto-derive must
        # not double-register it.
        plan = _two_paraboloid_plan(
            composition_policy="auto",
            shared_vars=[
                {"name": "x", "value": 7.0, "consumers": ["a", "b"]},
            ],
        )
        prob, meta = materialize(plan)
        try:
            assert prob.model._get_subsystem("shared_ivc") is not None
            prob.set_val("a.y", 0.0)
            prob.set_val("b.y", 0.0)
            prob.run_model()
            # User-declared value=7 survives.
            # f(7, 0) = 16 + 0 + 16 - 3 = 29
            assert abs(float(prob.get_val("a.f_xy")) - 29.0) < 1e-8
            assert abs(float(prob.get_val("b.f_xy")) - 29.0) < 1e-8
        finally:
            prob.cleanup()

    def test_auto_plus_user_declared_coexist(
        self, paraboloid_with_shared_contract, monkeypatch,
    ):
        """Mix: user shares `y` explicitly; `x` is auto-hoisted."""
        from hangar.omd.materializer import materialize
        # Extend the fixture contract to also declare y as produced so
        # auto-hoisting has two overlaps (x + y).
        build_paraboloid.contract = FactoryContract(
            produces={
                "x": VarSpec(default=0.0),
                "y": VarSpec(default=0.0),
            },
            consumes={},
        )
        plan = _two_paraboloid_plan(
            composition_policy="auto",
            shared_vars=[
                {"name": "y", "value": -4.0, "consumers": ["a", "b"]},
            ],
        )
        prob, meta = materialize(plan)
        try:
            paths = meta["shared_var_paths"]
            assert "x" in paths and "y" in paths
            prob.set_val("x", 3.0)
            prob.run_model()
            assert abs(float(prob.get_val("a.f_xy")) - (-15.0)) < 1e-8
            assert abs(float(prob.get_val("b.f_xy")) - (-15.0)) < 1e-8
        finally:
            prob.cleanup()


class TestAdvisoryValidator:

    def test_findings_enumerate_auto_names(
        self, paraboloid_with_shared_contract,
    ):
        from hangar.omd.plan_validate import validate_factory_contracts
        plan = _two_paraboloid_plan(composition_policy="auto")
        findings = validate_factory_contracts(plan)
        assert any("Auto-shared 'x'" in f.message for f in findings)

    def test_findings_empty_when_policy_explicit(
        self, paraboloid_with_shared_contract,
    ):
        from hangar.omd.plan_validate import validate_factory_contracts
        plan = _two_paraboloid_plan()
        findings = validate_factory_contracts(plan)
        assert findings == []

    def test_no_auto_share_typo_flagged(
        self, paraboloid_with_shared_contract,
    ):
        from hangar.omd.plan_validate import validate_factory_contracts
        plan = _two_paraboloid_plan(
            composition_policy="auto",
            no_auto_share=["not_a_real_produced_name"],
        )
        findings = validate_factory_contracts(plan)
        typo_findings = [
            f for f in findings if "no_auto_share" in f.path
        ]
        assert typo_findings, "expected a finding for the bogus entry"
        assert "not_a_real_produced_name" in typo_findings[0].message


class TestSchema:

    def test_composition_policy_enum(self):
        from hangar.omd.plan_schema import validate_plan
        plan = {
            "metadata": {"id": "t", "name": "t", "version": 1},
            "components": [
                {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
            ],
            "composition_policy": "auto",
        }
        assert validate_plan(plan) == []

        plan["composition_policy"] = "invalid"
        errors = validate_plan(plan)
        assert errors

    def test_no_auto_share_schema(self):
        from hangar.omd.plan_schema import validate_plan
        plan = {
            "metadata": {"id": "t", "name": "t", "version": 1},
            "components": [
                {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
            ],
            "composition_policy": "auto",
            "no_auto_share": ["ac|geom|wing|AR"],
        }
        assert validate_plan(plan) == []


class TestDVResolution:

    def test_auto_shared_name_resolves_in_var_paths_validation(
        self, paraboloid_with_shared_contract,
    ):
        """A DV whose name matches an auto-hoisted variable must pass
        var-path validation without the user having to list it in
        shared_vars explicitly.
        """
        from hangar.omd.plan_validate import validate_var_paths
        plan = _two_paraboloid_plan(
            composition_policy="auto",
            design_variables=[
                {"name": "x", "lower": -50.0, "upper": 50.0},
            ],
            objective={"name": "a.f_xy"},
        )
        findings = validate_var_paths(plan)
        # `x` resolves via auto-derived shared_ivc, not an unknown name.
        assert not any(
            f.path.startswith("design_variables") for f in findings
        )
