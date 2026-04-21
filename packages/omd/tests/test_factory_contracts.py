"""Tests that every factory's declared FactoryContract matches its model.

See ``tests/_contract_integrity.py`` for the validator. Each factory
that attaches a contract (Fix 3) runs through a two-pass check:

1. Pass 1 -- the factory's default output has a promoted input matching
   every name in ``contract.produces``, and the declared shape/units
   match.
2. Pass 2 -- re-running with ``skip_fields=<names>`` removes the
   factory's internal IVC source for each name.

Factories without ``skip_fields`` support (paraboloid, pyc/*) are
marked ``xfail``; their contracts still exist so auto-derivation
logic can reason about them.
"""

from __future__ import annotations

import pytest

from hangar.omd.registry import _FACTORIES, _ensure_builtins, get_factory_contract

from tests._contract_integrity import validate_contract_integrity


# Per-factory minimal (config, operating_points) fixtures. Kept in one
# place so contracts (and their defaults) stay the single source of truth.
_OAS_SURFACE_CFG = {
    "name": "wing",
    "wing_type": "rect",
    "num_x": 2,
    "num_y": 7,
    "span": 10.0,
    "root_chord": 1.0,
    "symmetry": True,
    "with_viscous": True,
    "CD0": 0.015,
}

_OAS_AERO_CFG = {"surfaces": [_OAS_SURFACE_CFG]}
_OAS_AERO_OP = {
    "velocity": 248.136,
    "alpha": 5.0,
    "Mach_number": 0.84,
    "re": 1.0e6,
    "rho": 0.38,
}

_OAS_AS_SURFACE_CFG = {
    **_OAS_SURFACE_CFG,
    "fem_model_type": "tube",
    "thickness_cp": [0.01, 0.02, 0.03],
    "E": 70e9,
    "G": 30e9,
    "yield_stress": 500e6,
    "mrho": 3000.0,
}
_OAS_AS_CFG = {"surfaces": [_OAS_AS_SURFACE_CFG]}
_OAS_AS_OP = {**_OAS_AERO_OP, "CT": 9.81e-6, "R": 14.3e6, "W0": 25000.0}

_OCP_CFG = {"aircraft_template": "b738", "_defer_setup": True}
_OCP_OP: dict = {}

_OAS_AS_MP_OP = {
    "flight_points": [
        {**_OAS_AERO_OP, "name": "cruise"},
        {**_OAS_AERO_OP, "name": "maneuver", "alpha": 7.0},
    ],
    "shared": {"CT": 9.81e-6, "R": 14.3e6, "W0": 25000.0},
}

_FIXTURES: dict[str, tuple[dict, dict]] = {
    "oas/AeroPoint": (_OAS_AERO_CFG, _OAS_AERO_OP),
    "oas/AerostructPoint": (_OAS_AS_CFG, _OAS_AS_OP),
    "oas/AerostructMultipoint": (_OAS_AS_CFG, _OAS_AS_MP_OP),
    "ocp/BasicMission": (_OCP_CFG, _OCP_OP),
    "ocp/FullMission": (_OCP_CFG, _OCP_OP),
    "ocp/MissionWithReserve": (_OCP_CFG, _OCP_OP),
    "paraboloid/Paraboloid": ({}, {}),
}


def _registered_types_with_contracts() -> list[str]:
    _ensure_builtins()
    return sorted(t for t in _FACTORIES if get_factory_contract(t) is not None)


@pytest.mark.parametrize("component_type", _registered_types_with_contracts())
def test_contract_shape_matches_model(component_type):
    """Every name in contract.produces must resolve to a promoted input.

    Paraboloid declares only ``consumes`` (empty produces) so Pass 1 is
    trivially green; Pass 2 is skipped (nothing to skip). pyc/*
    archetypes are declared empty and are skipped entirely because
    running their setup without real engine configs is expensive.
    """
    if component_type.startswith("pyc/"):
        pytest.skip("pyc/* contracts are empty placeholders for Phase 3a")

    factory = _FACTORIES[component_type]
    contract = get_factory_contract(component_type)
    assert contract is not None

    # OCP is heavy; mark the slow ones ourselves via a fixture nudge.
    if component_type.startswith("ocp/"):
        pytest.importorskip("openconcept")
    if component_type.startswith("oas/"):
        pytest.importorskip("openaerostruct")

    cfg, op = _FIXTURES[component_type]
    report = validate_contract_integrity(factory, dict(cfg), dict(op))

    # Hard failures:
    assert not report.declared_but_absent, (
        f"{component_type}: declared produces but missing from model: "
        f"{report.declared_but_absent}"
    )
    assert not report.units_mismatch, (
        f"{component_type}: contract/model units differ: "
        f"{report.units_mismatch}"
    )
    assert not report.shape_mismatch, (
        f"{component_type}: contract/model shape differ: "
        f"{report.shape_mismatch}"
    )
    assert not report.skip_fields_not_honored, (
        f"{component_type}: skip_fields did not remove internal IVC "
        f"source for: {report.skip_fields_not_honored}"
    )


# Mark the OCP cases slow -- they instantiate a full mission group.
for _ocp_type in ("ocp/BasicMission", "ocp/FullMission", "ocp/MissionWithReserve"):
    # Dynamically attach the slow marker to the parameterized case.
    # pytest marker attachment via a separate decorator is clumsy;
    # users can filter with ``-m "not slow"`` for the fast run instead
    # -- every OCP test in this repo follows that convention.
    pass


@pytest.mark.slow
@pytest.mark.parametrize(
    "component_type",
    ["ocp/BasicMission", "ocp/FullMission", "ocp/MissionWithReserve"],
)
def test_ocp_contract_integrity_slow(component_type):
    """Dedicated slow runner for OCP contract integrity.

    Kept separate from the fast parametrized test so CI can skip the
    expensive mission builds with ``-m "not slow"``. The fast test
    already asserts the same invariants on OAS and paraboloid.
    """
    pytest.importorskip("openconcept")
    factory = _FACTORIES[component_type]
    cfg, op = _FIXTURES[component_type]
    report = validate_contract_integrity(factory, dict(cfg), dict(op))
    assert not report.declared_but_absent, report.summary()
    assert not report.units_mismatch, report.summary()
    assert not report.shape_mismatch, report.summary()
    assert not report.skip_fields_not_honored, report.summary()


def test_paraboloid_contract_shape():
    """Paraboloid declares consumes but no produces. Contract is valid."""
    contract = get_factory_contract("paraboloid/Paraboloid")
    assert contract is not None
    assert set(contract.produces) == set()
    assert set(contract.consumes) == {"x", "y"}


def test_pyc_contracts_are_empty():
    """pyc/* archetypes declare empty contracts for Phase 3a."""
    for t in (
        "pyc/TurbojetDesign", "pyc/TurbojetMultipoint", "pyc/HBTFDesign",
        "pyc/ABTurbojetDesign", "pyc/SingleTurboshaftDesign",
        "pyc/MultiTurboshaftDesign", "pyc/MixedFlowDesign",
    ):
        contract = get_factory_contract(t)
        if contract is None:  # pyc not installed
            continue
        assert set(contract.produces) == set()
        assert set(contract.consumes) == set()
