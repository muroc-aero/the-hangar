"""Unit tests for hangar.omd.plan_mutate primitives."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hangar.omd import plan_mutate as pm
from hangar.omd.plan_schema import validate_partial
from hangar.sdk.errors import UserInputError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plan_dir(tmp_path: Path) -> Path:
    d = tmp_path / "plan"
    pm.init_plan(d, plan_id="demo", name="Demo study")
    return d


_WING_CFG = {
    "surfaces": [{
        "name": "wing",
        "wing_type": "rect",
        "num_x": 2,
        "num_y": 5,
        "span": 10.0,
        "root_chord": 1.0,
        "symmetry": True,
        "fem_model_type": "tube",
        "E": 7.0e10,
        "G": 3.0e10,
        "yield_stress": 5.0e8,
        "mrho": 3000.0,
    }],
}


def _add_wing(plan_dir: Path) -> None:
    pm.add_component(
        plan_dir,
        comp_id="wing",
        comp_type="oas/AerostructPoint",
        config=_WING_CFG,
    )


# ---------------------------------------------------------------------------
# init_plan
# ---------------------------------------------------------------------------

def test_init_plan_scaffolds_metadata(tmp_path: Path):
    d = tmp_path / "new"
    pm.init_plan(d, plan_id="p1", name="Plan one", description="Hello")

    data = yaml.safe_load((d / "metadata.yaml").read_text())
    assert data == {
        "id": "p1",
        "name": "Plan one",
        "version": 1,
        "description": "Hello",
    }


def test_init_plan_rejects_empty_id(tmp_path: Path):
    with pytest.raises(UserInputError):
        pm.init_plan(tmp_path / "x", plan_id="", name="Nope")


def test_require_plan_dir_errors_when_uninitialized(tmp_path: Path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(UserInputError):
        pm.add_component(
            d, comp_id="wing", comp_type="oas/AerostructPoint",
            config=_WING_CFG,
        )


# ---------------------------------------------------------------------------
# add_component
# ---------------------------------------------------------------------------

def test_add_component_writes_bare_mapping(plan_dir: Path):
    _add_wing(plan_dir)
    data = yaml.safe_load((plan_dir / "components" / "wing.yaml").read_text())
    assert data["id"] == "wing"
    assert data["type"] == "oas/AerostructPoint"
    assert "config" in data


def test_add_component_duplicate_id_raises(plan_dir: Path):
    _add_wing(plan_dir)
    with pytest.raises(UserInputError, match="already exists"):
        _add_wing(plan_dir)


def test_add_component_replace_overwrites(plan_dir: Path):
    _add_wing(plan_dir)
    new_cfg = {**_WING_CFG, "extra": "field"}
    pm.add_component(
        plan_dir, comp_id="wing", comp_type="oas/AerostructPoint",
        config=new_cfg, replace=True,
    )
    data = yaml.safe_load((plan_dir / "components" / "wing.yaml").read_text())
    assert data["config"]["extra"] == "field"


# ---------------------------------------------------------------------------
# add_requirement
# ---------------------------------------------------------------------------

def test_add_requirement_appends(plan_dir: Path):
    pm.add_requirement(
        plan_dir,
        req={"id": "R1", "text": "Minimize mass"},
    )
    pm.add_requirement(
        plan_dir,
        req={"id": "R2", "text": "No failure"},
    )
    data = yaml.safe_load((plan_dir / "requirements.yaml").read_text())
    assert [r["id"] for r in data] == ["R1", "R2"]


def test_add_requirement_duplicate_raises(plan_dir: Path):
    pm.add_requirement(plan_dir, req={"id": "R1", "text": "x"})
    with pytest.raises(UserInputError, match="already exists"):
        pm.add_requirement(plan_dir, req={"id": "R1", "text": "y"})


def test_add_requirement_replace_flag(plan_dir: Path):
    pm.add_requirement(plan_dir, req={"id": "R1", "text": "original"})
    pm.add_requirement(
        plan_dir,
        req={"id": "R1", "text": "updated"},
        replace=True,
    )
    data = yaml.safe_load((plan_dir / "requirements.yaml").read_text())
    assert data[0]["text"] == "updated"


# ---------------------------------------------------------------------------
# add_dv / set_objective (DV name validation)
# ---------------------------------------------------------------------------

def test_add_dv_validates_against_var_paths(plan_dir: Path):
    _add_wing(plan_dir)
    pm.add_dv(plan_dir, name="twist_cp", lower=-10, upper=15)
    pm.add_dv(plan_dir, name="wing.thickness_cp", lower=0.003, upper=0.1)
    opt = yaml.safe_load((plan_dir / "optimization.yaml").read_text())
    names = [d["name"] for d in opt["design_variables"]]
    assert names == ["twist_cp", "wing.thickness_cp"]


def test_add_dv_unknown_name_lists_allowed(plan_dir: Path):
    _add_wing(plan_dir)
    with pytest.raises(UserInputError, match="twist_cp"):
        pm.add_dv(plan_dir, name="bogus_dv", lower=0, upper=1)


def test_add_dv_lower_must_be_less_than_upper(plan_dir: Path):
    _add_wing(plan_dir)
    with pytest.raises(UserInputError, match="lower"):
        pm.add_dv(plan_dir, name="twist_cp", lower=5, upper=5)


def test_add_dv_without_components_skips_strict_validation(plan_dir: Path):
    # No components declared → no strict-name validation. The partial
    # schema still accepts the optimization file.
    pm.add_dv(plan_dir, name="anything_goes", lower=-1, upper=1)


def test_set_objective_validates_var_paths(plan_dir: Path):
    _add_wing(plan_dir)
    pm.set_objective(plan_dir, name="structural_mass")
    with pytest.raises(UserInputError, match="unknown objective"):
        pm.set_objective(plan_dir, name="not_an_output")


def test_set_objective_replaces_existing(plan_dir: Path):
    _add_wing(plan_dir)
    pm.set_objective(plan_dir, name="structural_mass")
    pm.set_objective(plan_dir, name="fuelburn", scaler=0.1)
    opt = yaml.safe_load((plan_dir / "optimization.yaml").read_text())
    assert opt["objective"] == {"name": "fuelburn", "scaler": 0.1}


# ---------------------------------------------------------------------------
# add_decision (hand-authored)
# ---------------------------------------------------------------------------

def test_add_decision_offlist_stage_is_not_rejected(plan_dir: Path):
    """Library does not enforce stage membership; CLI emits a warning."""
    pm.add_decision(
        plan_dir,
        decision={"decision": "x", "stage": "invented_stage"},
    )
    data = yaml.safe_load((plan_dir / "decisions.yaml").read_text())
    assert data[0]["stage"] == "invented_stage"


def test_add_decision_auto_id(plan_dir: Path):
    pm.add_decision(plan_dir, decision={"decision": "x", "stage": "dv_setup"})
    pm.add_decision(plan_dir, decision={"decision": "y", "stage": "dv_setup"})
    data = yaml.safe_load((plan_dir / "decisions.yaml").read_text())
    assert [d["id"] for d in data] == ["dec-auto-1", "dec-auto-2"]


# ---------------------------------------------------------------------------
# Rationale capture hook
# ---------------------------------------------------------------------------

def test_rationale_appended_to_decisions_yaml(plan_dir: Path):
    _add_wing(plan_dir)
    pm.add_dv(
        plan_dir, name="twist_cp", lower=-10, upper=15,
        rationale="Conservative envelope",
    )
    data = yaml.safe_load((plan_dir / "decisions.yaml").read_text())
    # One captured by add_component (no rationale: none) and one by add_dv
    # (with rationale). add_component without rationale writes nothing.
    assert len(data) == 1
    entry = data[0]
    assert entry["stage"] == "dv_setup"
    assert entry["rationale"] == "Conservative envelope"
    assert entry["element_path"] == "design_variables[twist_cp]"
    assert entry["id"].startswith("dec-auto-")


def test_rationale_none_skips_capture(plan_dir: Path):
    _add_wing(plan_dir)
    pm.add_dv(plan_dir, name="twist_cp", lower=-1, upper=1, rationale=None)
    assert not (plan_dir / "decisions.yaml").exists()


def test_rationale_stage_matches_primitive(plan_dir: Path):
    _add_wing(plan_dir)
    pm.set_objective(plan_dir, name="structural_mass", rationale="Goal")
    pm.set_solver(
        plan_dir, nonlinear="NewtonSolver", rationale="Standard choice",
    )
    pm.set_operating_point(
        plan_dir,
        fields={
            "velocity": 248.0,
            "alpha": 5.0,
            "Mach_number": 0.84,
            "re": 1.0e6,
            "rho": 0.38,
        },
        rationale="Cruise design point",
    )
    data = yaml.safe_load((plan_dir / "decisions.yaml").read_text())
    stages = [d["stage"] for d in data]
    assert stages == [
        "objective_selection",
        "solver_selection",
        "operating_point_selection",
    ]


# ---------------------------------------------------------------------------
# set_operating_point
# ---------------------------------------------------------------------------

def test_set_operating_point_merges_fields(plan_dir: Path):
    pm.set_operating_point(plan_dir, fields={"Mach_number": 0.84, "alpha": 5.0})
    pm.set_operating_point(plan_dir, fields={"alpha": 3.0, "rho": 0.38})
    data = yaml.safe_load((plan_dir / "operating_points.yaml").read_text())
    assert data == {"Mach_number": 0.84, "alpha": 3.0, "rho": 0.38}


# ---------------------------------------------------------------------------
# set_solver
# ---------------------------------------------------------------------------

def test_set_solver_writes_both_legs(plan_dir: Path):
    pm.set_solver(
        plan_dir,
        nonlinear="NewtonSolver",
        linear="DirectSolver",
        nonlinear_options={"maxiter": 20},
    )
    data = yaml.safe_load((plan_dir / "solvers.yaml").read_text())
    assert data["nonlinear"] == {
        "type": "NewtonSolver",
        "options": {"maxiter": 20},
    }
    assert data["linear"] == {"type": "DirectSolver"}


def test_set_solver_requires_at_least_one_leg(plan_dir: Path):
    with pytest.raises(UserInputError, match="at least one"):
        pm.set_solver(plan_dir)


# ---------------------------------------------------------------------------
# set_analysis_strategy
# ---------------------------------------------------------------------------

def test_set_analysis_strategy_phases_3(plan_dir: Path):
    pm.set_analysis_strategy(plan_dir, phases=3)
    data = yaml.safe_load((plan_dir / "analysis_plan.yaml").read_text())
    ids = [p["id"] for p in data["phases"]]
    assert ids == ["p1", "p2", "p3"]
    assert data["phases"][0]["depends_on"] == []
    assert data["phases"][1]["depends_on"] == ["p1"]
    assert data["phases"][2]["depends_on"] == ["p2"]


def test_set_analysis_strategy_phases_must_be_positive(plan_dir: Path):
    with pytest.raises(UserInputError):
        pm.set_analysis_strategy(plan_dir, phases=0)


# ---------------------------------------------------------------------------
# load_partial / validate_partial
# ---------------------------------------------------------------------------

def test_load_partial_empty_dir_returns_metadata_only(plan_dir: Path):
    out = pm.load_partial(plan_dir)
    assert set(out) == {"metadata"}


def test_partial_validator_accepts_missing_top_level():
    assert validate_partial({}) == []


def test_partial_validator_still_catches_malformed_component():
    errs = validate_partial({"components": [{"id": "x"}]})  # missing type/config
    assert errs


def test_partial_validator_rejects_metadata_missing_version():
    errs = validate_partial({"metadata": {"id": "x", "name": "y"}})
    assert any(e["path"] == "metadata" for e in errs)
