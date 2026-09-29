"""OCP aircraft overrides and plan-level starting values.

Covers the four ways a blind agent failed to pose the Brelje 2018a
hybrid King Air: ``aircraft_data`` next to a template was dropped,
``operating_points`` aircraft keys were ignored, the structural weight
factor had no config surface, and ``initial_values`` were skipped
silently (unknown names) or not applied at all (plans without an
objective). Each of those now either takes effect or is an error.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from hangar.omd.factories.ocp.aircraft_overrides import (
    active_fields,
    collect_overrides,
    flatten_aircraft_data,
    resolve_aircraft,
)
from hangar.omd.op_points import normalize_operating_points
from hangar.omd.plan_validate import validate_plan_semantic
from hangar.sdk.errors import UserInputError

HYBRID = {"aircraft_template": "kingair", "architecture": "twin_series_hybrid"}


def _leaf(data: dict, path: str) -> dict:
    node = data
    for part in path.split("|"):
        node = node[part]
    return node


# ---------------------------------------------------------------------------
# aircraft_overrides (no OpenConcept needed)
# ---------------------------------------------------------------------------


def test_flatten_accepts_nested_and_flat_keys():
    flat = flatten_aircraft_data({
        "ac": {"weights": {"MTOW": {"value": 5000, "units": "kg"}}},
        "ac|propulsion|propeller|diameter": 2.2,
    })
    assert flat == {
        "ac|weights|MTOW": {"value": 5000, "units": "kg"},
        "ac|propulsion|propeller|diameter": {"value": 2.2, "units": None},
    }


def test_aircraft_data_merges_over_template_with_unit_conversion():
    cfg = dict(HYBRID, aircraft_data={
        "ac": {"propulsion": {"propeller": {"diameter": {"value": 220.0, "units": "cm"}}}},
    })
    resolved = resolve_aircraft(cfg, {}, "twin_series_hybrid")
    diam = _leaf(resolved.data, "ac|propulsion|propeller|diameter")
    assert diam["units"] == "m" and diam["value"] == pytest.approx(2.2)
    # the rest of the template survives the merge
    assert _leaf(resolved.data, "ac|weights|MTOW")["value"] == 4581


def test_operating_point_overrides_and_fudge_alias():
    op = normalize_operating_points({
        "ac|propulsion|engine|rating": {"value": 833.1, "units": "kW"},
        "ac|weights|structural_fudge": 2.0,
    })
    # the unit tag survives normalization for the factory to convert
    assert op["ac|propulsion|engine|rating"] == {"value": 833.1, "units": "kW"}
    resolved = resolve_aircraft(dict(HYBRID), op, "twin_series_hybrid")
    rating = _leaf(resolved.data, "ac|propulsion|engine|rating")
    assert rating["units"] == "hp" and rating["value"] == pytest.approx(1117.2, rel=1e-4)
    assert resolved.structural_fudge == 2.0
    assert resolved.applied["structural_fudge"]["value"] == 2.0


def test_battery_specific_energy_override_routes_to_propulsion():
    resolved = resolve_aircraft(dict(HYBRID), {
        "ac|propulsion|battery|specific_energy": {"value": 1.62, "units": "MJ/kg"},
    }, "twin_series_hybrid")
    assert resolved.battery_specific_energy == pytest.approx(450.0)


@pytest.mark.parametrize("cfg, op, fragment, suggestion", [
    # typo in a template path -> suggestion
    (dict(HYBRID, aircraft_data={"ac|propulsion|engine|ratng": 1.0}), {},
     "not an aircraft-data field", "ac|propulsion|engine|rating"),
    # OEW is computed on a propeller architecture
    (dict(HYBRID), {"ac|weights|OEW": 3000.0}, "not read by architecture", None),
    # hybrid-only field on a pure turboprop
    ({"aircraft_template": "kingair", "architecture": "twin_turboprop"},
     {"ac|weights|W_battery": 300.0}, "not read by architecture", None),
    # the same fudge twice with different values
    (dict(HYBRID, structural_fudge=1.8), {"structural_fudge": 2.0},
     "more than once", None),
    # a propulsion slot replaces the weight model the fudge scales
    (dict(HYBRID, structural_fudge=2.0,
          slots={"propulsion": {"provider": "pyc/surrogate"}}), {},
     "has no effect", None),
])
def test_override_problems(cfg, op, fragment, suggestion):
    arch = cfg["architecture"]
    *_, problems = collect_overrides(cfg, op, arch)
    assert problems and fragment in problems[0].message
    if suggestion:
        assert suggestion in problems[0].suggestions
    with pytest.raises(UserInputError, match=fragment):
        resolve_aircraft(cfg, op, arch)


def test_active_fields_follow_architecture():
    hybrid = active_fields("twin_series_hybrid")
    assert "ac|weights|W_battery" in hybrid and "ac|weights|OEW" not in hybrid
    assert "ac|weights|OEW" in active_fields("twin_turbofan")  # CFM56 passthrough


def test_validate_flags_ignored_ocp_operating_points():
    plan = {
        "metadata": {"id": "p", "name": "p", "version": 1},
        "components": [{"id": "m", "type": "ocp/FullMission", "config": dict(HYBRID)}],
        "operating_points": {"mission_range_NM": 600, "ac|weights|OEW": 1.0},
    }
    paths = {f.path for f in validate_plan_semantic(plan)}
    assert "operating_points.mission_range_NM" in paths
    assert "operating_points.ac|weights|OEW" in paths

    # composite plans share operating points with other factories: only
    # the aircraft-key check applies there
    plan["components"].append({"id": "w", "type": "oas/AeroPoint", "config": {}})
    plan["operating_points"] = {"alpha": 2.0}
    assert not [f for f in validate_plan_semantic(plan)
                if f.path.startswith("operating_points")]


# ---------------------------------------------------------------------------
# materializer integration (builds the King Air hybrid mission)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_plan():
    pytest.importorskip("openconcept")
    return {
        "metadata": {"id": "ocp-overrides", "name": "overrides", "version": 1},
        "components": [{
            "id": "mission", "type": "ocp/FullMission",
            "config": dict(HYBRID, num_nodes=3,
                           mission_params={"mission_range_NM": 500.0,
                                           "payload_lb": 1000.0}),
        }],
        "operating_points": {},
    }


def _materialize(plan):
    from hangar.omd.materializer import materialize

    return materialize(plan, recording_level="minimal")


def _scalar(val) -> float:
    # staged (pre-run) values come back as 0-d arrays
    return float(np.atleast_1d(val).flat[0])


def _fudges(prob) -> dict[str, float]:
    outs = prob.model.get_io_metadata(iotypes=("output",), return_rel_names=False)
    return {k: _scalar(prob.get_val(k)) for k in outs
            if k.endswith("OEW.const.structural_fudge")}


def test_structural_fudge_sets_every_phase(base_plan):
    plan = copy.deepcopy(base_plan)
    plan["components"][0]["config"]["structural_fudge"] = 2.0
    prob, meta = _materialize(plan)
    fudges = _fudges(prob)
    # takeoff phases, climb/cruise/descent and the engine-out climb
    assert len(fudges) == 8 and set(fudges.values()) == {2.0}
    assert meta["aircraft_overrides"]["structural_fudge"]["value"] == 2.0


def test_initial_values_apply_without_an_objective(base_plan):
    plan = copy.deepcopy(base_plan)
    plan["initial_values"] = [
        {"name": "ac|propulsion|engine|rating", "val": 1117.2, "units": "hp"},
    ]
    prob, meta = _materialize(plan)
    assert _scalar(prob.get_val("ac|propulsion|engine|rating", units="hp")) \
        == pytest.approx(1117.2)
    assert meta["applied_plan_values"][0]["name"] == "ac|propulsion|engine|rating"


def test_dv_initial_wins_over_initial_values(base_plan):
    plan = copy.deepcopy(base_plan)
    plan["initial_values"] = [{"name": "ac|weights|W_battery", "val": 100.0, "units": "kg"}]
    plan["design_variables"] = [{"name": "ac|weights|W_battery", "lower": 20.0,
                                 "upper": 2250.0, "units": "kg", "initial": 700.0}]
    plan["objective"] = {"name": "mixed_objective"}
    prob, _ = _materialize(plan)
    assert _scalar(prob.get_val("ac|weights|W_battery", units="kg")) == 700.0


@pytest.mark.parametrize("name, fragment", [
    ("ac|weights|structural_fudge", "config.structural_fudge"),
    ("analysis.cruise.acmodel.OEW.const.structral_fudge", "cruise.OEW.structural_fudge"),
    ("cruise.OEW", "computed by the model"),
])
def test_initial_values_that_cannot_take_effect_raise(base_plan, name, fragment):
    plan = copy.deepcopy(base_plan)
    plan["initial_values"] = [{"name": name, "val": 2.0}]
    with pytest.raises(UserInputError, match="nothing was run") as exc:
        _materialize(plan)
    assert fragment in str(exc.value)


def test_input_fed_by_independent_variable_is_redirected(base_plan):
    plan = copy.deepcopy(base_plan)
    # `cruise.structural_fudge` is the weight model's input, fed by its
    # own constant; setting the input alone would be overwritten
    plan["initial_values"] = [{"name": "cruise.structural_fudge", "val": 2.0}]
    prob, meta = _materialize(plan)
    assert meta["applied_plan_values"][0]["target"] == "cruise.OEW.structural_fudge"
    prob.run_model()
    fudges = _fudges(prob)
    assert fudges["analysis.cruise.acmodel.OEW.const.structural_fudge"] == 2.0
    assert np.isfinite(_scalar(prob.get_val("cruise.OEW")))
