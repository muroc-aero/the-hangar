"""Tests for the plan-level ``shared_vars`` primitive (Fix 2).

``shared_vars`` lets two or more components in a composite plan share a
set of design variables without per-element ``connections:`` wiring. The
materializer builds a root ``shared_ivc`` IndepVarComp, removes the
named fields from each consumer's internal IVC via ``skip_fields``, and
fans out connections from the shared IVC to every consumer.

Design doc: ``packages/omd/MULTI_TOOL_COMPOSITION_PLAN.md`` (Fix 2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Schema & semantic validation (fast)
# ---------------------------------------------------------------------------


def _minimal_plan_with_shared_vars(**kwargs) -> dict:
    base = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [
            {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
            {"id": "b", "type": "paraboloid/Paraboloid", "config": {}},
        ],
        "shared_vars": [
            {
                "name": "x",
                "value": 3.0,
                "consumers": ["a", "b"],
            },
        ],
    }
    base.update(kwargs)
    return base


class TestSchema:

    def test_shared_vars_passes_schema(self):
        from hangar.omd.plan_schema import validate_plan
        plan = _minimal_plan_with_shared_vars()
        assert validate_plan(plan) == []

    def test_shared_vars_missing_consumers_rejected(self):
        from hangar.omd.plan_schema import validate_plan
        plan = _minimal_plan_with_shared_vars()
        del plan["shared_vars"][0]["consumers"]
        errors = validate_plan(plan)
        assert errors, "expected schema error for missing consumers"
        assert any("consumers" in e["message"] for e in errors)

    def test_shared_vars_empty_consumers_rejected(self):
        from hangar.omd.plan_schema import validate_plan
        plan = _minimal_plan_with_shared_vars()
        plan["shared_vars"][0]["consumers"] = []
        errors = validate_plan(plan)
        assert errors, "expected schema error for empty consumers"

    def test_shared_vars_optional_units_and_value(self):
        from hangar.omd.plan_schema import validate_plan
        plan = _minimal_plan_with_shared_vars()
        plan["shared_vars"][0]["units"] = "m"
        plan["shared_vars"][0]["value"] = [0.005, 0.01, 0.015]
        assert validate_plan(plan) == []


class TestSemanticValidation:

    def test_unknown_consumer_flagged(self):
        from hangar.omd.plan_validate import validate_shared_vars
        plan = _minimal_plan_with_shared_vars()
        plan["shared_vars"][0]["consumers"] = ["a", "nonexistent"]
        findings = validate_shared_vars(plan)
        assert any("nonexistent" in f.message for f in findings)

    def test_duplicate_name_flagged(self):
        from hangar.omd.plan_validate import validate_shared_vars
        plan = _minimal_plan_with_shared_vars()
        plan["shared_vars"].append({
            "name": "x", "value": 5.0, "consumers": ["a"],
        })
        findings = validate_shared_vars(plan)
        assert any("Duplicate" in f.message for f in findings)

    def test_pyc_consumer_flagged_as_unsupported(self):
        from hangar.omd.plan_validate import validate_shared_vars
        plan = _minimal_plan_with_shared_vars()
        plan["components"].append({
            "id": "engine",
            "type": "pyc/TurbojetDesign",
            "config": {},
        })
        plan["shared_vars"][0]["consumers"] = ["a", "engine"]
        findings = validate_shared_vars(plan)
        assert any(
            "skip_fields" in f.message and "engine" in f.message
            for f in findings
        )

    def test_no_shared_vars_noop(self):
        from hangar.omd.plan_validate import validate_shared_vars
        plan = {"components": [{"id": "a", "type": "paraboloid/Paraboloid"}]}
        assert validate_shared_vars(plan) == []

    def test_shared_var_name_accepted_as_dv_target(self):
        """A shared_var name must pass the semantic DV-name validator."""
        from hangar.omd.plan_validate import validate_var_paths
        plan = _minimal_plan_with_shared_vars()
        plan["design_variables"] = [
            {"name": "x", "lower": 0.0, "upper": 10.0},
        ]
        # Without shared_vars context, 'x' would be rejected. With it
        # present, the validator adds it to the known set.
        assert validate_var_paths(plan) == []


# ---------------------------------------------------------------------------
# Materializer end-to-end (fast -- paraboloid is trivial)
# ---------------------------------------------------------------------------


class TestMaterializerWiring:

    def _build(self):
        from hangar.omd.materializer import materialize
        plan = {
            "metadata": {"id": "shared-parab", "name": "t", "version": 1},
            "components": [
                {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
                {"id": "b", "type": "paraboloid/Paraboloid", "config": {}},
            ],
            "shared_vars": [
                {"name": "x", "value": 3.0, "consumers": ["a", "b"]},
            ],
        }
        return materialize(plan), plan

    def test_shared_ivc_subsystem_present(self):
        (prob, meta), _ = self._build()
        assert prob.model._get_subsystem("shared_ivc") is not None
        # The shared IVC output is promoted, so its path at the model
        # root is the bare name.
        assert meta["shared_var_paths"]["x"] == "x"

    def test_shared_ivc_drives_both_consumers(self):
        (prob, _), _ = self._build()
        prob.set_val("a.y", -4.0)
        prob.set_val("b.y", -4.0)
        prob.run_model()
        # f(3, -4) = 0 + (-12) + 0 - 3 = -15
        assert abs(float(prob.get_val("a.f_xy")) - (-15.0)) < 1e-8
        assert abs(float(prob.get_val("b.f_xy")) - (-15.0)) < 1e-8
        prob.cleanup()

    def test_updating_shared_value_reaches_all_consumers(self):
        (prob, _), _ = self._build()
        prob.set_val("a.y", 0.0)
        prob.set_val("b.y", 0.0)
        prob.set_val("x", 5.0)
        prob.run_model()
        # f(5, 0) = 4 + 0 + 16 - 3 = 17
        assert abs(float(prob.get_val("a.f_xy")) - 17.0) < 1e-8
        assert abs(float(prob.get_val("b.f_xy")) - 17.0) < 1e-8
        prob.cleanup()

    def test_var_paths_exposes_shared_var_name(self):
        (_, meta), _ = self._build()
        # Composite metadata publishes a merged var_paths with shared
        # names redirected to the promoted name at the model root.
        assert meta["var_paths"]["x"] == "x"


class TestDVResolution:

    def test_shared_var_dv_registered_at_root(self):
        """A DV whose name matches a shared_var routes to shared_ivc."""
        from hangar.omd.materializer import materialize
        plan = {
            "metadata": {"id": "dv-shared", "name": "t", "version": 1},
            "components": [
                {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
                {"id": "b", "type": "paraboloid/Paraboloid", "config": {}},
            ],
            "shared_vars": [
                {"name": "x", "value": 3.0, "consumers": ["a", "b"]},
            ],
            "design_variables": [
                {"name": "x", "lower": -50.0, "upper": 50.0},
            ],
            "constraints": [
                {"name": "a.f_xy", "lower": -100.0},
            ],
            "objective": {"name": "b.f_xy"},
        }
        prob, meta = materialize(plan)
        # get_design_vars() needs final_setup (sizes computed).
        prob.final_setup()
        # Driver registers the DV once at the promoted shared name.
        dvs = prob.model.get_design_vars()
        # OpenMDAO's get_design_vars keys the DV under its promoted
        # name (not the per-component path). Exactly one entry and
        # it resolves via the shared IVC source.
        assert "x" in dvs
        assert len(dvs) == 1
        prob.cleanup()


class TestRegression:

    def test_connections_only_composite_unchanged(self):
        """Existing connections:-only plans must still materialize."""
        from hangar.omd.materializer import materialize
        plan = {
            "metadata": {"id": "parab2", "name": "t", "version": 1},
            "components": [
                {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
                {"id": "b", "type": "paraboloid/Paraboloid", "config": {}},
            ],
            "connections": [
                {"src": "a.f_xy", "tgt": "b.x"},
            ],
            "operating_points": {"x": 3.0, "y": -4.0},
        }
        prob, meta = materialize(plan)
        # No shared_ivc when shared_vars is absent.
        assert prob.model._get_subsystem("shared_ivc") is None
        prob.set_val("a.x", 3.0)
        prob.set_val("a.y", -4.0)
        prob.set_val("b.y", 0.0)
        prob.run_model()
        assert abs(float(prob.get_val("a.f_xy")) - (-15.0)) < 1e-8
        prob.cleanup()


# ---------------------------------------------------------------------------
# Plan mutation CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def plan_with_two_components(tmp_path: Path, runner: CliRunner) -> Path:
    from hangar.omd.cli import cli
    d = tmp_path / "plan"
    r = runner.invoke(
        cli, ["plan", "init", str(d), "--id", "demo", "--name", "Demo"],
    )
    assert r.exit_code == 0, r.output
    for cid in ("a", "b"):
        # Write a minimal paraboloid component YAML directly.
        comp_dir = d / "components"
        comp_dir.mkdir(exist_ok=True)
        (comp_dir / f"{cid}.yaml").write_text(
            f"id: {cid}\n"
            f"type: paraboloid/Paraboloid\n"
            f"config: {{}}\n"
        )
    return d


class TestPlanMutateCLI:

    def test_add_shared_var_writes_yaml(
        self, plan_with_two_components: Path, runner: CliRunner,
    ):
        from hangar.omd.cli import cli
        r = runner.invoke(cli, [
            "plan", "add-shared-var", str(plan_with_two_components),
            "--name", "x",
            "--value", "3.5",
            "--consumers", "a,b",
        ])
        assert r.exit_code == 0, r.output
        sv = yaml.safe_load(
            (plan_with_two_components / "shared_vars.yaml").read_text()
        )
        assert isinstance(sv, list)
        assert sv[0] == {
            "name": "x",
            "consumers": ["a", "b"],
            "value": 3.5,
        }

    def test_add_shared_var_list_value(
        self, plan_with_two_components: Path, runner: CliRunner,
    ):
        from hangar.omd.cli import cli
        r = runner.invoke(cli, [
            "plan", "add-shared-var", str(plan_with_two_components),
            "--name", "thickness_cp",
            "--value", "0.005,0.01,0.015",
            "--units", "m",
            "--consumers", "a,b",
        ])
        assert r.exit_code == 0, r.output
        sv = yaml.safe_load(
            (plan_with_two_components / "shared_vars.yaml").read_text()
        )
        assert sv[0]["value"] == [0.005, 0.01, 0.015]
        assert sv[0]["units"] == "m"

    def test_add_shared_var_rejects_unknown_consumer(
        self, plan_with_two_components: Path, runner: CliRunner,
    ):
        from hangar.omd.cli import cli
        r = runner.invoke(cli, [
            "plan", "add-shared-var", str(plan_with_two_components),
            "--name", "x",
            "--value", "3.0",
            "--consumers", "a,ghost",
        ])
        assert r.exit_code != 0
        assert "ghost" in r.output

    def test_add_shared_var_rejects_duplicate(
        self, plan_with_two_components: Path, runner: CliRunner,
    ):
        from hangar.omd.cli import cli
        runner.invoke(cli, [
            "plan", "add-shared-var", str(plan_with_two_components),
            "--name", "x", "--value", "3", "--consumers", "a,b",
        ])
        r = runner.invoke(cli, [
            "plan", "add-shared-var", str(plan_with_two_components),
            "--name", "x", "--value", "4", "--consumers", "a,b",
        ])
        assert r.exit_code != 0
        assert "already exists" in r.output


class TestAssemblerPickup:

    def test_shared_vars_yaml_spliced_in(self, tmp_path: Path):
        from hangar.omd.assemble import assemble_plan
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "metadata.yaml").write_text(
            "id: t\nname: t\nversion: 1\n"
        )
        (plan_dir / "shared_vars.yaml").write_text(
            "- name: x\n  value: 3.0\n  consumers: [a, b]\n"
        )
        comp_dir = plan_dir / "components"
        comp_dir.mkdir()
        for cid in ("a", "b"):
            (comp_dir / f"{cid}.yaml").write_text(
                f"id: {cid}\ntype: paraboloid/Paraboloid\nconfig: {{}}\n"
            )
        result = assemble_plan(plan_dir)
        assert result["errors"] == []
        assert result["plan"]["shared_vars"] == [
            {"name": "x", "value": 3.0, "consumers": ["a", "b"]},
        ]


# ---------------------------------------------------------------------------
# OCP factory skip_fields (slow -- imports openconcept)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestOCPSkipFields:

    def test_skip_fields_removes_dv_comp_entry(self):
        """With skip_fields=['ac|geom|wing|AR'], the dv_comp must not
        register AR as an output. The aircraft model still promotes the
        name through as an input (now undriven)."""
        import openmdao.api as om
        from hangar.omd.factories.ocp.builder import build_ocp_basic_mission

        cfg = {
            "aircraft_template": "b738",
            "architecture": "twin_turbofan",
            "num_nodes": 3,
            "mission_params": {
                "cruise_altitude_ft": 35000.0,
                "mission_range_NM": 100.0,
                "climb_vs_ftmin": 1500.0,
                "climb_Ueas_kn": 230.0,
                "cruise_Ueas_kn": 270.0,
                "descent_vs_ftmin": 1500.0,
                "descent_Ueas_kn": 250.0,
            },
            "skip_fields": ["ac|geom|wing|AR"],
            "_defer_setup": True,
        }
        prob, meta = build_ocp_basic_mission(cfg, {})
        # Must also drive the now-undriven input externally for setup
        # to check out; attach a trivial IVC to supply it.
        supplier = om.IndepVarComp()
        supplier.add_output("ac|geom|wing|AR", val=9.45)
        wrapper = om.Group()
        wrapper.add_subsystem(
            "supplier", supplier, promotes_outputs=["ac|geom|wing|AR"],
        )
        wrapper.add_subsystem(
            "mission", prob.model, promotes_inputs=["ac|geom|wing|AR"],
        )
        outer = om.Problem(model=wrapper, reports=False)
        outer.setup(check=False)
        # Assert dv_comp did not emit AR as one of its outputs.
        dv_outputs = outer.model.mission._get_subsystem("dv_comp").list_outputs(
            out_stream=None, return_format="dict",
        )
        dv_names = {k.split(".")[-1] for k in dv_outputs}
        assert "ac|geom|wing|AR" not in dv_names, dv_names
        outer.cleanup()
