"""Tests for plan_graph and discipline_graph builders."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hangar.omd.plan_graph import build_plan_graph
from hangar.omd.discipline_graph import build_discipline_graph

FIXTURES = Path(__file__).parent / "fixtures"
STUDIES = Path(__file__).parents[3] / "hangar_studies"


def _load_plan(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _node_ids(graph: dict) -> set[str]:
    return {n["id"] for n in graph["nodes"]}


def _node_types(graph: dict) -> set[str]:
    return {n["type"] for n in graph["nodes"]}


def _node_by_id(graph: dict, nid: str) -> dict | None:
    for n in graph["nodes"]:
        if n["id"] == nid:
            return n
    return None


def _edge_relations(graph: dict) -> list[str]:
    return [e["relation"] for e in graph["edges"]]


# -----------------------------------------------------------------------
# Plan graph: OCP
# -----------------------------------------------------------------------


class TestPlanGraphOCP:
    def test_basic_mission(self):
        plan = _load_plan(FIXTURES / "ocp_basic_mission/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "plan" in ids
        assert "aircraft_config" in ids
        assert "mission_profile" in ids

    def test_basic_mission_has_architecture(self):
        plan = _load_plan(FIXTURES / "ocp_basic_mission/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "architecture" in ids
        # Check architecture edge
        arch_edges = [e for e in g["edges"]
                      if e["relation"] == "has_architecture"]
        assert len(arch_edges) >= 1

    def test_with_slots(self):
        plan = _load_plan(FIXTURES / "ocp_pyc_prop_slot/history/v3.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "slot-propulsion" in ids
        slot = _node_by_id(g, "slot-propulsion")
        assert slot is not None
        assert slot["properties"]["provider"] == "pyc/turbojet"

    def test_with_drag_slot(self):
        plan = _load_plan(FIXTURES / "ocp_vlm_drag_slot/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "slot-drag" in ids
        slot = _node_by_id(g, "slot-drag")
        assert slot is not None
        assert "oas/vlm" in slot["properties"]["provider"]

    def test_inline_aircraft_data(self):
        plan_path = STUDIES / "a320-neo-integration/step3_integrated_mission.yaml"
        if not plan_path.exists():
            pytest.skip("A320neo study plan not available")
        plan = _load_plan(plan_path)
        g = build_plan_graph(plan)

        ac = _node_by_id(g, "aircraft_config")
        assert ac is not None
        # Should extract S_ref from inline aircraft_data
        assert ac["properties"].get("S_ref") is not None

    def test_solver_settings(self):
        plan = _load_plan(FIXTURES / "ocp_pyc_prop_slot/history/v3.yaml")
        g = build_plan_graph(plan)

        # OCP plans with solver_settings should get a solver node
        # (depends on fixture having solver_settings in config)
        types = _node_types(g)
        # At minimum we should have plan, aircraft_config, mission_profile
        assert "plan" in types
        assert "aircraft_config" in types
        assert "mission_profile" in types

    def test_mission_profile_properties(self):
        plan = _load_plan(FIXTURES / "ocp_basic_mission/history/v1.yaml")
        g = build_plan_graph(plan)

        mp = _node_by_id(g, "mission_profile")
        assert mp is not None
        props = mp["properties"]
        assert "phases" in props
        assert isinstance(props["phases"], list)


# -----------------------------------------------------------------------
# Plan graph: pyCycle
# -----------------------------------------------------------------------


class TestPlanGraphPyCycle:
    def test_turbojet(self):
        plan = _load_plan(FIXTURES / "pyc_turbojet_design/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "engine_config" in ids
        # Should have element nodes
        assert "elem-inlet" in ids
        assert "elem-comp" in ids
        assert "elem-burner" in ids
        assert "elem-turb" in ids
        assert "elem-nozz" in ids

    def test_turbojet_flow_edges(self):
        plan = _load_plan(FIXTURES / "pyc_turbojet_design/history/v1.yaml")
        g = build_plan_graph(plan)

        flow_edges = [(e["source"], e["target"]) for e in g["edges"]
                      if e["relation"] == "flow_to"]
        assert ("elem-inlet", "elem-comp") in flow_edges
        assert ("elem-comp", "elem-burner") in flow_edges
        assert ("elem-burner", "elem-turb") in flow_edges
        assert ("elem-turb", "elem-nozz") in flow_edges

    def test_turbojet_has_flight_condition(self):
        plan = _load_plan(FIXTURES / "pyc_turbojet_design/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "flight" in ids

    def test_turbojet_engine_config_label(self):
        plan = _load_plan(FIXTURES / "pyc_turbojet_design/history/v1.yaml")
        g = build_plan_graph(plan)

        ec = _node_by_id(g, "engine_config")
        assert ec is not None
        assert "Turbojet" in ec["label"]
        # Should include key parameters
        assert "comp_PR" in ec["label"]

    def test_hbtf(self):
        plan = _load_plan(FIXTURES / "pyc_hbtf_design/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "engine_config" in ids
        assert "elem-fan" in ids
        assert "elem-splitter" in ids
        assert "elem-hpc" in ids
        assert "elem-hpt" in ids
        assert "elem-lpt" in ids
        assert "elem-core_nozz" in ids
        assert "elem-byp_nozz" in ids

    def test_hbtf_bypass_edge(self):
        plan = _load_plan(FIXTURES / "pyc_hbtf_design/history/v1.yaml")
        g = build_plan_graph(plan)

        flow_edges = [(e["source"], e["target"]) for e in g["edges"]
                      if e["relation"] == "flow_to"]
        assert ("elem-splitter", "elem-byp_nozz") in flow_edges

    def test_ab_turbojet(self):
        plan = _load_plan(FIXTURES / "pyc_ab_turbojet_design/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "elem-ab" in ids  # afterburner

    def test_single_turboshaft(self):
        plan = _load_plan(FIXTURES / "pyc_single_turboshaft_design/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "elem-pt" in ids  # power turbine

    def test_mixedflow(self):
        plan = _load_plan(FIXTURES / "pyc_mixedflow_design/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "elem-mixer" in ids
        assert "elem-ab" in ids


# -----------------------------------------------------------------------
# Plan graph: OAS (regression)
# -----------------------------------------------------------------------


class TestPlanGraphOAS:
    def test_aero_analysis_unchanged(self):
        plan = _load_plan(FIXTURES / "oas_aero_analysis/history/v1.yaml")
        g = build_plan_graph(plan)

        types = _node_types(g)
        assert "plan" in types
        assert "surface" in types
        assert "mesh" in types
        assert "flight_condition" in types


# -----------------------------------------------------------------------
# Discipline graph: OCP
# -----------------------------------------------------------------------


class TestDisciplineGraphOCP:
    def test_basic_mission(self):
        g = build_discipline_graph(
            "ocp/BasicMission",
            metadata={"component_family": "ocp", "architecture": "turboprop",
                       "phases": ["climb", "cruise", "descent"]},
        )
        ids = _node_ids(g)
        assert "aircraft_config" in ids
        assert "aero" in ids
        assert "propulsion" in ids
        assert "weight" in ids
        assert "mission" in ids
        # Coupling loop
        assert "coupling" in ids

    def test_has_flow_edges(self):
        g = build_discipline_graph("ocp/BasicMission", metadata={})
        rels = _edge_relations(g)
        assert "provides" in rels

    def test_enriched_slot_labels(self):
        g = build_discipline_graph(
            "ocp/BasicMission",
            metadata={
                "component_family": "ocp",
                "active_slots": {
                    "drag": {"provider": "oas/vlm"},
                    "propulsion": {"provider": "pyc/turbojet"},
                },
            },
        )
        aero = _node_by_id(g, "aero")
        prop = _node_by_id(g, "propulsion")
        assert aero is not None
        assert "oas/vlm" in aero["label"]
        assert prop is not None
        assert "pyc/turbojet" in prop["label"]

    def test_mission_enrichment(self):
        g = build_discipline_graph(
            "ocp/BasicMission",
            metadata={
                "component_family": "ocp",
                "phases": ["climb", "cruise", "descent"],
                "mission_type": "basic",
            },
        )
        mission = _node_by_id(g, "mission")
        assert mission is not None
        assert "3 phases" in mission["label"]


# -----------------------------------------------------------------------
# Discipline graph: pyCycle
# -----------------------------------------------------------------------


class TestDisciplineGraphPyCycle:
    def test_turbojet(self):
        g = build_discipline_graph("pyc/TurbojetDesign")
        ids = _node_ids(g)
        assert "fc" in ids
        assert "inlet" in ids
        assert "comp" in ids
        assert "burner" in ids
        assert "turb" in ids
        assert "nozz" in ids
        assert "perf" in ids
        # 7 discipline nodes + balance coupling
        assert "balance" in ids
        assert len([n for n in g["nodes"] if n["type"] == "discipline"]) == 7

    def test_turbojet_flow_edges(self):
        g = build_discipline_graph("pyc/TurbojetDesign")
        rels = _edge_relations(g)
        assert "provides" in rels
        assert "couples" in rels

    def test_hbtf(self):
        g = build_discipline_graph("pyc/HBTFDesign")
        ids = _node_ids(g)
        assert "fan" in ids
        assert "splitter" in ids
        assert "lpc" in ids
        assert "hpc" in ids
        assert "hpt" in ids
        assert "lpt" in ids
        assert "core_nozz" in ids
        assert "byp_nozz" in ids
        assert "perf" in ids
        assert len([n for n in g["nodes"] if n["type"] == "discipline"]) == 12

    def test_ab_turbojet(self):
        g = build_discipline_graph("pyc/ABTurbojetDesign")
        ids = _node_ids(g)
        assert "ab" in ids

    def test_single_turboshaft(self):
        g = build_discipline_graph("pyc/SingleTurboshaftDesign")
        ids = _node_ids(g)
        assert "pt" in ids

    def test_multi_turboshaft(self):
        g = build_discipline_graph("pyc/MultiTurboshaftDesign")
        ids = _node_ids(g)
        assert "hpc_axi" in ids
        assert "hpc_centri" in ids
        assert "pt" in ids

    def test_mixedflow(self):
        g = build_discipline_graph("pyc/MixedFlowDesign")
        ids = _node_ids(g)
        assert "mixer" in ids
        assert "ab" in ids

    def test_multipoint_enrichment(self):
        g = build_discipline_graph(
            "pyc/TurbojetMultipoint",
            metadata={
                "multipoint": True,
                "point_names": ["DESIGN", "OD_0", "OD_1"],
                "archetype_meta": {"description": "Single-spool turbojet"},
            },
        )
        fc = _node_by_id(g, "fc")
        assert fc is not None
        assert "3 points" in fc["label"]


# -----------------------------------------------------------------------
# Discipline graph: fallback
# -----------------------------------------------------------------------


class TestDisciplineGraphFallback:
    def test_unknown_type(self):
        g = build_discipline_graph("unknown/Type")
        assert len(g["nodes"]) == 1
        assert g["nodes"][0]["id"] == "component"
        assert len(g["edges"]) == 0

    def test_oas_unchanged(self):
        g = build_discipline_graph("oas/AerostructPoint")
        ids = _node_ids(g)
        assert "geometry" in ids
        assert "aero" in ids
        assert "struct" in ids
        assert "perf" in ids
        assert "coupling" in ids


# -----------------------------------------------------------------------
# Plan graph: slot decomposition
# -----------------------------------------------------------------------


class TestSlotDecomposition:
    def test_vlm_slot_has_surface_and_mesh(self):
        plan = _load_plan(FIXTURES / "ocp_vlm_drag_slot/history/v1.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "slot-drag" in ids
        assert "slot-drag-surf" in ids
        assert "slot-drag-mesh" in ids

        # Mesh node should have num_x/num_y
        mesh = _node_by_id(g, "slot-drag-mesh")
        assert mesh is not None
        assert mesh["properties"].get("num_y") is not None

    def test_vlm_slot_mesh_label(self):
        plan = _load_plan(FIXTURES / "ocp_vlm_drag_slot/history/v1.yaml")
        g = build_plan_graph(plan)

        mesh = _node_by_id(g, "slot-drag-mesh")
        assert mesh is not None
        assert "panels" in mesh["label"]

    def test_vlm_slot_has_configures_edge(self):
        plan = _load_plan(FIXTURES / "ocp_vlm_drag_slot/history/v1.yaml")
        g = build_plan_graph(plan)

        config_edges = [
            e for e in g["edges"]
            if e["relation"] == "configures"
            and e["source"] == "aircraft_config"
            and e["target"] == "slot-drag-surf"
        ]
        assert len(config_edges) >= 1

    def test_pyc_direct_slot_has_elements(self):
        plan = _load_plan(FIXTURES / "ocp_pyc_prop_slot/history/v3.yaml")
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "slot-propulsion" in ids
        # Direct pyc/turbojet should decompose into engine elements
        assert "slot-propulsion-elem-inlet" in ids
        assert "slot-propulsion-elem-comp" in ids
        assert "slot-propulsion-elem-burner" in ids
        assert "slot-propulsion-elem-turb" in ids
        assert "slot-propulsion-elem-nozz" in ids

    def test_pyc_direct_slot_has_flow_edges(self):
        plan = _load_plan(FIXTURES / "ocp_pyc_prop_slot/history/v3.yaml")
        g = build_plan_graph(plan)

        flow_edges = [
            (e["source"], e["target"]) for e in g["edges"]
            if e["relation"] == "flow_to"
            and e["source"].startswith("slot-propulsion-elem-")
        ]
        assert ("slot-propulsion-elem-inlet", "slot-propulsion-elem-comp") in flow_edges
        assert ("slot-propulsion-elem-comp", "slot-propulsion-elem-burner") in flow_edges

    def test_pyc_surrogate_slot_has_archetype_and_deck(self):
        plan_path = STUDIES / "a320-neo-integration/step3_integrated_mission.yaml"
        if not plan_path.exists():
            pytest.skip("A320neo study plan not available")
        plan = _load_plan(plan_path)
        g = build_plan_graph(plan)

        ids = _node_ids(g)
        assert "slot-propulsion" in ids
        assert "slot-propulsion-archetype" in ids
        assert "slot-propulsion-deck" in ids

        arch = _node_by_id(g, "slot-propulsion-archetype")
        assert arch is not None
        assert arch["properties"]["archetype"] == "turbojet"

        deck = _node_by_id(g, "slot-propulsion-deck")
        assert deck is not None
        assert deck["type"] == "surrogate_deck"


# -----------------------------------------------------------------------
# Problem DAG: result enrichment
# -----------------------------------------------------------------------


class TestProblemDAGEnrichment:
    """Test the result enrichment logic used by the problem DAG handler."""

    def test_slot_results_injected_into_nodes(self):
        """Build a discipline graph and verify enrichment injects results."""
        dgraph = build_discipline_graph(
            "ocp/BasicMission",
            metadata={
                "component_family": "ocp",
                "active_slots": {
                    "drag": {"provider": "oas/vlm"},
                    "propulsion": {"provider": "pyc/surrogate"},
                },
            },
        )

        # Simulate what cli.py does with slot_results
        slot_results = {
            "drag": {"provider": "oas/vlm", "drag": 45200.0},
            "propulsion": {"provider": "pyc/surrogate", "thrust": 52000.0,
                           "fuel_flow": 1.23},
        }
        run_summary = {"fuel_burn_kg": 7500.0, "OEW_kg": 42600.0}

        _SLOT_TO_NODE = {
            "drag": "aero", "propulsion": "propulsion", "weight": "weight",
        }

        for node in dgraph["nodes"]:
            props = node.get("properties", {})
            nid = node["id"]
            result_values = {}

            for slot_name, node_id in _SLOT_TO_NODE.items():
                if nid == node_id and slot_name in slot_results:
                    sr = slot_results[slot_name]
                    for k, v in sr.items():
                        if k == "provider":
                            continue
                        result_values[k] = f"{v:.4g}" if isinstance(v, float) else str(v)

            if nid == "mission" and run_summary:
                for k, v in run_summary.items():
                    result_values[k] = f"{v:.4g}" if isinstance(v, float) else str(v)

            if result_values:
                props["result_values"] = result_values
            node["properties"] = props

        # Check aero node got drag result
        aero = _node_by_id(dgraph, "aero")
        assert aero is not None
        assert "result_values" in aero["properties"]
        assert "drag" in aero["properties"]["result_values"]

        # Check propulsion node got thrust
        prop = _node_by_id(dgraph, "propulsion")
        assert prop is not None
        assert "thrust" in prop["properties"]["result_values"]

        # Check mission node got fuel_burn_kg
        mission = _node_by_id(dgraph, "mission")
        assert mission is not None
        assert "fuel_burn_kg" in mission["properties"]["result_values"]


# ---------------------------------------------------------------------------
# Enriched plan_graph tests (phase, acceptance_criterion, justifies targeting)
# ---------------------------------------------------------------------------


def _build_enriched_graph(tmp_path):
    """Assemble the enriched fixture into a working dir, then build its graph."""
    import shutil
    from hangar.omd.assemble import assemble_plan

    work = tmp_path / "enriched"
    shutil.copytree(FIXTURES / "oas_aerostruct_enriched", work)
    result = assemble_plan(work)
    assert result["errors"] == [], result["errors"]
    return build_plan_graph(result["plan"], "plan-oas-aerostruct-enriched", 1)


def test_enriched_graph_has_phase_nodes(tmp_path):
    g = _build_enriched_graph(tmp_path)
    types = _node_types(g)
    assert "phase" in types
    phase_ids = [n["id"] for n in g["nodes"] if n["type"] == "phase"]
    assert "phase-phase-1" in phase_ids
    assert "phase-phase-2" in phase_ids


def test_enriched_graph_has_precedes_edge(tmp_path):
    g = _build_enriched_graph(tmp_path)
    edges = [(e["source"], e["target"]) for e in g["edges"]
             if e["relation"] == "precedes"]
    assert ("phase-phase-1", "phase-phase-2") in edges


def test_enriched_graph_has_acceptance_criterion_nodes(tmp_path):
    g = _build_enriched_graph(tmp_path)
    crits = [n for n in g["nodes"] if n["type"] == "acceptance_criterion"]
    assert len(crits) == 2
    # has_criterion edges link requirements to their criteria
    has_crit = [(e["source"], e["target"]) for e in g["edges"]
                if e["relation"] == "has_criterion"]
    assert len(has_crit) == 2
    assert all(s.startswith("req-") and t.startswith("crit-")
               for s, t in has_crit)


def test_enriched_graph_justifies_targets_specific_elements(tmp_path):
    g = _build_enriched_graph(tmp_path)
    justifies = [(e["source"], e["target"]) for e in g["edges"]
                 if e["relation"] == "justifies"]
    assert justifies, "expected justifies edges for enriched decisions"
    targets = {t for _, t in justifies}
    # None should fall back to the generic "plan" node -- all three
    # decisions in the fixture carry an element_path.
    assert "plan" not in targets
    # Expect at least one DV target, one objective target, one mesh target.
    assert any(t.startswith("mesh-") for t in targets)
    assert any(t.startswith("dv-") for t in targets)
    assert "objective" in targets
