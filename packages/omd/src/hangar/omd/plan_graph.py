"""Build a knowledge graph from a plan YAML dict.

Produces a typed entity-relationship graph with nodes (typed entities)
and edges (named relationships). The graph data contract is designed
to be replaceable by a TypeDB query returning the same structure.

Graph schema:
    Node types: plan, surface, material, fem_model, mesh, flight_condition,
                solver, linear_solver, objective, design_variable, constraint,
                decision, requirement
    Edge types: contains, has_geometry, has_material, has_fem, uses_solver,
                uses_linear, at_conditions, acts_on, bounds, justifies,
                traces_to
"""

from __future__ import annotations


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

    # --- Flight conditions ---
    op = plan.get("operating_points", {})
    if op:
        parts = []
        if "Mach_number" in op:
            parts.append(f"M={op['Mach_number']}")
        if "alpha" in op:
            parts.append(f"a={op['alpha']}")
        if "velocity" in op:
            parts.append(f"V={op['velocity']} m/s")
        nodes.append({
            "id": "flight",
            "type": "flight_condition",
            "label": "\n".join(parts[:2]) if parts else "flight",
            "properties": op,
        })
        edges.append({
            "source": "plan", "target": "flight",
            "relation": "at_conditions", "properties": {},
        })

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
    # Build a lookup for stage -> node ID for decision linking
    stage_targets = {}
    for sid in surface_ids:
        sname = sid.replace("surf-", "")
        stage_targets[f"mesh-{sname}"] = f"mesh-{sname}"
        stage_targets[f"mat-{sname}"] = f"mat-{sname}"
        stage_targets[f"fem-{sname}"] = f"fem-{sname}"

    node_ids = {n["id"] for n in nodes}

    for dec in plan.get("decisions", []):
        did = dec.get("id", f"dec-{plan.get('decisions', []).index(dec)}")
        decid = f"dec-{did}"
        text = dec.get("decision", "")
        reason = dec.get("reason", "")
        stage = dec.get("stage", "")

        nodes.append({
            "id": decid,
            "type": "decision",
            "label": text[:35] if text else did,
            "properties": dec,
        })

        # Link decision to the node it justifies based on stage
        target = "plan"  # default
        if "mesh" in stage:
            # Link to first mesh node
            for nid in node_ids:
                if nid.startswith("mesh-"):
                    target = nid
                    break
        elif "material" in stage:
            for nid in node_ids:
                if nid.startswith("mat-"):
                    target = nid
                    break
        elif "fem" in stage or "structural" in stage:
            for nid in node_ids:
                if nid.startswith("fem-"):
                    target = nid
                    break
        elif "solver" in stage:
            if "nl-solver" in node_ids:
                target = "nl-solver"

        edges.append({
            "source": decid, "target": target,
            "relation": "justifies", "properties": {},
        })

    # --- Requirements ---
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

    return {
        "plan_id": pid,
        "version": ver,
        "nodes": nodes,
        "edges": edges,
    }
