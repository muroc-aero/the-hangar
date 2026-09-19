"""Unit tests for the native avy/Sizing factory (build only, no driver run).

Building the AviaryGroup takes a couple of seconds (deck load, phase
preprocessing, dymos phases) but runs no optimization; the full sizing
lives in the parity suites (packages/omd/examples/tests/). Everything here
needs aviary in the venv (bash scripts/dev-setup.sh).
"""

from __future__ import annotations

import pytest

pytest.importorskip("aviary")

from hangar.omd.factories.avy import build_avy_sizing  # noqa: E402
from hangar.omd.registry import get_factory  # noqa: E402

DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"


@pytest.fixture(scope="module")
def built():
    prob, meta = build_avy_sizing(
        {"deck": DECK, "target_range_nm": 1906.0, "max_iter": 7}, {}
    )
    return prob, meta


def test_factory_registered():
    factory = get_factory("avy/Sizing")
    assert factory is build_avy_sizing
    # run.py reads this before materialization: mode=optimize needs no
    # plan-level DVs/objective for a self-optimizing component.
    assert factory.self_optimizing is True


def test_build_requires_deck():
    with pytest.raises(ValueError, match="deck"):
        build_avy_sizing({}, {})


def test_group_is_native_subsystem_with_promoted_names(built):
    prob, meta = built
    from aviary.core.aviary_group import AviaryGroup

    grp = prob.model._get_subsystem("aviary")
    assert isinstance(grp, AviaryGroup)
    assert meta["component_family"] == "avy"
    assert meta["point_name"] == "aviary"
    # Aviary's names are the component namespace
    assert meta["var_paths"]["gross_mass_lbm"] == "mission:gross_mass"
    assert meta["var_paths"]["wing_mass_lbm"] == "aircraft:wing:mass"
    assert set(meta["avy_outputs"]) == {
        "gross_mass_lbm", "total_fuel_mass_lbm", "operating_mass_lbm",
        "wing_mass_lbm", "range_nmi", "final_time_min",
    }


def test_declares_its_own_optimization(built):
    prob, meta = built
    grp = prob.model._get_subsystem("aviary")
    # DVs / objective live inside the group; the materializer's driver
    # collects them (self_optimizing + driver_defaults hooks).
    dvs = getattr(grp, "_static_design_vars", None) or grp._design_vars
    resps = getattr(grp, "_static_responses", None) or grp._responses
    assert dvs, "Aviary DVs declared on the group"
    assert resps, "Aviary objective/constraints declared on the group"
    assert meta["self_optimizing"] is True
    assert meta["requires_driver"] is True
    assert meta["driver_defaults"] == {
        "type": "SLSQP", "options": {"maxiter": 7, "tol": 1e-9},
    }
    assert meta["driver_coloring"] is True


def test_publishes_model_options_and_post_setup(built):
    prob, meta = built
    # Aviary options (engine count, mass/mission methods, ...) travel by
    # OpenMDAO model_options keyed on the group path; composites re-key.
    assert "aviary.*" in meta["model_options"]
    assert meta["model_options"]["aviary.*"]
    assert len(meta["post_setup"]) == 1
    assert meta["setup_warning_filters"]


def test_deck_override_becomes_boundary_input():
    """A deck value for a computed variable is Aviary's override: the
    FLOPS output is renamed away and the promoted name is an input a plan
    connection can drive (the oas_avy_wing_mass seam)."""
    prob, _meta = build_avy_sizing(
        {
            "deck": DECK,
            "overrides": {"aircraft:wing:mass": [15000.0, "lbm"]},
            "max_iter": 1,
        },
        {},
    )
    prob.setup()
    prob.final_setup()
    inputs = {
        meta["prom_name"]
        for _abs, meta in prob.model.list_inputs(out_stream=None, prom_name=True)
    }
    assert "aircraft:wing:mass" in inputs
    src = prob.model.get_source("aircraft:wing:mass")
    assert "_auto_ivc" in src, src


def test_operating_point_overrides_target_range():
    _prob, meta = build_avy_sizing(
        {"deck": DECK, "target_range_nm": 1000.0, "max_iter": 1},
        {"target_range_nm": 1234.0},
    )
    grp = _prob.model._get_subsystem("aviary")
    assert grp.post_mission_info["target_range"][0] == 1234.0


def test_external_subsystems_shape_validated():
    with pytest.raises(ValueError, match="external_subsystems"):
        build_avy_sizing({"deck": DECK, "external_subsystems": ["oops"]}, {})


def test_unknown_external_subsystem_rejected():
    with pytest.raises(ValueError, match="Unknown external subsystem"):
        build_avy_sizing(
            {"deck": DECK, "external_subsystems": [{"name": "nope"}]}, {}
        )


def test_objective_validated():
    with pytest.raises(ValueError, match="objective"):
        build_avy_sizing({"deck": DECK, "objective": "range"}, {})


def test_only_slsqp_under_omd():
    with pytest.raises(ValueError, match="SLSQP|pyoptsparse"):
        build_avy_sizing({"deck": DECK, "optimizer": "IPOPT"}, {})


@pytest.mark.parametrize("key", ["override_inputs", "avy_python", "run_timeout_s"])
def test_legacy_subprocess_keys_rejected_with_migration_hint(key):
    with pytest.raises(ValueError, match=key):
        build_avy_sizing({"deck": DECK, key: {}}, {})


def test_bad_phase_info_module():
    with pytest.raises(ValueError, match="phase_info_module"):
        build_avy_sizing({"deck": DECK, "phase_info_module": "no.such.module"}, {})
