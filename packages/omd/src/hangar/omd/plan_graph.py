"""Build a knowledge graph from a plan YAML dict.

Produces a typed entity-relationship graph with nodes (typed entities)
and edges (named relationships). The graph data contract is designed
to be replaceable by a TypeDB query returning the same structure.

Graph schema:
    Node types: plan, surface, material, fem_model, mesh, flight_condition,
                solver, linear_solver, objective, design_variable, constraint,
                decision, requirement, aircraft_config, mission_profile,
                propulsion_architecture, slot_provider, engine_config,
                engine_element
    Edge types: contains, has_geometry, has_material, has_fem, uses_solver,
                uses_linear, at_conditions, acts_on, bounds, justifies,
                traces_to, has_architecture, flow_to, couples, provides
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# OCP reference data (no external dependencies)
# ---------------------------------------------------------------------------

_OCP_TEMPLATE_SUMMARY: dict[str, dict] = {
    "caravan": {
        "label": "Cessna 208 Caravan",
        "S_ref_m2": 26.0, "AR": 9.69, "MTOW_kg": 3970, "OEW_kg": 2145,
    },
    "b738": {
        "label": "Boeing 737-800",
        "S_ref_m2": 124.6, "AR": 9.45, "MTOW_kg": 79002, "OEW_kg": 41871,
    },
    "kingair": {
        "label": "King Air C90GT",
        "S_ref_m2": 27.3, "AR": 8.58, "MTOW_kg": 4581, "OEW_kg": 2585,
    },
    "tbm850": {
        "label": "TBM 850",
        "S_ref_m2": 18.0, "AR": 8.95, "MTOW_kg": 3353, "OEW_kg": 2073,
    },
}

_OCP_MISSION_PHASES: dict[str, list[str]] = {
    "ocp/BasicMission": ["climb", "cruise", "descent"],
    "ocp/FullMission": ["v0v1", "v1vr", "v1v0", "rotate",
                        "climb", "cruise", "descent"],
    "ocp/MissionWithReserve": ["climb", "cruise", "descent",
                               "reserve_climb", "reserve_cruise",
                               "reserve_descent", "loiter"],
}

# ---------------------------------------------------------------------------
# pyCycle reference data
# ---------------------------------------------------------------------------

_PYC_ARCHETYPE_LABEL: dict[str, str] = {
    "TurbojetDesign": "Turbojet",
    "TurbojetMultipoint": "Turbojet (MP)",
    "HBTFDesign": "High-Bypass Turbofan",
    "ABTurbojetDesign": "AB Turbojet",
    "SingleTurboshaftDesign": "Turboshaft",
    "MultiTurboshaftDesign": "Multi-Spool Turboshaft",
    "MixedFlowDesign": "Mixed-Flow Turbofan",
}

_PYC_DISPLAY_KEYS: dict[str, list[str]] = {
    "TurbojetDesign": ["comp_PR", "comp_eff", "turb_eff", "thermo_method"],
    "TurbojetMultipoint": ["comp_PR", "comp_eff", "turb_eff", "thermo_method"],
    "HBTFDesign": ["fan_PR", "hpc_PR", "BPR", "fan_eff", "hpc_eff",
                    "thermo_method"],
    "ABTurbojetDesign": ["comp_PR", "comp_eff", "turb_eff", "thermo_method"],
    "SingleTurboshaftDesign": ["comp_PR", "comp_eff", "turb_eff",
                               "thermo_method"],
    "MultiTurboshaftDesign": ["lpc_PR", "hpc_axi_PR", "hpc_centri_PR",
                              "thermo_method"],
    "MixedFlowDesign": ["fan_PR", "lpc_PR", "hpc_PR", "thermo_method"],
}

# Major flow-path elements per archetype (id, human label).
# Ducts and bleeds omitted for readability.
_PYC_ELEMENTS: dict[str, list[tuple[str, str]]] = {
    "TurbojetDesign": [
        ("inlet", "Inlet"), ("comp", "Compressor"), ("burner", "Combustor"),
        ("turb", "Turbine"), ("nozz", "Nozzle"),
    ],
    "TurbojetMultipoint": [
        ("inlet", "Inlet"), ("comp", "Compressor"), ("burner", "Combustor"),
        ("turb", "Turbine"), ("nozz", "Nozzle"),
    ],
    "HBTFDesign": [
        ("inlet", "Inlet"), ("fan", "Fan"), ("splitter", "Splitter"),
        ("lpc", "LPC"), ("hpc", "HPC"), ("burner", "Combustor"),
        ("hpt", "HP Turbine"), ("lpt", "LP Turbine"),
        ("core_nozz", "Core Nozzle"), ("byp_nozz", "Bypass Nozzle"),
    ],
    "ABTurbojetDesign": [
        ("inlet", "Inlet"), ("comp", "Compressor"), ("burner", "Combustor"),
        ("turb", "Turbine"), ("ab", "Afterburner"), ("nozz", "Nozzle"),
    ],
    "SingleTurboshaftDesign": [
        ("inlet", "Inlet"), ("comp", "Compressor"), ("burner", "Combustor"),
        ("turb", "GG Turbine"), ("pt", "Power Turbine"), ("nozz", "Exhaust"),
    ],
    "MultiTurboshaftDesign": [
        ("inlet", "Inlet"), ("lpc", "LPC"), ("hpc_axi", "HPC (Axial)"),
        ("hpc_centri", "HPC (Centrifugal)"), ("burner", "Combustor"),
        ("hpt", "HP Turbine"), ("lpt", "LP Turbine"),
        ("pt", "Power Turbine"), ("nozz", "Exhaust"),
    ],
    "MixedFlowDesign": [
        ("inlet", "Inlet"), ("fan", "Fan"), ("splitter", "Splitter"),
        ("lpc", "LPC"), ("hpc", "HPC"), ("burner", "Combustor"),
        ("hpt", "HP Turbine"), ("lpt", "LP Turbine"),
        ("mixer", "Mixer"), ("ab", "Afterburner"), ("nozz", "Mixed Nozzle"),
    ],
}

# Streamwise flow order (element ids) -- main gas path only.
_PYC_FLOW_ORDER: dict[str, list[str]] = {
    "TurbojetDesign": ["inlet", "comp", "burner", "turb", "nozz"],
    "TurbojetMultipoint": ["inlet", "comp", "burner", "turb", "nozz"],
    "HBTFDesign": ["inlet", "fan", "splitter", "lpc", "hpc", "burner",
                    "hpt", "lpt", "core_nozz"],
    "ABTurbojetDesign": ["inlet", "comp", "burner", "turb", "ab", "nozz"],
    "SingleTurboshaftDesign": ["inlet", "comp", "burner", "turb", "pt",
                               "nozz"],
    "MultiTurboshaftDesign": ["inlet", "lpc", "hpc_axi", "hpc_centri",
                              "burner", "hpt", "lpt", "pt", "nozz"],
    "MixedFlowDesign": ["inlet", "fan", "splitter", "lpc", "hpc", "burner",
                         "hpt", "lpt", "mixer", "ab", "nozz"],
}

# Bypass flow connections (source_elem -> target_elem).
_PYC_BYPASS_EDGES: dict[str, list[tuple[str, str]]] = {
    "HBTFDesign": [("splitter", "byp_nozz")],
    "MixedFlowDesign": [("splitter", "mixer")],
}

# Shaft connections: (shaft_label, [driven elements]).
_PYC_SHAFT_CONNECTIONS: dict[str, list[tuple[str, list[str]]]] = {
    "TurbojetDesign": [("Shaft", ["comp", "turb"])],
    "TurbojetMultipoint": [("Shaft", ["comp", "turb"])],
    "HBTFDesign": [("HP Shaft", ["hpc", "hpt"]),
                    ("LP Shaft", ["fan", "lpc", "lpt"])],
    "ABTurbojetDesign": [("Shaft", ["comp", "turb"])],
    "SingleTurboshaftDesign": [("HP Shaft", ["comp", "turb"]),
                               ("LP Shaft", ["pt"])],
    "MultiTurboshaftDesign": [("HP Shaft", ["hpc_axi", "hpc_centri", "hpt"]),
                              ("IP Shaft", ["lpc", "lpt"]),
                              ("LP Shaft", ["pt"])],
    "MixedFlowDesign": [("HP Shaft", ["hpc", "hpt"]),
                         ("LP Shaft", ["fan", "lpc", "lpt"])],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_plan_graph(plan: dict, plan_id: str = "", version: int = 0) -> dict:
    """Build a knowledge graph from a plan YAML dict.

    Args:
        plan: Parsed plan YAML dictionary.
        plan_id: Plan identifier (for labeling).
        version: Plan version number.

    Returns:
        Dict with plan_id, version, nodes (list), edges (list).
        Each node has: id, type, label, properties.
        Each edge has: source, target, relation, properties.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    meta = plan.get("metadata", {})
    pid = plan_id or meta.get("id", "plan")
    ver = version or meta.get("version", 0)

    # --- Plan root ---
    nodes.append({
        "id": "plan",
        "type": "plan",
        "label": f"{pid} v{ver}",
        "properties": {
            "id": pid,
            "name": meta.get("name", ""),
            "version": ver,
            "content_hash": meta.get("content_hash", ""),
        },
    })

    # Detect component family for conditional extraction
    comp_type = ""
    comp_config: dict = {}
    if plan.get("components"):
        comp_type = plan["components"][0].get("type", "")
        comp_config = plan["components"][0].get("config", {})

    # --- Flight conditions ---
    op = plan.get("operating_points", {})
    if op:
        parts = []
        if "Mach_number" in op:
            parts.append(f"M={op['Mach_number']}")
        if "MN" in op:
            parts.append(f"M={op['MN']}")
        if "alpha" in op:
            parts.append(f"a={op['alpha']}")
        if "velocity" in op:
            parts.append(f"V={op['velocity']} m/s")
        if "alt" in op:
            parts.append(f"alt={op['alt']} ft")
        if "Fn_target" in op:
            parts.append(f"Fn={op['Fn_target']} lbf")
        if "T4_target" in op:
            parts.append(f"T4={op['T4_target']} R")
        nodes.append({
            "id": "flight",
            "type": "flight_condition",
            "label": "\n".join(parts[:3]) if parts else "flight",
            "properties": op,
        })
        edges.append({
            "source": "plan", "target": "flight",
            "relation": "at_conditions", "properties": {},
        })

    # --- Component-family-specific extraction ---
    if comp_type.startswith("ocp/"):
        _extract_ocp_nodes(comp_config, comp_type, nodes, edges)
    elif comp_type.startswith("pyc/"):
        _extract_pyc_nodes(comp_config, comp_type, nodes, edges)

    # --- Surfaces (decomposed into geometry, material, FEM) ---
    surface_ids = []
    for comp in plan.get("components", []):
        for surf in comp.get("config", {}).get("surfaces", []):
            sname = surf.get("name", comp["id"])
            sid = f"surf-{sname}"
            surface_ids.append(sid)

            # Surface node (geometry identity)
            nodes.append({
                "id": sid,
                "type": "surface",
                "label": sname,
                "properties": {
                    "name": sname,
                    "wing_type": surf.get("wing_type", ""),
                    "span": surf.get("span"),
                    "root_chord": surf.get("root_chord"),
                    "symmetry": surf.get("symmetry"),
                    "sweep": surf.get("sweep"),
                    "dihedral": surf.get("dihedral"),
                    "taper": surf.get("taper"),
                },
            })
            edges.append({
                "source": "plan", "target": sid,
                "relation": "contains", "properties": {},
            })

            # Mesh node
            num_x = surf.get("num_x")
            num_y = surf.get("num_y")
            if num_x or num_y:
                mid = f"mesh-{sname}"
                nodes.append({
                    "id": mid,
                    "type": "mesh",
                    "label": f"{num_x}x{num_y} panels",
                    "properties": {"num_x": num_x, "num_y": num_y},
                })
                edges.append({
                    "source": sid, "target": mid,
                    "relation": "has_geometry", "properties": {},
                })

            # Material node
            mat_keys = {"E", "G", "yield_stress", "mrho"}
            mat_props = {k: surf[k] for k in mat_keys if k in surf}
            if mat_props:
                matid = f"mat-{sname}"
                # Build a readable label
                mat_label_parts = []
                if "E" in mat_props:
                    mat_label_parts.append(f"E={mat_props['E']:.0e}")
                if "yield_stress" in mat_props:
                    mat_label_parts.append(f"yield={mat_props['yield_stress']:.0e}")
                if "mrho" in mat_props:
                    mat_label_parts.append(f"rho={mat_props['mrho']}")
                nodes.append({
                    "id": matid,
                    "type": "material",
                    "label": "\n".join(mat_label_parts[:2]) if mat_label_parts else "material",
                    "properties": mat_props,
                })
                edges.append({
                    "source": sid, "target": matid,
                    "relation": "has_material", "properties": {},
                })

            # FEM model node
            fem_type = surf.get("fem_model_type")
            if fem_type:
                femid = f"fem-{sname}"
                fem_props = {"fem_model_type": fem_type}
                for k in ("thickness_cp", "spar_thickness_cp", "skin_thickness_cp"):
                    if k in surf:
                        fem_props[k] = surf[k]
                nodes.append({
                    "id": femid,
                    "type": "fem_model",
                    "label": fem_type,
                    "properties": fem_props,
                })
                edges.append({
                    "source": sid, "target": femid,
                    "relation": "has_fem", "properties": {},
                })

    # --- Solvers ---
    solvers = plan.get("solvers", {})
    if solvers:
        nl = solvers.get("nonlinear", {})
        ln = solvers.get("linear", {})
        if nl:
            nl_type = nl.get("type", "NonlinearSolver")
            nl_opts = nl.get("options", {})
            opt_parts = []
            if nl_opts.get("maxiter"):
                opt_parts.append(f"maxiter={nl_opts['maxiter']}")
            if nl_opts.get("atol"):
                opt_parts.append(f"atol={nl_opts['atol']}")
            nodes.append({
                "id": "nl-solver",
                "type": "solver",
                "label": f"{nl_type}\n{', '.join(opt_parts)}" if opt_parts else nl_type,
                "properties": {"type": nl_type, **nl_opts},
            })
            edges.append({
                "source": "plan", "target": "nl-solver",
                "relation": "uses_solver", "properties": {},
            })
        if ln:
            ln_type = ln.get("type", "LinearSolver")
            nodes.append({
                "id": "lin-solver",
                "type": "linear_solver",
                "label": ln_type,
                "properties": {"type": ln_type, **ln.get("options", {})},
            })
            if nl:
                edges.append({
                    "source": "nl-solver", "target": "lin-solver",
                    "relation": "uses_linear", "properties": {},
                })
            else:
                edges.append({
                    "source": "plan", "target": "lin-solver",
                    "relation": "uses_solver", "properties": {},
                })

    # --- Optimization ---
    obj = plan.get("objective")
    if obj:
        obj_name = obj.get("name", "?")
        obj_short = obj_name.split(".")[-1]
        nodes.append({
            "id": "objective",
            "type": "objective",
            "label": f"min {obj_short}",
            "properties": obj,
        })
        edges.append({
            "source": "plan", "target": "objective",
            "relation": "contains", "properties": {},
        })

    for dv in plan.get("design_variables", []):
        dv_name = dv.get("name", "?")
        dv_short = dv_name.split(".")[-1]
        dvid = f"dv-{dv_short}"
        lower = dv.get("lower", "")
        upper = dv.get("upper", "")
        nodes.append({
            "id": dvid,
            "type": "design_variable",
            "label": f"{dv_short}\n[{lower}, {upper}]",
            "properties": dv,
        })
        # DV acts_on the surface it modifies (match name prefix)
        target = None
        for sid in surface_ids:
            surf_name = sid.replace("surf-", "")
            if surf_name in dv_name:
                target = sid
                break
        if target:
            edges.append({
                "source": dvid, "target": target,
                "relation": "acts_on", "properties": {},
            })
        if obj:
            edges.append({
                "source": dvid, "target": "objective",
                "relation": "optimizes", "properties": {},
            })

    for con in plan.get("constraints", []):
        con_name = con.get("name", "?")
        con_short = con_name.split(".")[-1]
        conid = f"con-{con_short}"
        eq = con.get("equals")
        label = con_short + (f" = {eq}" if eq is not None else "")
        nodes.append({
            "id": conid,
            "type": "constraint",
            "label": label,
            "properties": con,
        })
        if obj:
            edges.append({
                "source": conid, "target": "objective",
                "relation": "bounds", "properties": {},
            })

    # --- Decisions ---
    node_ids = {n["id"] for n in nodes}

    for dec in plan.get("decisions", []):
        did = dec.get("id", f"dec-{plan.get('decisions', []).index(dec)}")
        decid = f"dec-{did}"
        text = dec.get("decision", "")
        stage = dec.get("stage", "")

        nodes.append({
            "id": decid,
            "type": "decision",
            "label": text[:35] if text else did,
            "properties": dec,
        })

        # Resolve element_path first (preferred); fall back to stage heuristic.
        target = _resolve_decision_target(
            dec, plan, node_ids, surface_ids, nodes, edges,
        )
        if target is None:
            target = _stage_target(stage, node_ids)
        if target is None:
            target = "plan"

        edges.append({
            "source": decid, "target": target,
            "relation": "justifies", "properties": {},
        })

    # --- Requirements + acceptance criteria ---
    for req in plan.get("requirements", []):
        if not isinstance(req, dict):
            continue
        rid = req.get("id", "req")
        reqid = f"req-{rid}"
        nodes.append({
            "id": reqid,
            "type": "requirement",
            "label": f"{rid}\n{req.get('text', '')[:30]}",
            "properties": req,
        })
        edges.append({
            "source": "plan", "target": reqid,
            "relation": "contains", "properties": {},
        })
        for idx, crit in enumerate(req.get("acceptance_criteria") or []):
            if not isinstance(crit, dict):
                continue
            metric = crit.get("metric", f"c{idx}")
            cid = f"crit-{rid}-{metric}"
            label_parts = [metric]
            if "comparator" in crit and "threshold" in crit:
                label_parts.append(f"{crit['comparator']} {crit['threshold']}")
            elif "comparator" in crit and "range" in crit:
                label_parts.append(f"{crit['comparator']} {crit['range']}")
            nodes.append({
                "id": cid,
                "type": "acceptance_criterion",
                "label": "\n".join(label_parts),
                "properties": crit,
            })
            edges.append({
                "source": reqid, "target": cid,
                "relation": "has_criterion", "properties": {},
            })

    # --- Analysis plan phases ---
    ap = plan.get("analysis_plan")
    if isinstance(ap, dict):
        phases = ap.get("phases") or []
        phase_ids = {
            p.get("id") for p in phases
            if isinstance(p, dict) and p.get("id")
        }
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            pid_ = phase.get("id")
            if not pid_:
                continue
            phid = f"phase-{pid_}"
            label = phase.get("name") or pid_
            mode = phase.get("mode")
            if mode:
                label = f"{label}\n({mode})"
            nodes.append({
                "id": phid,
                "type": "phase",
                "label": label,
                "properties": phase,
            })
            edges.append({
                "source": "plan", "target": phid,
                "relation": "contains", "properties": {},
            })
            for dep in phase.get("depends_on") or []:
                if dep in phase_ids:
                    edges.append({
                        "source": f"phase-{dep}", "target": phid,
                        "relation": "precedes", "properties": {},
                    })

    return {
        "plan_id": pid,
        "version": ver,
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Decision target resolution
# ---------------------------------------------------------------------------


def _stage_target(stage: str, node_ids: set[str]) -> str | None:
    """Legacy heuristic: map a decision stage string to a graph-node id.

    Kept as a fallback when element_path is absent or fails to resolve.
    """
    if not stage:
        return None
    if "mesh" in stage:
        for nid in node_ids:
            if nid.startswith("mesh-"):
                return nid
    if "material" in stage:
        for nid in node_ids:
            if nid.startswith("mat-"):
                return nid
    if "fem" in stage or "structural" in stage:
        for nid in node_ids:
            if nid.startswith("fem-"):
                return nid
    if "solver" in stage and "nl-solver" in node_ids:
        return "nl-solver"
    if "optimizer" in stage and "nl-solver" in node_ids:
        return "nl-solver"
    return None


def _resolve_decision_target(
    decision: dict,
    plan: dict,
    node_ids: set[str],
    surface_ids: list[str],
    nodes: list[dict],
    edges: list[dict],
) -> str | None:
    """Resolve a decision's element_path to an existing graph node id.

    If the path resolves to an element that maps to an existing node in
    the graph (mesh, material, FEM, DV, constraint, objective, solver,
    surface, requirement, phase), return that node's id. If the path
    resolves but points at an element without a dedicated node, create
    a synthetic ``elem-`` node so the ``justifies`` edge has a concrete
    target. Return None when element_path is absent or unresolvable so
    the caller can fall back to the stage heuristic.
    """
    from hangar.omd.plan_paths import resolve_element_path

    path = decision.get("element_path")
    if not path:
        return None
    resolved = resolve_element_path(plan, path)
    if resolved is None:
        return None

    target = _element_path_to_node_id(path, resolved, node_ids, surface_ids)
    if target is not None:
        return target

    # Synthesize a node for this element so the graph still renders the
    # justifies edge against a concrete target.
    safe_key = resolved.entity_key.replace("[", "_").replace("]", "").replace(".", "_")
    synth_id = f"elem-{safe_key}"
    if synth_id not in node_ids:
        nodes.append({
            "id": synth_id,
            "type": "plan_element",
            "label": resolved.entity_key,
            "properties": {
                "element_path": path,
                "entity_kind": resolved.entity_kind,
            },
        })
        edges.append({
            "source": "plan", "target": synth_id,
            "relation": "contains", "properties": {},
        })
        node_ids.add(synth_id)
    return synth_id


def _element_path_to_node_id(
    path: str,
    resolved,
    node_ids: set[str],
    surface_ids: list[str],
) -> str | None:
    """Map a resolved element_path to an existing graph-node id, if any."""
    # design_variables[name] / design_variables[name].<field>
    if path.startswith("design_variables["):
        name = _bracket_value(path, "design_variables")
        if name:
            short = name.split(".")[-1]
            candidate = f"dv-{short}"
            if candidate in node_ids:
                return candidate
    if path.startswith("constraints["):
        name = _bracket_value(path, "constraints")
        if name:
            short = name.split(".")[-1]
            candidate = f"con-{short}"
            if candidate in node_ids:
                return candidate
    if path == "objective" or path.startswith("objective."):
        if "objective" in node_ids:
            return "objective"
    if path.startswith("solvers.nonlinear") and "nl-solver" in node_ids:
        return "nl-solver"
    if path.startswith("solvers.linear") and "lin-solver" in node_ids:
        return "lin-solver"
    if path.startswith("requirements["):
        name = _bracket_value(path, "requirements")
        if name and f"req-{name}" in node_ids:
            return f"req-{name}"
    if path.startswith("analysis_plan.phases["):
        name = _bracket_value(path, "phases")
        if name and f"phase-{name}" in node_ids:
            return f"phase-{name}"
    # Surface-scoped paths: components[X].config.surfaces[Y].<field>
    if path.startswith("components[") and ".surfaces[" in path:
        surf_name = _bracket_value_after(path, ".surfaces")
        if not surf_name:
            return None
        surf_id = f"surf-{surf_name}"
        tail = path.split(".surfaces[", 1)[1].split("]", 1)[-1].lstrip(".")
        if tail in {"num_x", "num_y"} and f"mesh-{surf_name}" in node_ids:
            return f"mesh-{surf_name}"
        if tail in {"E", "G", "yield_stress", "mrho"} and f"mat-{surf_name}" in node_ids:
            return f"mat-{surf_name}"
        if tail in {
            "fem_model_type", "thickness_cp",
            "spar_thickness_cp", "skin_thickness_cp",
        } and f"fem-{surf_name}" in node_ids:
            return f"fem-{surf_name}"
        if surf_id in node_ids:
            return surf_id
    return None


def _bracket_value(path: str, head: str) -> str | None:
    """Extract 'wing' from 'components[wing].config.num_y' given head='components'."""
    prefix = f"{head}["
    if not path.startswith(prefix):
        return None
    end = path.find("]", len(prefix))
    if end < 0:
        return None
    return path[len(prefix):end]


def _bracket_value_after(path: str, marker: str) -> str | None:
    """Extract the bracketed value immediately after a .marker segment."""
    needle = f"{marker}["
    idx = path.find(needle)
    if idx < 0:
        return None
    start = idx + len(needle)
    end = path.find("]", start)
    if end < 0:
        return None
    return path[start:end]


# ---------------------------------------------------------------------------
# OCP plan extraction
# ---------------------------------------------------------------------------


def _extract_ocp_nodes(
    config: dict, comp_type: str, nodes: list[dict], edges: list[dict],
) -> None:
    """Extract OCP aircraft/mission/slot/solver nodes from plan config."""

    # --- Aircraft config ---
    template = config.get("aircraft_template", "")
    aircraft_data = config.get("aircraft_data", {})

    ac_props: dict = {}
    ac_label = "Aircraft"

    if template and template in _OCP_TEMPLATE_SUMMARY:
        summary = _OCP_TEMPLATE_SUMMARY[template]
        ac_label = summary["label"]
        ac_props = dict(summary)
    elif aircraft_data:
        # Extract key values from inline nested dict
        ac = aircraft_data.get("ac", {})
        geom = ac.get("geom", {})
        weights = ac.get("weights", {})
        wing = geom.get("wing", {})

        s_ref = wing.get("S_ref", {})
        if isinstance(s_ref, dict):
            ac_props["S_ref"] = s_ref.get("value")
            ac_props["S_ref_units"] = s_ref.get("units", "m**2")
        ar = wing.get("AR", {})
        if isinstance(ar, dict):
            ac_props["AR"] = ar.get("value")

        mtow = weights.get("MTOW", {})
        if isinstance(mtow, dict):
            ac_props["MTOW_kg"] = mtow.get("value")
        oew = weights.get("OEW", {})
        if isinstance(oew, dict):
            ac_props["OEW_kg"] = oew.get("value")

        # Build label from available data
        parts = []
        if ac_props.get("S_ref"):
            parts.append(f"S={ac_props['S_ref']} m2")
        if ac_props.get("MTOW_kg"):
            parts.append(f"MTOW={ac_props['MTOW_kg']} kg")
        ac_label = "\n".join(parts) if parts else "Aircraft (inline)"
    elif template:
        ac_label = template

    nodes.append({
        "id": "aircraft_config",
        "type": "aircraft_config",
        "label": ac_label,
        "properties": ac_props,
    })
    edges.append({
        "source": "plan", "target": "aircraft_config",
        "relation": "contains", "properties": {},
    })

    # --- Architecture ---
    architecture = config.get("architecture", "")
    if architecture:
        nodes.append({
            "id": "architecture",
            "type": "propulsion_architecture",
            "label": architecture,
            "properties": {"architecture": architecture},
        })
        edges.append({
            "source": "aircraft_config", "target": "architecture",
            "relation": "has_architecture", "properties": {},
        })

    # --- Mission profile ---
    mp = config.get("mission_params", {})
    num_nodes = config.get("num_nodes")
    phases = _OCP_MISSION_PHASES.get(comp_type, ["climb", "cruise", "descent"])

    alt = mp.get("cruise_altitude_ft", "")
    rng = mp.get("mission_range_NM", "")
    label_parts = []
    if alt:
        label_parts.append(f"{alt} ft")
    if rng:
        label_parts.append(f"{rng} NM")
    if num_nodes:
        label_parts.append(f"{num_nodes} nodes")

    nodes.append({
        "id": "mission_profile",
        "type": "mission_profile",
        "label": "\n".join(label_parts) if label_parts else comp_type,
        "properties": {**mp, "num_nodes": num_nodes, "phases": phases},
    })
    edges.append({
        "source": "plan", "target": "mission_profile",
        "relation": "contains", "properties": {},
    })

    # --- Slot providers ---
    slots = config.get("slots", {})
    for slot_name, slot_cfg in slots.items():
        provider = slot_cfg.get("provider", "")
        slot_config = slot_cfg.get("config", {})
        sid = f"slot-{slot_name}"

        # Build label with key config values
        label = f"{slot_name}: {provider}" if provider else slot_name

        nodes.append({
            "id": sid,
            "type": "slot_provider",
            "label": label,
            "properties": {"provider": provider, "slot": slot_name, **slot_config},
        })
        edges.append({
            "source": "plan", "target": sid,
            "relation": "contains", "properties": {},
        })
        edges.append({
            "source": sid, "target": "mission_profile",
            "relation": "provides", "properties": {},
        })

        # Decompose slot internals into sub-nodes
        _decompose_slot(slot_name, slot_cfg, ac_props, nodes, edges)

    # --- Solver settings ---
    solver_settings = config.get("solver_settings", {})
    if solver_settings:
        solver_type = solver_settings.get("solver_type", "newton")
        maxiter = solver_settings.get("maxiter", "")
        atol = solver_settings.get("atol", "")

        opt_parts = []
        if maxiter:
            opt_parts.append(f"maxiter={maxiter}")
        if atol:
            opt_parts.append(f"atol={atol}")

        nodes.append({
            "id": "nl-solver",
            "type": "solver",
            "label": f"{solver_type}\n{', '.join(opt_parts)}" if opt_parts else solver_type,
            "properties": solver_settings,
        })
        edges.append({
            "source": "plan", "target": "nl-solver",
            "relation": "uses_solver", "properties": {},
        })


# ---------------------------------------------------------------------------
# pyCycle plan extraction
# ---------------------------------------------------------------------------


def _extract_pyc_nodes(
    config: dict, comp_type: str, nodes: list[dict], edges: list[dict],
) -> None:
    """Extract pyCycle engine config and element nodes from plan config."""

    # Derive archetype from component type (e.g. "pyc/TurbojetDesign" -> "TurbojetDesign")
    archetype = comp_type.split("/", 1)[-1] if "/" in comp_type else comp_type

    # --- Engine config node ---
    label = _PYC_ARCHETYPE_LABEL.get(archetype, archetype)
    display_keys = _PYC_DISPLAY_KEYS.get(archetype, [])

    # Build label with key parameter values
    param_parts = []
    for key in display_keys:
        val = config.get(key)
        if val is not None:
            if isinstance(val, float):
                param_parts.append(f"{key}={val:.3g}")
            else:
                param_parts.append(f"{key}={val}")
    if param_parts:
        label += "\n" + ", ".join(param_parts[:3])
        if len(param_parts) > 3:
            label += f" +{len(param_parts) - 3}"

    engine_props = {k: config[k] for k in display_keys if k in config}
    engine_props["archetype"] = archetype

    nodes.append({
        "id": "engine_config",
        "type": "engine_config",
        "label": label,
        "properties": engine_props,
    })
    edges.append({
        "source": "plan", "target": "engine_config",
        "relation": "contains", "properties": {},
    })

    # --- Engine element nodes ---
    elements = _PYC_ELEMENTS.get(archetype, [])
    element_ids = set()
    for elem_id, elem_label in elements:
        nid = f"elem-{elem_id}"
        element_ids.add(nid)
        nodes.append({
            "id": nid,
            "type": "engine_element",
            "label": elem_label,
            "properties": {"element_id": elem_id},
        })
        edges.append({
            "source": "engine_config", "target": nid,
            "relation": "contains", "properties": {},
        })

    # --- Streamwise flow edges ---
    flow_order = _PYC_FLOW_ORDER.get(archetype, [])
    for i in range(len(flow_order) - 1):
        src = f"elem-{flow_order[i]}"
        tgt = f"elem-{flow_order[i + 1]}"
        if src in element_ids and tgt in element_ids:
            edges.append({
                "source": src, "target": tgt,
                "relation": "flow_to", "properties": {},
            })

    # --- Bypass flow edges ---
    for src_id, tgt_id in _PYC_BYPASS_EDGES.get(archetype, []):
        src = f"elem-{src_id}"
        tgt = f"elem-{tgt_id}"
        if src in element_ids and tgt in element_ids:
            edges.append({
                "source": src, "target": tgt,
                "relation": "flow_to", "properties": {"path": "bypass"},
            })

    # --- Shaft coupling edges ---
    for shaft_label, driven_elems in _PYC_SHAFT_CONNECTIONS.get(archetype, []):
        for elem_id in driven_elems:
            nid = f"elem-{elem_id}"
            if nid in element_ids:
                edges.append({
                    "source": nid, "target": nid,
                    "relation": "couples",
                    "properties": {"shaft": shaft_label},
                })


# ---------------------------------------------------------------------------
# Slot internal decomposition
# ---------------------------------------------------------------------------


def _decompose_slot(
    slot_name: str,
    slot_cfg: dict,
    aircraft_props: dict,
    nodes: list[dict],
    edges: list[dict],
) -> None:
    """Decompose a slot provider into sub-nodes showing its internal structure.

    For OAS drag slots: surface geometry + mesh sub-nodes.
    For pyCycle direct slots: engine element sub-nodes with flow edges.
    For pyCycle surrogate slots: archetype + deck description sub-nodes.
    """
    provider = slot_cfg.get("provider", "")
    config = slot_cfg.get("config", {})
    sid = f"slot-{slot_name}"

    if provider.startswith("oas/"):
        _decompose_oas_slot(sid, config, aircraft_props, nodes, edges)
    elif provider in ("pyc/turbojet", "pyc/hbtf"):
        _decompose_pyc_direct_slot(sid, provider, config, nodes, edges)
    elif provider == "pyc/surrogate":
        _decompose_pyc_surrogate_slot(sid, config, nodes, edges)


def _decompose_oas_slot(
    sid: str,
    config: dict,
    aircraft_props: dict,
    nodes: list[dict],
    edges: list[dict],
) -> None:
    """Add OAS surface/mesh sub-nodes under a drag slot."""
    surf_id = f"{sid}-surf"
    mesh_id = f"{sid}-mesh"

    # Build surface properties from aircraft config
    surf_props: dict = {}
    for key in ("S_ref", "AR", "span", "root_chord", "sweep", "taper",
                "symmetry", "dihedral"):
        if key in aircraft_props:
            surf_props[key] = aircraft_props[key]

    # Surface label
    parts = []
    if surf_props.get("S_ref"):
        parts.append(f"S={surf_props['S_ref']} m2")
    if surf_props.get("AR"):
        parts.append(f"AR={surf_props['AR']}")
    surf_label = "\n".join(parts) if parts else "wing"

    nodes.append({
        "id": surf_id,
        "type": "surface",
        "label": surf_label,
        "properties": surf_props,
    })
    edges.append({
        "source": sid, "target": surf_id,
        "relation": "contains", "properties": {},
    })

    # Reference edge from aircraft config
    edges.append({
        "source": "aircraft_config", "target": surf_id,
        "relation": "configures", "properties": {},
    })

    # Mesh sub-node
    num_x = config.get("num_x")
    num_y = config.get("num_y")
    if num_x or num_y:
        mesh_props: dict = {"num_x": num_x, "num_y": num_y}
        if config.get("num_twist"):
            mesh_props["num_twist"] = config["num_twist"]

        nodes.append({
            "id": mesh_id,
            "type": "mesh",
            "label": f"{num_x}x{num_y} panels",
            "properties": mesh_props,
        })
        edges.append({
            "source": surf_id, "target": mesh_id,
            "relation": "has_geometry", "properties": {},
        })

    # Material/FEM sub-nodes for aerostruct slots
    mat_keys = {"E", "G", "yield_stress", "mrho"}
    mat_props = {k: config[k] for k in mat_keys if k in config}
    if mat_props:
        mat_id = f"{sid}-mat"
        mat_label_parts = []
        if "E" in mat_props:
            mat_label_parts.append(f"E={mat_props['E']:.0e}")
        if "yield_stress" in mat_props:
            mat_label_parts.append(f"yield={mat_props['yield_stress']:.0e}")
        nodes.append({
            "id": mat_id,
            "type": "material",
            "label": "\n".join(mat_label_parts[:2]) if mat_label_parts else "material",
            "properties": mat_props,
        })
        edges.append({
            "source": surf_id, "target": mat_id,
            "relation": "has_material", "properties": {},
        })

    fem_type = config.get("fem_model_type")
    if fem_type:
        fem_id = f"{sid}-fem"
        nodes.append({
            "id": fem_id,
            "type": "fem_model",
            "label": fem_type,
            "properties": {"fem_model_type": fem_type},
        })
        edges.append({
            "source": surf_id, "target": fem_id,
            "relation": "has_fem", "properties": {},
        })


def _decompose_pyc_direct_slot(
    sid: str,
    provider: str,
    config: dict,
    nodes: list[dict],
    edges: list[dict],
) -> None:
    """Add pyCycle engine element sub-nodes under a direct-coupled slot."""
    # Map provider to archetype
    archetype_map = {
        "pyc/turbojet": "TurbojetDesign",
        "pyc/hbtf": "HBTFDesign",
    }
    archetype = archetype_map.get(provider)
    if not archetype:
        return

    elements = _PYC_ELEMENTS.get(archetype, [])
    element_ids = set()
    for elem_id, elem_label in elements:
        nid = f"{sid}-elem-{elem_id}"
        element_ids.add(nid)
        nodes.append({
            "id": nid,
            "type": "engine_element",
            "label": elem_label,
            "properties": {"element_id": elem_id},
        })
        edges.append({
            "source": sid, "target": nid,
            "relation": "contains", "properties": {},
        })

    # Flow edges
    flow_order = _PYC_FLOW_ORDER.get(archetype, [])
    for i in range(len(flow_order) - 1):
        src = f"{sid}-elem-{flow_order[i]}"
        tgt = f"{sid}-elem-{flow_order[i + 1]}"
        if src in element_ids and tgt in element_ids:
            edges.append({
                "source": src, "target": tgt,
                "relation": "flow_to", "properties": {},
            })

    # Bypass edges
    for src_id, tgt_id in _PYC_BYPASS_EDGES.get(archetype, []):
        src = f"{sid}-elem-{src_id}"
        tgt = f"{sid}-elem-{tgt_id}"
        if src in element_ids and tgt in element_ids:
            edges.append({
                "source": src, "target": tgt,
                "relation": "flow_to", "properties": {"path": "bypass"},
            })


def _decompose_pyc_surrogate_slot(
    sid: str,
    config: dict,
    nodes: list[dict],
    edges: list[dict],
) -> None:
    """Add archetype + deck sub-nodes under a pyCycle surrogate slot."""
    arch_id = f"{sid}-archetype"
    deck_id = f"{sid}-deck"

    archetype = config.get("archetype", "turbojet")
    design_alt = config.get("design_alt", "")
    design_MN = config.get("design_MN", "")
    design_Fn = config.get("design_Fn", "")
    design_T4 = config.get("design_T4", "")

    # Archetype node with design point conditions
    arch_parts = [archetype]
    if design_alt:
        arch_parts.append(f"alt={design_alt} ft")
    if design_MN:
        arch_parts.append(f"MN={design_MN}")

    arch_props = {"archetype": archetype}
    for key in ("design_alt", "design_MN", "design_Fn", "design_T4",
                "thermo_method"):
        if key in config:
            arch_props[key] = config[key]

    nodes.append({
        "id": arch_id,
        "type": "engine_config",
        "label": "\n".join(arch_parts[:2]),
        "properties": arch_props,
    })
    edges.append({
        "source": sid, "target": arch_id,
        "relation": "contains", "properties": {},
    })

    # Deck grid description
    grid_spec = config.get("grid_spec", {})
    if grid_spec:
        grid_parts = []
        for key, vals in grid_spec.items():
            if isinstance(vals, list):
                grid_parts.append(f"{key}: {len(vals)} pts")
        deck_label = "Surrogate Deck\n" + ", ".join(grid_parts) if grid_parts else "Surrogate Deck"

        nodes.append({
            "id": deck_id,
            "type": "surrogate_deck",
            "label": deck_label,
            "properties": grid_spec,
        })
        edges.append({
            "source": arch_id, "target": deck_id,
            "relation": "generates", "properties": {},
        })
