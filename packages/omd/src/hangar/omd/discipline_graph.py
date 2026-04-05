"""Build discipline-level analysis flow graphs.

Produces a curated engineering view of what physics ran, in what order,
exchanging what data. Each factory type has a domain-specific discipline
map. Runtime data (surface names, solver iterations) enriches the static
map.

Graph schema matches plan_graph.py: {nodes, edges} with typed entities
and named relationships. Designed to be replaceable by a TypeDB query.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Curated discipline maps per component type
# ---------------------------------------------------------------------------

_AEROSTRUCT_MAP = {
    "nodes": [
        {
            "id": "geometry",
            "type": "discipline",
            "label": "Geometry",
            "properties": {
                "description": "Mesh parametrization from control points",
                "physics": "mesh_generation",
                "method": "B-spline interpolation",
                "inputs": ["twist_cp", "thickness_cp", "chord_cp"],
                "outputs": ["mesh", "nodes", "radius", "t_over_c"],
            },
        },
        {
            "id": "aero",
            "type": "discipline",
            "label": "Aerodynamics",
            "properties": {
                "description": "Vortex Lattice Method for pressure distribution",
                "physics": "potential_flow",
                "method": "VLM (panel method)",
                "inputs": ["deformed_mesh", "alpha", "Mach_number", "velocity", "rho"],
                "outputs": ["CL", "CD", "pressures", "spanwise_cl", "forces"],
            },
        },
        {
            "id": "struct",
            "type": "discipline",
            "label": "Structures",
            "properties": {
                "description": "Finite Element Method for deflection and stress",
                "physics": "linear_elasticity",
                "method": "FEM (tube or wingbox)",
                "inputs": ["nodes", "aero_loads", "stiffness_matrix"],
                "outputs": ["displacements", "stresses", "failure"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Aggregated aero and structural metrics",
                "physics": "post_processing",
                "method": "algebraic aggregation",
                "inputs": ["CL", "CD", "structural_mass", "failure"],
                "outputs": ["L/D", "fuel_burn", "total_weight", "L_equals_W"],
            },
        },
    ],
    "coupling": {
        "id": "coupling",
        "disciplines": ["aero", "struct"],
        "solver": "NewtonSolver",
        "label": "Aero-Struct Coupling",
        "exchanges": [
            {"from": "aero", "to": "struct", "data": ["aero loads", "pressures"]},
            {"from": "struct", "to": "aero", "data": ["deformed mesh", "displacements"]},
        ],
    },
    "flow": [
        {"from": "geometry", "to": "aero",
         "variables": ["mesh", "t_over_c"]},
        {"from": "geometry", "to": "struct",
         "variables": ["nodes", "radius", "local_stiff"]},
        {"from": "aero", "to": "perf",
         "variables": ["CL", "CD"]},
        {"from": "struct", "to": "perf",
         "variables": ["structural_mass", "failure"]},
    ],
}

_AERO_MAP = {
    "nodes": [
        {
            "id": "geometry",
            "type": "discipline",
            "label": "Geometry",
            "properties": {
                "description": "Mesh parametrization from control points",
                "physics": "mesh_generation",
                "method": "B-spline interpolation",
                "inputs": ["twist_cp", "chord_cp"],
                "outputs": ["mesh", "t_over_c"],
            },
        },
        {
            "id": "aero",
            "type": "discipline",
            "label": "Aerodynamics",
            "properties": {
                "description": "Vortex Lattice Method for pressure distribution",
                "physics": "potential_flow",
                "method": "VLM (panel method)",
                "inputs": ["mesh", "alpha", "Mach_number", "velocity", "rho"],
                "outputs": ["CL", "CD", "CM", "spanwise_cl"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Aggregated aerodynamic metrics",
                "physics": "post_processing",
                "method": "algebraic aggregation",
                "inputs": ["CL", "CD"],
                "outputs": ["L/D"],
            },
        },
    ],
    "coupling": None,
    "flow": [
        {"from": "geometry", "to": "aero",
         "variables": ["mesh", "t_over_c"]},
        {"from": "aero", "to": "perf",
         "variables": ["CL", "CD"]},
    ],
}

_COMPONENT_MAPS = {
    "oas/AerostructPoint": _AEROSTRUCT_MAP,
    "oas/AeroPoint": _AERO_MAP,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_discipline_graph(
    component_type: str,
    metadata: dict | None = None,
    solver_info: dict | None = None,
) -> dict:
    """Build a discipline-level analysis flow graph.

    Args:
        component_type: Factory component type (e.g. "oas/AerostructPoint").
        metadata: Factory metadata with surface_names, flight_conditions, etc.
        solver_info: Optional solver event data (iterations, residuals).

    Returns:
        Dict with nodes and edges following the plan_graph.py contract.
    """
    dmap = _COMPONENT_MAPS.get(component_type)
    if dmap is None:
        return _fallback_graph(component_type)

    metadata = metadata or {}
    solver_info = solver_info or {}

    nodes = []
    edges = []

    # --- Discipline nodes ---
    for dnode in dmap["nodes"]:
        node = {
            "id": dnode["id"],
            "type": dnode["type"],
            "label": dnode["label"],
            "properties": dict(dnode["properties"]),
        }
        # Enrich with runtime metadata
        _enrich_discipline(node, metadata)
        nodes.append(node)

    # --- Coupling loop node ---
    coupling = dmap.get("coupling")
    if coupling:
        coup_label = coupling["label"]
        coup_props = {
            "solver": coupling["solver"],
            "disciplines": coupling["disciplines"],
        }

        # Solver iteration info from runtime
        iters = solver_info.get("iterations")
        status = solver_info.get("convergence_status", "")
        if iters is not None:
            coup_label += f"\n{iters} iterations"
            coup_props["iterations"] = iters
        if status:
            coup_props["convergence_status"] = status
        residual = solver_info.get("final_residual")
        if residual is not None:
            coup_props["final_residual"] = residual

        nodes.append({
            "id": coupling["id"],
            "type": "coupling_loop",
            "label": coup_label,
            "properties": coup_props,
        })

        # Coupling exchange edges (bidirectional inside the loop)
        for exch in coupling.get("exchanges", []):
            data_label = ", ".join(exch["data"])
            edges.append({
                "source": exch["from"],
                "target": exch["to"],
                "relation": "couples",
                "properties": {"variables": exch["data"]},
            })

        # Flow edges into and out of the coupling loop
        coupled_set = set(coupling["disciplines"])
        for flow in dmap["flow"]:
            src = flow["from"]
            tgt = flow["to"]
            var_label = ", ".join(flow["variables"][:4])
            if len(flow["variables"]) > 4:
                var_label += f" +{len(flow['variables']) - 4}"

            if src in coupled_set and tgt not in coupled_set:
                # From coupled discipline to outside: route through coupling node
                edges.append({
                    "source": coupling["id"], "target": tgt,
                    "relation": "provides",
                    "properties": {"variables": flow["variables"]},
                })
            elif tgt in coupled_set and src not in coupled_set:
                # From outside to coupled discipline: route through coupling node
                edges.append({
                    "source": src, "target": coupling["id"],
                    "relation": "provides",
                    "properties": {"variables": flow["variables"]},
                })
            else:
                # Both outside coupling, or both inside (shouldn't happen with this map)
                edges.append({
                    "source": src, "target": tgt,
                    "relation": "provides",
                    "properties": {"variables": flow["variables"]},
                })
    else:
        # No coupling -- direct flow edges
        for flow in dmap["flow"]:
            edges.append({
                "source": flow["from"],
                "target": flow["to"],
                "relation": "provides",
                "properties": {"variables": flow["variables"]},
            })

    return {"nodes": nodes, "edges": edges}


def _enrich_discipline(node: dict, metadata: dict) -> None:
    """Add runtime-specific data to a discipline node."""
    props = node["properties"]
    did = node["id"]

    surface_names = metadata.get("surface_names", [])
    flight = metadata.get("flight_conditions", {})

    if did == "geometry" and surface_names:
        props["surfaces"] = surface_names

    if did == "aero" and flight:
        props["flight_conditions"] = {
            k: flight[k] for k in ("velocity", "alpha", "Mach_number", "rho", "re")
            if k in flight
        }

    if did == "struct":
        # Get FEM type and material from surface metadata
        for surf in metadata.get("surfaces", []):
            if isinstance(surf, dict):
                fem = surf.get("fem_model_type")
                if fem:
                    props["fem_type"] = fem
                    node["label"] = f"Structures ({fem})"
                for mk in ("E", "G", "yield_stress", "mrho"):
                    if mk in surf:
                        props[mk] = surf[mk]
                break


def _fallback_graph(component_type: str) -> dict:
    """Return a minimal single-node graph for unknown component types."""
    return {
        "nodes": [{
            "id": "component",
            "type": "discipline",
            "label": component_type,
            "properties": {"description": f"Unknown component type: {component_type}"},
        }],
        "edges": [],
    }
