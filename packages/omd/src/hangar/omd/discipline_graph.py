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

# ---------------------------------------------------------------------------
# OCP mission map
# ---------------------------------------------------------------------------

_OCP_MISSION_MAP = {
    "nodes": [
        {
            "id": "aircraft_config",
            "type": "discipline",
            "label": "Aircraft Config",
            "properties": {
                "description": "Aircraft geometry, weights, and aero coefficients",
                "physics": "configuration",
                "method": "DictIndepVarComp",
                "inputs": [],
                "outputs": ["S_ref", "AR", "MTOW", "OEW", "CD0", "e"],
            },
        },
        {
            "id": "aero",
            "type": "discipline",
            "label": "Aerodynamics",
            "properties": {
                "description": "Drag model from polar or slot provider",
                "physics": "aerodynamics",
                "method": "PolarDrag",
                "inputs": ["fltcond|CL", "fltcond|q", "S_ref", "AR", "CD0", "e"],
                "outputs": ["drag"],
            },
        },
        {
            "id": "propulsion",
            "type": "discipline",
            "label": "Propulsion",
            "properties": {
                "description": "Propulsion system model",
                "physics": "thermodynamics",
                "method": "architecture-specific",
                "inputs": ["throttle", "fltcond|h", "fltcond|Utrue"],
                "outputs": ["thrust", "fuel_flow"],
            },
        },
        {
            "id": "weight",
            "type": "discipline",
            "label": "Weight",
            "properties": {
                "description": "Empty weight estimation",
                "physics": "structures",
                "method": "EmptyWeight",
                "inputs": ["ac|geom|*", "ac|propulsion|*"],
                "outputs": ["OEW"],
            },
        },
        {
            "id": "mission",
            "type": "discipline",
            "label": "Mission Integration",
            "properties": {
                "description": "Trajectory integration across phases",
                "physics": "flight_mechanics",
                "method": "Simpson's rule integration",
                "inputs": ["thrust", "drag", "OEW", "fltcond|*"],
                "outputs": ["fuel_burn", "range", "fuel_used_final"],
            },
        },
    ],
    "coupling": {
        "id": "coupling",
        "disciplines": ["aero", "propulsion", "mission"],
        "solver": "NewtonSolver",
        "label": "Mission Coupling",
        "exchanges": [
            {"from": "mission", "to": "aero", "data": ["fltcond|CL", "fltcond|q"]},
            {"from": "mission", "to": "propulsion", "data": ["throttle", "fltcond|*"]},
            {"from": "aero", "to": "mission", "data": ["drag"]},
            {"from": "propulsion", "to": "mission", "data": ["thrust", "fuel_flow"]},
        ],
    },
    "flow": [
        {"from": "aircraft_config", "to": "aero",
         "variables": ["S_ref", "AR", "CD0", "e"]},
        {"from": "aircraft_config", "to": "propulsion",
         "variables": ["engine_rating"]},
        {"from": "aircraft_config", "to": "weight",
         "variables": ["ac|geom|*", "ac|propulsion|*"]},
        {"from": "weight", "to": "mission",
         "variables": ["OEW"]},
        {"from": "aero", "to": "mission",
         "variables": ["drag"]},
        {"from": "propulsion", "to": "mission",
         "variables": ["thrust", "fuel_flow"]},
    ],
}

# ---------------------------------------------------------------------------
# pyCycle discipline maps
# ---------------------------------------------------------------------------

_TURBOJET_MAP = {
    "nodes": [
        {
            "id": "fc",
            "type": "discipline",
            "label": "Flight Conditions",
            "properties": {
                "description": "Ambient conditions from altitude and Mach",
                "physics": "atmosphere",
                "method": "Standard atmosphere",
                "inputs": ["alt", "MN"],
                "outputs": ["Pt", "Tt", "W"],
            },
        },
        {
            "id": "inlet",
            "type": "discipline",
            "label": "Inlet",
            "properties": {
                "description": "Ram compression inlet",
                "physics": "gas_dynamics",
                "method": "Adiabatic diffuser",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "F_ram"],
            },
        },
        {
            "id": "comp",
            "type": "discipline",
            "label": "Compressor",
            "properties": {
                "description": "Axial compressor with map-based PR and efficiency",
                "physics": "turbomachinery",
                "method": "AXI5 map",
                "inputs": ["Fl_I", "PR", "eff", "Nmech"],
                "outputs": ["Fl_O", "trq", "power"],
            },
        },
        {
            "id": "burner",
            "type": "discipline",
            "label": "Combustor",
            "properties": {
                "description": "Constant-pressure combustion",
                "physics": "combustion",
                "method": "CEA/Tabular thermodynamics",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "turb",
            "type": "discipline",
            "label": "Turbine",
            "properties": {
                "description": "Axial turbine driving compressor via shaft",
                "physics": "turbomachinery",
                "method": "LPT2269 map",
                "inputs": ["Fl_I", "PR", "eff", "Nmech"],
                "outputs": ["Fl_O", "trq", "power"],
            },
        },
        {
            "id": "nozz",
            "type": "discipline",
            "label": "Nozzle",
            "properties": {
                "description": "Converging-diverging nozzle with thrust",
                "physics": "gas_dynamics",
                "method": "Isentropic expansion",
                "inputs": ["Fl_I", "Ps_exhaust", "Cv"],
                "outputs": ["Fg"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Net thrust, TSFC, and OPR calculation",
                "physics": "post_processing",
                "method": "Algebraic",
                "inputs": ["Fg", "F_ram", "Wfuel"],
                "outputs": ["Fn", "TSFC", "OPR"],
            },
        },
    ],
    "coupling": {
        "id": "balance",
        "disciplines": ["comp", "burner", "turb"],
        "solver": "NewtonSolver",
        "label": "Balance (Newton)",
        "exchanges": [
            {"from": "perf", "to": "inlet", "data": ["W (mass flow)"]},
            {"from": "perf", "to": "burner", "data": ["FAR"]},
            {"from": "perf", "to": "turb", "data": ["turb_PR"]},
        ],
    },
    "flow": [
        {"from": "fc", "to": "inlet", "variables": ["Fl_O"]},
        {"from": "inlet", "to": "comp", "variables": ["Fl_O"]},
        {"from": "comp", "to": "burner", "variables": ["Fl_O"]},
        {"from": "burner", "to": "turb", "variables": ["Fl_O"]},
        {"from": "turb", "to": "nozz", "variables": ["Fl_O"]},
        {"from": "nozz", "to": "perf", "variables": ["Fg"]},
        {"from": "inlet", "to": "perf", "variables": ["F_ram"]},
        {"from": "comp", "to": "perf", "variables": ["Pt3"]},
    ],
}

_HBTF_MAP = {
    "nodes": [
        {
            "id": "fc",
            "type": "discipline",
            "label": "Flight Conditions",
            "properties": {
                "description": "Ambient conditions from altitude and Mach",
                "physics": "atmosphere",
                "method": "Standard atmosphere",
                "inputs": ["alt", "MN"],
                "outputs": ["Pt", "Tt", "W"],
            },
        },
        {
            "id": "inlet",
            "type": "discipline",
            "label": "Inlet",
            "properties": {
                "description": "Ram compression inlet",
                "physics": "gas_dynamics",
                "method": "Adiabatic diffuser",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "F_ram"],
            },
        },
        {
            "id": "fan",
            "type": "discipline",
            "label": "Fan",
            "properties": {
                "description": "Low-pressure fan stage",
                "physics": "turbomachinery",
                "method": "FanMap",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "splitter",
            "type": "discipline",
            "label": "Splitter",
            "properties": {
                "description": "Core/bypass flow split",
                "physics": "gas_dynamics",
                "method": "BPR-based split",
                "inputs": ["Fl_I", "BPR"],
                "outputs": ["Fl_O1 (core)", "Fl_O2 (bypass)"],
            },
        },
        {
            "id": "lpc",
            "type": "discipline",
            "label": "LPC",
            "properties": {
                "description": "Low-pressure compressor",
                "physics": "turbomachinery",
                "method": "LPCMap",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "hpc",
            "type": "discipline",
            "label": "HPC",
            "properties": {
                "description": "High-pressure compressor",
                "physics": "turbomachinery",
                "method": "HPCMap",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "burner",
            "type": "discipline",
            "label": "Combustor",
            "properties": {
                "description": "Constant-pressure combustion",
                "physics": "combustion",
                "method": "CEA/Tabular thermodynamics",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "hpt",
            "type": "discipline",
            "label": "HP Turbine",
            "properties": {
                "description": "High-pressure turbine driving HPC",
                "physics": "turbomachinery",
                "method": "HPTMap",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "lpt",
            "type": "discipline",
            "label": "LP Turbine",
            "properties": {
                "description": "Low-pressure turbine driving fan and LPC",
                "physics": "turbomachinery",
                "method": "LPTMap",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "core_nozz",
            "type": "discipline",
            "label": "Core Nozzle",
            "properties": {
                "description": "Core stream exhaust nozzle",
                "physics": "gas_dynamics",
                "method": "Converging nozzle",
                "inputs": ["Fl_I", "Cv"],
                "outputs": ["Fg"],
            },
        },
        {
            "id": "byp_nozz",
            "type": "discipline",
            "label": "Bypass Nozzle",
            "properties": {
                "description": "Bypass stream exhaust nozzle",
                "physics": "gas_dynamics",
                "method": "Converging nozzle",
                "inputs": ["Fl_I", "Cv"],
                "outputs": ["Fg"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Net thrust, TSFC, OPR, and BPR calculation",
                "physics": "post_processing",
                "method": "Algebraic",
                "inputs": ["Fg_core", "Fg_bypass", "F_ram", "Wfuel"],
                "outputs": ["Fn", "TSFC", "OPR", "BPR"],
            },
        },
    ],
    "coupling": {
        "id": "balance",
        "disciplines": ["fan", "lpc", "hpc", "burner", "hpt", "lpt"],
        "solver": "NewtonSolver",
        "label": "Balance (Newton)",
        "exchanges": [
            {"from": "perf", "to": "inlet", "data": ["W (mass flow)"]},
            {"from": "perf", "to": "burner", "data": ["FAR"]},
            {"from": "perf", "to": "hpt", "data": ["hpt_PR"]},
            {"from": "perf", "to": "lpt", "data": ["lpt_PR"]},
        ],
    },
    "flow": [
        # Core path
        {"from": "fc", "to": "inlet", "variables": ["Fl_O"]},
        {"from": "inlet", "to": "fan", "variables": ["Fl_O"]},
        {"from": "fan", "to": "splitter", "variables": ["Fl_O"]},
        {"from": "splitter", "to": "lpc", "variables": ["Fl_O1 (core)"]},
        {"from": "lpc", "to": "hpc", "variables": ["Fl_O"]},
        {"from": "hpc", "to": "burner", "variables": ["Fl_O"]},
        {"from": "burner", "to": "hpt", "variables": ["Fl_O"]},
        {"from": "hpt", "to": "lpt", "variables": ["Fl_O"]},
        {"from": "lpt", "to": "core_nozz", "variables": ["Fl_O"]},
        {"from": "core_nozz", "to": "perf", "variables": ["Fg"]},
        # Bypass path
        {"from": "splitter", "to": "byp_nozz", "variables": ["Fl_O2 (bypass)"]},
        {"from": "byp_nozz", "to": "perf", "variables": ["Fg"]},
        # Performance inputs
        {"from": "inlet", "to": "perf", "variables": ["F_ram"]},
    ],
}

_AB_TURBOJET_MAP = {
    "nodes": [
        {
            "id": "fc",
            "type": "discipline",
            "label": "Flight Conditions",
            "properties": {
                "description": "Ambient conditions from altitude and Mach",
                "physics": "atmosphere",
                "method": "Standard atmosphere",
                "inputs": ["alt", "MN"],
                "outputs": ["Pt", "Tt"],
            },
        },
        {
            "id": "inlet",
            "type": "discipline",
            "label": "Inlet",
            "properties": {
                "description": "Ram compression inlet",
                "physics": "gas_dynamics",
                "method": "Adiabatic diffuser",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "F_ram"],
            },
        },
        {
            "id": "comp",
            "type": "discipline",
            "label": "Compressor",
            "properties": {
                "description": "Axial compressor",
                "physics": "turbomachinery",
                "method": "AXI5 map",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "burner",
            "type": "discipline",
            "label": "Combustor",
            "properties": {
                "description": "Main combustor",
                "physics": "combustion",
                "method": "CEA/Tabular",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "turb",
            "type": "discipline",
            "label": "Turbine",
            "properties": {
                "description": "Axial turbine",
                "physics": "turbomachinery",
                "method": "LPT2269 map",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "ab",
            "type": "discipline",
            "label": "Afterburner",
            "properties": {
                "description": "Reheat combustor for thrust augmentation",
                "physics": "combustion",
                "method": "CEA/Tabular",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "nozz",
            "type": "discipline",
            "label": "Nozzle",
            "properties": {
                "description": "Variable-geometry C-D nozzle",
                "physics": "gas_dynamics",
                "method": "Isentropic expansion",
                "inputs": ["Fl_I", "Cv"],
                "outputs": ["Fg"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Net thrust, TSFC, OPR",
                "physics": "post_processing",
                "method": "Algebraic (2 burners)",
                "inputs": ["Fg", "F_ram", "Wfuel_main", "Wfuel_ab"],
                "outputs": ["Fn", "TSFC", "OPR"],
            },
        },
    ],
    "coupling": {
        "id": "balance",
        "disciplines": ["comp", "burner", "turb", "ab"],
        "solver": "NewtonSolver",
        "label": "Balance (Newton)",
        "exchanges": [
            {"from": "perf", "to": "inlet", "data": ["W (mass flow)"]},
            {"from": "perf", "to": "burner", "data": ["FAR"]},
            {"from": "perf", "to": "turb", "data": ["turb_PR"]},
        ],
    },
    "flow": [
        {"from": "fc", "to": "inlet", "variables": ["Fl_O"]},
        {"from": "inlet", "to": "comp", "variables": ["Fl_O"]},
        {"from": "comp", "to": "burner", "variables": ["Fl_O"]},
        {"from": "burner", "to": "turb", "variables": ["Fl_O"]},
        {"from": "turb", "to": "ab", "variables": ["Fl_O"]},
        {"from": "ab", "to": "nozz", "variables": ["Fl_O"]},
        {"from": "nozz", "to": "perf", "variables": ["Fg"]},
        {"from": "inlet", "to": "perf", "variables": ["F_ram"]},
    ],
}

_SINGLE_TURBOSHAFT_MAP = {
    "nodes": [
        {
            "id": "fc",
            "type": "discipline",
            "label": "Flight Conditions",
            "properties": {
                "description": "Ambient conditions from altitude and Mach",
                "physics": "atmosphere",
                "method": "Standard atmosphere",
                "inputs": ["alt", "MN"],
                "outputs": ["Pt", "Tt"],
            },
        },
        {
            "id": "inlet",
            "type": "discipline",
            "label": "Inlet",
            "properties": {
                "description": "Ram compression inlet",
                "physics": "gas_dynamics",
                "method": "Adiabatic diffuser",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "comp",
            "type": "discipline",
            "label": "Compressor",
            "properties": {
                "description": "Gas generator compressor",
                "physics": "turbomachinery",
                "method": "AXI5 map",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "burner",
            "type": "discipline",
            "label": "Combustor",
            "properties": {
                "description": "Main combustor",
                "physics": "combustion",
                "method": "CEA/Tabular",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "turb",
            "type": "discipline",
            "label": "Gas Generator Turbine",
            "properties": {
                "description": "HP turbine driving compressor",
                "physics": "turbomachinery",
                "method": "LPT2269 map",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "pt",
            "type": "discipline",
            "label": "Power Turbine",
            "properties": {
                "description": "Free power turbine driving output shaft",
                "physics": "turbomachinery",
                "method": "LPT2269 map",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O", "shaft_power"],
            },
        },
        {
            "id": "nozz",
            "type": "discipline",
            "label": "Exhaust",
            "properties": {
                "description": "Exhaust nozzle (low residual thrust)",
                "physics": "gas_dynamics",
                "method": "Converging nozzle",
                "inputs": ["Fl_I"],
                "outputs": ["Fg"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Shaft power, SFC, OPR",
                "physics": "post_processing",
                "method": "Algebraic",
                "inputs": ["shaft_power", "Wfuel"],
                "outputs": ["SHP", "SFC", "OPR"],
            },
        },
    ],
    "coupling": {
        "id": "balance",
        "disciplines": ["comp", "burner", "turb", "pt"],
        "solver": "NewtonSolver",
        "label": "Balance (Newton)",
        "exchanges": [
            {"from": "perf", "to": "inlet", "data": ["W (mass flow)"]},
            {"from": "perf", "to": "burner", "data": ["FAR"]},
            {"from": "perf", "to": "turb", "data": ["turb_PR"]},
            {"from": "perf", "to": "pt", "data": ["pt_PR"]},
        ],
    },
    "flow": [
        {"from": "fc", "to": "inlet", "variables": ["Fl_O"]},
        {"from": "inlet", "to": "comp", "variables": ["Fl_O"]},
        {"from": "comp", "to": "burner", "variables": ["Fl_O"]},
        {"from": "burner", "to": "turb", "variables": ["Fl_O"]},
        {"from": "turb", "to": "pt", "variables": ["Fl_O"]},
        {"from": "pt", "to": "nozz", "variables": ["Fl_O"]},
        {"from": "pt", "to": "perf", "variables": ["shaft_power"]},
        {"from": "nozz", "to": "perf", "variables": ["Fg"]},
    ],
}

_MULTI_TURBOSHAFT_MAP = {
    "nodes": [
        {
            "id": "fc",
            "type": "discipline",
            "label": "Flight Conditions",
            "properties": {
                "description": "Ambient conditions",
                "physics": "atmosphere",
                "method": "Standard atmosphere",
                "inputs": ["alt", "MN"],
                "outputs": ["Pt", "Tt"],
            },
        },
        {
            "id": "inlet",
            "type": "discipline",
            "label": "Inlet",
            "properties": {
                "description": "Ram compression inlet",
                "physics": "gas_dynamics",
                "method": "Adiabatic diffuser",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "lpc",
            "type": "discipline",
            "label": "LPC",
            "properties": {
                "description": "Low-pressure compressor",
                "physics": "turbomachinery",
                "method": "LPCMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "hpc_axi",
            "type": "discipline",
            "label": "HPC (Axial)",
            "properties": {
                "description": "High-pressure axial compressor",
                "physics": "turbomachinery",
                "method": "HPCMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "hpc_centri",
            "type": "discipline",
            "label": "HPC (Centrifugal)",
            "properties": {
                "description": "Centrifugal compressor stage",
                "physics": "turbomachinery",
                "method": "HPCMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "burner",
            "type": "discipline",
            "label": "Combustor",
            "properties": {
                "description": "Main combustor",
                "physics": "combustion",
                "method": "CEA/Tabular",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "hpt",
            "type": "discipline",
            "label": "HP Turbine",
            "properties": {
                "description": "HP turbine driving HPC stages",
                "physics": "turbomachinery",
                "method": "HPTMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "lpt",
            "type": "discipline",
            "label": "LP Turbine",
            "properties": {
                "description": "LP turbine driving LPC",
                "physics": "turbomachinery",
                "method": "LPTMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "pt",
            "type": "discipline",
            "label": "Power Turbine",
            "properties": {
                "description": "Free power turbine",
                "physics": "turbomachinery",
                "method": "LPTMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "shaft_power"],
            },
        },
        {
            "id": "nozz",
            "type": "discipline",
            "label": "Exhaust",
            "properties": {
                "description": "Exhaust nozzle",
                "physics": "gas_dynamics",
                "method": "Converging nozzle",
                "inputs": ["Fl_I"],
                "outputs": ["Fg"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Shaft power, SFC, OPR",
                "physics": "post_processing",
                "method": "Algebraic",
                "inputs": ["shaft_power", "Wfuel"],
                "outputs": ["SHP", "SFC", "OPR"],
            },
        },
    ],
    "coupling": {
        "id": "balance",
        "disciplines": ["lpc", "hpc_axi", "hpc_centri", "burner", "hpt", "lpt", "pt"],
        "solver": "NewtonSolver",
        "label": "Balance (Newton)",
        "exchanges": [
            {"from": "perf", "to": "inlet", "data": ["W"]},
            {"from": "perf", "to": "burner", "data": ["FAR"]},
            {"from": "perf", "to": "hpt", "data": ["hpt_PR"]},
            {"from": "perf", "to": "lpt", "data": ["lpt_PR"]},
            {"from": "perf", "to": "pt", "data": ["pt_PR"]},
        ],
    },
    "flow": [
        {"from": "fc", "to": "inlet", "variables": ["Fl_O"]},
        {"from": "inlet", "to": "lpc", "variables": ["Fl_O"]},
        {"from": "lpc", "to": "hpc_axi", "variables": ["Fl_O"]},
        {"from": "hpc_axi", "to": "hpc_centri", "variables": ["Fl_O"]},
        {"from": "hpc_centri", "to": "burner", "variables": ["Fl_O"]},
        {"from": "burner", "to": "hpt", "variables": ["Fl_O"]},
        {"from": "hpt", "to": "lpt", "variables": ["Fl_O"]},
        {"from": "lpt", "to": "pt", "variables": ["Fl_O"]},
        {"from": "pt", "to": "nozz", "variables": ["Fl_O"]},
        {"from": "pt", "to": "perf", "variables": ["shaft_power"]},
    ],
}

_MIXEDFLOW_MAP = {
    "nodes": [
        {
            "id": "fc",
            "type": "discipline",
            "label": "Flight Conditions",
            "properties": {
                "description": "Ambient conditions",
                "physics": "atmosphere",
                "method": "Standard atmosphere",
                "inputs": ["alt", "MN"],
                "outputs": ["Pt", "Tt"],
            },
        },
        {
            "id": "inlet",
            "type": "discipline",
            "label": "Inlet",
            "properties": {
                "description": "Ram compression inlet",
                "physics": "gas_dynamics",
                "method": "Adiabatic diffuser",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "F_ram"],
            },
        },
        {
            "id": "fan",
            "type": "discipline",
            "label": "Fan",
            "properties": {
                "description": "Low-pressure fan stage",
                "physics": "turbomachinery",
                "method": "AXI5 map",
                "inputs": ["Fl_I", "PR", "eff"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "splitter",
            "type": "discipline",
            "label": "Splitter",
            "properties": {
                "description": "Core/bypass flow split",
                "physics": "gas_dynamics",
                "method": "BPR-based split",
                "inputs": ["Fl_I", "BPR"],
                "outputs": ["Fl_O1 (core)", "Fl_O2 (bypass)"],
            },
        },
        {
            "id": "lpc",
            "type": "discipline",
            "label": "LPC",
            "properties": {
                "description": "Low-pressure compressor",
                "physics": "turbomachinery",
                "method": "LPCMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "hpc",
            "type": "discipline",
            "label": "HPC",
            "properties": {
                "description": "High-pressure compressor",
                "physics": "turbomachinery",
                "method": "HPCMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "burner",
            "type": "discipline",
            "label": "Combustor",
            "properties": {
                "description": "Main combustor",
                "physics": "combustion",
                "method": "CEA/Tabular",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "hpt",
            "type": "discipline",
            "label": "HP Turbine",
            "properties": {
                "description": "High-pressure turbine",
                "physics": "turbomachinery",
                "method": "HPTMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "lpt",
            "type": "discipline",
            "label": "LP Turbine",
            "properties": {
                "description": "Low-pressure turbine",
                "physics": "turbomachinery",
                "method": "LPTMap",
                "inputs": ["Fl_I"],
                "outputs": ["Fl_O", "trq"],
            },
        },
        {
            "id": "mixer",
            "type": "discipline",
            "label": "Mixer",
            "properties": {
                "description": "Core/bypass stream mixer",
                "physics": "gas_dynamics",
                "method": "Constant-area mixing",
                "inputs": ["Fl_I1 (core)", "Fl_I2 (bypass)"],
                "outputs": ["Fl_O"],
            },
        },
        {
            "id": "ab",
            "type": "discipline",
            "label": "Afterburner",
            "properties": {
                "description": "Reheat combustor",
                "physics": "combustion",
                "method": "CEA/Tabular",
                "inputs": ["Fl_I", "FAR"],
                "outputs": ["Fl_O", "Wfuel"],
            },
        },
        {
            "id": "nozz",
            "type": "discipline",
            "label": "Mixed Nozzle",
            "properties": {
                "description": "Mixed-flow exhaust nozzle",
                "physics": "gas_dynamics",
                "method": "C-D nozzle",
                "inputs": ["Fl_I"],
                "outputs": ["Fg"],
            },
        },
        {
            "id": "perf",
            "type": "discipline",
            "label": "Performance",
            "properties": {
                "description": "Net thrust, TSFC, OPR",
                "physics": "post_processing",
                "method": "Algebraic (2 burners)",
                "inputs": ["Fg", "F_ram", "Wfuel"],
                "outputs": ["Fn", "TSFC", "OPR"],
            },
        },
    ],
    "coupling": {
        "id": "balance",
        "disciplines": ["fan", "lpc", "hpc", "burner", "hpt", "lpt", "mixer", "ab"],
        "solver": "NewtonSolver",
        "label": "Balance (Newton)",
        "exchanges": [
            {"from": "perf", "to": "inlet", "data": ["W"]},
            {"from": "perf", "to": "burner", "data": ["FAR"]},
            {"from": "perf", "to": "hpt", "data": ["hpt_PR"]},
            {"from": "perf", "to": "lpt", "data": ["lpt_PR"]},
            {"from": "perf", "to": "splitter", "data": ["BPR"]},
        ],
    },
    "flow": [
        # Core path
        {"from": "fc", "to": "inlet", "variables": ["Fl_O"]},
        {"from": "inlet", "to": "fan", "variables": ["Fl_O"]},
        {"from": "fan", "to": "splitter", "variables": ["Fl_O"]},
        {"from": "splitter", "to": "lpc", "variables": ["Fl_O1 (core)"]},
        {"from": "lpc", "to": "hpc", "variables": ["Fl_O"]},
        {"from": "hpc", "to": "burner", "variables": ["Fl_O"]},
        {"from": "burner", "to": "hpt", "variables": ["Fl_O"]},
        {"from": "hpt", "to": "lpt", "variables": ["Fl_O"]},
        {"from": "lpt", "to": "mixer", "variables": ["Fl_O (core)"]},
        # Bypass path
        {"from": "splitter", "to": "mixer", "variables": ["Fl_O2 (bypass)"]},
        # Mixed path
        {"from": "mixer", "to": "ab", "variables": ["Fl_O"]},
        {"from": "ab", "to": "nozz", "variables": ["Fl_O"]},
        {"from": "nozz", "to": "perf", "variables": ["Fg"]},
        {"from": "inlet", "to": "perf", "variables": ["F_ram"]},
    ],
}

# ---------------------------------------------------------------------------
# Component type -> discipline map registry
# ---------------------------------------------------------------------------

_COMPONENT_MAPS = {
    # OAS
    "oas/AerostructPoint": _AEROSTRUCT_MAP,
    "oas/AeroPoint": _AERO_MAP,
    # OCP missions
    "ocp/BasicMission": _OCP_MISSION_MAP,
    "ocp/FullMission": _OCP_MISSION_MAP,
    "ocp/MissionWithReserve": _OCP_MISSION_MAP,
    # pyCycle engines
    "pyc/TurbojetDesign": _TURBOJET_MAP,
    "pyc/TurbojetMultipoint": _TURBOJET_MAP,
    "pyc/HBTFDesign": _HBTF_MAP,
    "pyc/ABTurbojetDesign": _AB_TURBOJET_MAP,
    "pyc/SingleTurboshaftDesign": _SINGLE_TURBOSHAFT_MAP,
    "pyc/MultiTurboshaftDesign": _MULTI_TURBOSHAFT_MAP,
    "pyc/MixedFlowDesign": _MIXEDFLOW_MAP,
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

    # --- OAS enrichment ---
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

    # --- OCP enrichment ---
    component_family = metadata.get("component_family", "")
    if component_family == "ocp":
        active_slots = metadata.get("active_slots", {})

        if did == "aircraft_config":
            arch = metadata.get("architecture", "")
            if arch:
                props["architecture"] = arch
            num_nodes = metadata.get("num_nodes")
            if num_nodes:
                props["num_nodes"] = num_nodes

        if did == "aero":
            drag_slot = active_slots.get("drag", {})
            if drag_slot:
                provider = drag_slot.get("provider", "PolarDrag")
                props["method"] = provider
                node["label"] = f"Aerodynamics ({provider})"

        if did == "propulsion":
            prop_slot = active_slots.get("propulsion", {})
            if prop_slot:
                provider = prop_slot.get("provider", "")
                props["method"] = provider
                node["label"] = f"Propulsion ({provider})"
            else:
                arch = metadata.get("architecture", "")
                if arch:
                    props["method"] = arch
                    node["label"] = f"Propulsion ({arch})"

        if did == "weight":
            wt_slot = active_slots.get("weight", {})
            if wt_slot:
                provider = wt_slot.get("provider", "")
                props["method"] = provider
                node["label"] = f"Weight ({provider})"

        if did == "mission":
            phases = metadata.get("phases", [])
            if phases:
                props["phases"] = phases
                mission_type = metadata.get("mission_type", "basic")
                node["label"] = f"Mission ({mission_type})\n{len(phases)} phases"

    # --- pyCycle enrichment ---
    archetype_meta = metadata.get("archetype_meta", {})
    if archetype_meta:
        if did == "burner":
            desc = archetype_meta.get("description", "")
            if desc:
                props["engine_type"] = desc

        if did == "perf":
            output_names = metadata.get("output_names", [])
            if output_names:
                props["tracked_outputs"] = [n.split(".")[-1] for n in output_names]

        if did == "fc" and metadata.get("multipoint"):
            point_names = metadata.get("point_names", [])
            if point_names:
                props["operating_points"] = point_names
                node["label"] = f"Flight Conditions\n{len(point_names)} points"


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
