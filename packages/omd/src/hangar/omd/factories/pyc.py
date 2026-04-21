"""pyCycle component factories for omd plan materialization.

Builds OpenMDAO problems from plan YAML configs using the self-contained
pyCycle archetype classes in hangar.omd.pyc.
"""

from __future__ import annotations

from hangar.omd.factory_metadata import FactoryContract, FactoryMetadata

from typing import Any

import openmdao.api as om

from hangar.omd.pyc.archetypes import Turbojet, MPTurbojet
from hangar.omd.pyc.hbtf import HBTF, MPHbtf, HBTF_META
from hangar.omd.pyc.ab_turbojet import ABTurbojet, AB_TURBOJET_META
from hangar.omd.pyc.turboshaft import (
    SingleSpoolTurboshaft, SINGLE_SPOOL_TURBOSHAFT_META,
    MultiSpoolTurboshaft, MULTI_SPOOL_TURBOSHAFT_META,
)
from hangar.omd.pyc.mixedflow_turbofan import MixedFlowTurbofan, MIXEDFLOW_TURBOFAN_META
from hangar.omd.pyc.defaults import (
    DEFAULT_TURBOJET_PARAMS,
    DEFAULT_TURBOJET_DESIGN_GUESSES,
    DEFAULT_TURBOJET_OD_GUESSES,
    TURBOJET_META,
    DEFAULT_HBTF_PARAMS,
    DEFAULT_HBTF_DESIGN_GUESSES,
    DEFAULT_HBTF_OD_GUESSES,
    DEFAULT_AB_TURBOJET_PARAMS,
    DEFAULT_AB_TURBOJET_DESIGN_GUESSES,
    DEFAULT_AB_TURBOJET_DESIGN_CONDITIONS,
    DEFAULT_SINGLE_TURBOSHAFT_PARAMS,
    DEFAULT_SINGLE_TURBOSHAFT_DESIGN_GUESSES,
    DEFAULT_SINGLE_TURBOSHAFT_DESIGN_CONDITIONS,
    DEFAULT_MULTI_TURBOSHAFT_PARAMS,
    DEFAULT_MULTI_TURBOSHAFT_DESIGN_GUESSES,
    DEFAULT_MULTI_TURBOSHAFT_DESIGN_CONDITIONS,
    DEFAULT_MIXEDFLOW_PARAMS,
    DEFAULT_MIXEDFLOW_DESIGN_GUESSES,
    DEFAULT_MIXEDFLOW_DESIGN_CONDITIONS,
)


def build_pyc_turbojet_design(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a single design-point turbojet problem from plan config.

    The Cycle class IS the model (prob.model = Turbojet(...)), not a
    subsystem. The Newton solver and balance equations are configured
    inside Turbojet.setup(), so no external solver config is needed.

    Args:
        component_config: Engine parameters (comp_PR, comp_eff, etc.).
        operating_points: Flight conditions (alt, MN, Fn_target, T4_target).

    Returns:
        Tuple of (problem, metadata). Problem has setup NOT called.
    """
    # Merge user config over defaults
    params = {**DEFAULT_TURBOJET_PARAMS}
    for key in DEFAULT_TURBOJET_PARAMS:
        if key in component_config:
            params[key] = component_config[key]
    # Pass through any extra keys (e.g. solver_iprint)
    for key in component_config:
        if key not in params:
            params[key] = component_config[key]

    guesses = component_config.get("initial_guesses", DEFAULT_TURBOJET_DESIGN_GUESSES)

    prob = om.Problem(reports=False)
    prob.model = Turbojet(params=params)

    # Operating conditions applied after setup via initial_values_with_units
    initial_values_with_units: dict[str, dict] = {
        "fc.alt": {"val": float(operating_points.get("alt", 0.0)), "units": "ft"},
        "fc.MN": {"val": float(operating_points.get("MN", 0.000001))},
        "balance.Fn_target": {
            "val": float(operating_points.get("Fn_target", 11800.0)),
            "units": "lbf",
        },
        "balance.T4_target": {
            "val": float(operating_points.get("T4_target", 2370.0)),
            "units": "degR",
        },
        "comp.PR": {"val": float(params["comp_PR"])},
        "comp.eff": {"val": float(params["comp_eff"])},
        "turb.eff": {"val": float(params["turb_eff"])},
        "Nmech": {"val": float(params["Nmech"]), "units": "rpm"},
    }

    # Newton solver initial guesses (no units needed)
    initial_values: dict[str, float] = {
        "balance.FAR": guesses.get("FAR", 0.0175506829934),
        "balance.W": guesses.get("W", 168.453135137),
        "balance.turb_PR": guesses.get("turb_PR", 4.46138725662),
        "fc.balance.Pt": guesses.get("fc_Pt", 14.6955113159),
        "fc.balance.Tt": guesses.get("fc_Tt", 518.665288153),
    }

    metadata: dict[str, Any] = {
        "point_name": "turbojet_design",
        "output_names": [
            "perf.Fn", "perf.TSFC", "perf.OPR", "perf.Fg",
        ],
        "initial_values": initial_values,
        "initial_values_with_units": initial_values_with_units,
        "var_paths": {
            "Fn": "perf.Fn",
            "TSFC": "perf.TSFC",
            "OPR": "perf.OPR",
            "Fg": "perf.Fg",
            "W": "inlet.Fl_O:stat:W",
            "T4": "burner.Fl_O:tot:T",
            "comp_PR": "comp.PR",
            "comp_eff": "comp.eff",
            "turb_PR": "turb.PR",
            "turb_eff": "turb.eff",
        },
        "archetype_meta": TURBOJET_META,
    }

    return prob, metadata


def build_pyc_turbojet_multipoint(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a multi-point turbojet problem (design + off-design).

    The operating_points dict must contain a ``flight_points`` list with
    at least one entry (the design point). Subsequent entries are off-design.

    Args:
        component_config: Engine parameters.
        operating_points: Must contain ``flight_points`` list. First entry
            is the design point (needs alt, MN, Fn_target, T4_target).
            Remaining entries are off-design (need name, alt, MN, Fn_target).

    Returns:
        Tuple of (problem, metadata). Problem has setup NOT called.
    """
    # Merge params
    params = {**DEFAULT_TURBOJET_PARAMS}
    for key in DEFAULT_TURBOJET_PARAMS:
        if key in component_config:
            params[key] = component_config[key]
    for key in component_config:
        if key not in params:
            params[key] = component_config[key]

    # Parse flight points
    flight_points = operating_points.get("flight_points", [])
    if not flight_points:
        raise ValueError("Multipoint plan requires flight_points in operating_points")

    design_point = flight_points[0]
    od_points = flight_points[1:]

    # Ensure OD points have names
    for i, od in enumerate(od_points):
        if "name" not in od:
            od["name"] = f"OD{i}"

    design_guesses = component_config.get(
        "design_guesses", DEFAULT_TURBOJET_DESIGN_GUESSES
    )
    od_guesses = component_config.get(
        "od_guesses", DEFAULT_TURBOJET_OD_GUESSES
    )

    prob = om.Problem(reports=False)
    prob.model = MPTurbojet(params=params, od_points=od_points)

    # Design point values
    initial_values_with_units: dict[str, dict] = {
        "DESIGN.fc.alt": {"val": float(design_point.get("alt", 0.0)), "units": "ft"},
        "DESIGN.fc.MN": {"val": float(design_point.get("MN", 0.000001))},
        "DESIGN.balance.Fn_target": {
            "val": float(design_point.get("Fn_target", 11800.0)),
            "units": "lbf",
        },
        "DESIGN.balance.T4_target": {
            "val": float(design_point.get("T4_target", 2370.0)),
            "units": "degR",
        },
        "DESIGN.comp.PR": {"val": float(params["comp_PR"])},
        "DESIGN.comp.eff": {"val": float(params["comp_eff"])},
        "DESIGN.turb.eff": {"val": float(params["turb_eff"])},
    }

    # Design point Newton guesses
    initial_values: dict[str, float] = {
        "DESIGN.balance.FAR": design_guesses.get("FAR", 0.0175506829934),
        "DESIGN.balance.W": design_guesses.get("W", 168.453135137),
        "DESIGN.balance.turb_PR": design_guesses.get("turb_PR", 4.46138725662),
        "DESIGN.fc.balance.Pt": design_guesses.get("fc_Pt", 14.6955113159),
        "DESIGN.fc.balance.Tt": design_guesses.get("fc_Tt", 518.665288153),
    }

    # Off-design guesses
    for od in od_points:
        pt = od["name"]
        initial_values[f"{pt}.balance.W"] = od_guesses.get("W", 166.0)
        initial_values[f"{pt}.balance.FAR"] = od_guesses.get("FAR", 0.0168)
        initial_values[f"{pt}.balance.Nmech"] = od_guesses.get("Nmech", 8197.0)
        initial_values[f"{pt}.fc.balance.Pt"] = od_guesses.get("fc_Pt", 15.7)
        initial_values[f"{pt}.fc.balance.Tt"] = od_guesses.get("fc_Tt", 558.3)
        initial_values[f"{pt}.turb.PR"] = od_guesses.get("turb_PR", 4.669)

    # Build output names for all points
    point_names = ["DESIGN"] + [od["name"] for od in od_points]
    output_names = []
    for pt in point_names:
        output_names.extend([
            f"{pt}.perf.Fn", f"{pt}.perf.TSFC", f"{pt}.perf.OPR", f"{pt}.perf.Fg",
        ])

    metadata: dict[str, Any] = {
        "point_name": "DESIGN",
        "point_names": point_names,
        "multipoint": True,
        "output_names": output_names,
        "initial_values": initial_values,
        "initial_values_with_units": initial_values_with_units,
        "var_paths": {
            "Fn": "DESIGN.perf.Fn",
            "TSFC": "DESIGN.perf.TSFC",
            "OPR": "DESIGN.perf.OPR",
            "Fg": "DESIGN.perf.Fg",
        },
        "archetype_meta": TURBOJET_META,
    }

    return prob, metadata


# ---------------------------------------------------------------------------
# HBTF (high-bypass turbofan)
# ---------------------------------------------------------------------------


def _merge(defaults, config):
    """Merge config over defaults, passing through extra keys."""
    merged = dict(defaults)
    for k, v in config.items():
        merged[k] = v
    return merged


def build_pyc_hbtf_design(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build an HBTF design-point problem via MPHbtf (design only, no OD)."""
    params = _merge(DEFAULT_HBTF_PARAMS, component_config)
    guesses = component_config.get("initial_guesses", DEFAULT_HBTF_DESIGN_GUESSES)

    prob = om.Problem(reports=False)
    prob.model = MPHbtf(params=params, od_points=[])

    initial_values_with_units: dict[str, dict] = {
        "DESIGN.fc.alt": {"val": float(operating_points.get("alt", 35000.0)), "units": "ft"},
        "DESIGN.fc.MN": {"val": float(operating_points.get("MN", 0.8))},
        "DESIGN.T4_MAX": {"val": float(operating_points.get("T4_target", 2857.0)), "units": "degR"},
        "DESIGN.Fn_DES": {"val": float(operating_points.get("Fn_target", 5900.0)), "units": "lbf"},
        "DESIGN.fan.PR": {"val": float(params.get("fan_PR", 1.685))},
        "DESIGN.fan.eff": {"val": float(params.get("fan_eff", 0.8948))},
        "DESIGN.lpc.PR": {"val": float(params.get("lpc_PR", 1.935))},
        "DESIGN.lpc.eff": {"val": float(params.get("lpc_eff", 0.9243))},
        "DESIGN.hpc.PR": {"val": float(params.get("hpc_PR", 9.369))},
        "DESIGN.hpc.eff": {"val": float(params.get("hpc_eff", 0.8707))},
        "DESIGN.hpt.eff": {"val": float(params.get("hpt_eff", 0.8888))},
        "DESIGN.lpt.eff": {"val": float(params.get("lpt_eff", 0.8996))},
    }

    initial_values: dict[str, float] = {
        "DESIGN.balance.FAR": guesses.get("FAR", 0.025),
        "DESIGN.balance.W": guesses.get("W", 100.0),
        "DESIGN.balance.lpt_PR": guesses.get("lpt_PR", 4.0),
        "DESIGN.balance.hpt_PR": guesses.get("hpt_PR", 3.0),
        "DESIGN.fc.balance.Pt": guesses.get("fc_Pt", 5.2),
        "DESIGN.fc.balance.Tt": guesses.get("fc_Tt", 440.0),
    }

    metadata: dict[str, Any] = {
        "point_name": "DESIGN",
        "output_names": [
            "DESIGN.perf.Fn", "DESIGN.perf.TSFC", "DESIGN.perf.OPR",
            "DESIGN.perf.Fg",
        ],
        "initial_values": initial_values,
        "initial_values_with_units": initial_values_with_units,
        "var_paths": {
            "Fn": "DESIGN.perf.Fn", "TSFC": "DESIGN.perf.TSFC",
            "OPR": "DESIGN.perf.OPR", "Fg": "DESIGN.perf.Fg",
            "W": "DESIGN.inlet.Fl_O:stat:W", "BPR": "DESIGN.splitter.BPR",
        },
        "archetype_meta": HBTF_META,
    }
    return prob, metadata


# ---------------------------------------------------------------------------
# Afterburning turbojet
# ---------------------------------------------------------------------------

def build_pyc_ab_turbojet_design(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build an afterburning turbojet design-point problem."""
    params = _merge(DEFAULT_AB_TURBOJET_PARAMS, component_config)
    guesses = component_config.get("initial_guesses",
                                   DEFAULT_AB_TURBOJET_DESIGN_GUESSES)

    prob = om.Problem(reports=False)
    prob.model = ABTurbojet(params=params)

    ab_far = float(operating_points.get("ab_FAR",
                   DEFAULT_AB_TURBOJET_DESIGN_CONDITIONS.get("ab_FAR", 0.0)))

    initial_values_with_units: dict[str, dict] = {
        "fc.alt": {"val": float(operating_points.get("alt", 0.0)), "units": "ft"},
        "fc.MN": {"val": float(operating_points.get("MN", 0.000001))},
        "balance.rhs:W": {"val": float(operating_points.get("Fn_target", 11800.0)), "units": "lbf"},
        "balance.rhs:FAR": {"val": float(operating_points.get("T4_target", 2370.0)), "units": "degR"},
        "comp.PR": {"val": float(params["comp_PR"])},
        "comp.eff": {"val": float(params["comp_eff"])},
        "turb.eff": {"val": float(params["turb_eff"])},
        "Nmech": {"val": float(params["Nmech"]), "units": "rpm"},
        "ab.Fl_I:FAR": {"val": ab_far},
    }

    # Element MNs and cycle params
    for mn_key in ("inlet_MN", "duct1_MN", "comp_MN", "burner_MN", "turb_MN", "ab_MN"):
        om_key = mn_key.replace("_MN", ".MN")
        if mn_key in params:
            initial_values_with_units[om_key] = {"val": float(params[mn_key])}

    cycle_params = {
        "duct1.dPqP": params.get("duct1_dPqP", 0.02),
        "burner.dPqP": params.get("burner_dPqP", 0.03),
        "ab.dPqP": params.get("ab_dPqP", 0.06),
        "nozz.Cv": params.get("nozz_Cv", 0.99),
        "comp.cool1:frac_W": params.get("cool1_frac_W", 0.0789),
        "comp.cool1:frac_P": params.get("cool1_frac_P", 1.0),
        "comp.cool1:frac_work": params.get("cool1_frac_work", 1.0),
        "comp.cool2:frac_W": params.get("cool2_frac_W", 0.0383),
        "comp.cool2:frac_P": params.get("cool2_frac_P", 1.0),
        "comp.cool2:frac_work": params.get("cool2_frac_work", 1.0),
        "turb.cool1:frac_P": params.get("turb_cool1_frac_P", 1.0),
        "turb.cool2:frac_P": params.get("turb_cool2_frac_P", 0.0),
    }
    for k, v in cycle_params.items():
        initial_values_with_units[k] = {"val": float(v)}

    initial_values: dict[str, float] = {
        "balance.FAR": guesses.get("FAR", 0.01755078),
        "balance.W": guesses.get("W", 168.0),
        "balance.turb_PR": guesses.get("turb_PR", 4.46131867),
        "fc.balance.Pt": guesses.get("fc_Pt", 14.6959),
        "fc.balance.Tt": guesses.get("fc_Tt", 518.67),
    }

    metadata: dict[str, Any] = {
        "point_name": "ab_turbojet",
        "output_names": ["perf.Fn", "perf.TSFC", "perf.OPR", "perf.Fg"],
        "initial_values": initial_values,
        "initial_values_with_units": initial_values_with_units,
        "var_paths": {
            "Fn": "perf.Fn", "TSFC": "perf.TSFC",
            "OPR": "perf.OPR", "Fg": "perf.Fg",
        },
        "archetype_meta": AB_TURBOJET_META,
    }
    return prob, metadata


# ---------------------------------------------------------------------------
# Single-spool turboshaft
# ---------------------------------------------------------------------------

def build_pyc_single_turboshaft_design(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a single-spool turboshaft design-point problem."""
    params = _merge(DEFAULT_SINGLE_TURBOSHAFT_PARAMS, component_config)
    guesses = component_config.get("initial_guesses",
                                   DEFAULT_SINGLE_TURBOSHAFT_DESIGN_GUESSES)

    prob = om.Problem(reports=False)
    prob.model = SingleSpoolTurboshaft(params=params)

    defs = DEFAULT_SINGLE_TURBOSHAFT_DESIGN_CONDITIONS
    initial_values_with_units: dict[str, dict] = {
        "fc.alt": {"val": float(operating_points.get("alt", defs["alt"])), "units": "ft"},
        "fc.MN": {"val": float(operating_points.get("MN", defs["MN"]))},
        "balance.T4_target": {"val": float(operating_points.get("T4_target", defs["T4_target"])), "units": "degR"},
        "balance.pwr_target": {"val": float(operating_points.get("pwr_target", defs["pwr_target"])), "units": "hp"},
        "balance.nozz_PR_target": {"val": float(operating_points.get("nozz_PR_target", defs["nozz_PR_target"]))},
        "comp.PR": {"val": float(params["comp_PR"])},
        "comp.eff": {"val": float(params["comp_eff"])},
        "turb.eff": {"val": float(params["turb_eff"])},
        "pt.eff": {"val": float(params["pt_eff"])},
        "HP_Nmech": {"val": float(params["HP_Nmech"]), "units": "rpm"},
        "LP_Nmech": {"val": float(params["LP_Nmech"]), "units": "rpm"},
    }

    for mn_key in ("inlet_MN", "comp_MN", "burner_MN", "turb_MN"):
        om_key = mn_key.replace("_MN", ".MN")
        if mn_key in params:
            initial_values_with_units[om_key] = {"val": float(params[mn_key])}

    initial_values_with_units["burner.dPqP"] = {"val": float(params.get("burner_dPqP", 0.03))}
    initial_values_with_units["nozz.Cv"] = {"val": float(params.get("nozz_Cv", 0.99))}

    initial_values: dict[str, float] = {
        "balance.FAR": guesses.get("FAR", 0.0175),
        "balance.W": guesses.get("W", 27.265),
        "balance.turb_PR": guesses.get("turb_PR", 3.8768),
        "balance.pt_PR": guesses.get("pt_PR", 2.0),
        "fc.balance.Pt": guesses.get("fc_Pt", 14.696),
        "fc.balance.Tt": guesses.get("fc_Tt", 518.67),
    }

    metadata: dict[str, Any] = {
        "point_name": "turboshaft",
        "output_names": ["perf.Fn", "perf.TSFC", "perf.OPR", "perf.Fg"],
        "initial_values": initial_values,
        "initial_values_with_units": initial_values_with_units,
        "var_paths": {
            "Fn": "perf.Fn", "TSFC": "perf.TSFC",
            "OPR": "perf.OPR", "Fg": "perf.Fg",
            "power": "LP_shaft.pwr_net",
        },
        "archetype_meta": SINGLE_SPOOL_TURBOSHAFT_META,
    }
    return prob, metadata


# ---------------------------------------------------------------------------
# Multi-spool turboshaft
# ---------------------------------------------------------------------------

def build_pyc_multi_turboshaft_design(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a 3-spool turboshaft design-point problem."""
    params = _merge(DEFAULT_MULTI_TURBOSHAFT_PARAMS, component_config)
    guesses = component_config.get("initial_guesses",
                                   DEFAULT_MULTI_TURBOSHAFT_DESIGN_GUESSES)

    prob = om.Problem(reports=False)
    prob.model = MultiSpoolTurboshaft(params=params, maxiter=10)

    defs = DEFAULT_MULTI_TURBOSHAFT_DESIGN_CONDITIONS
    initial_values_with_units: dict[str, dict] = {
        "fc.alt": {"val": float(operating_points.get("alt", defs["alt"])), "units": "ft"},
        "fc.MN": {"val": float(operating_points.get("MN", defs["MN"]))},
        "balance.rhs:FAR": {"val": float(operating_points.get("T4_target", defs["T4_target"])), "units": "degR"},
        "balance.rhs:W": {"val": float(operating_points.get("nozz_PR_target", defs["nozz_PR_target"]))},
        "LP_Nmech": {"val": float(params["LP_Nmech"]), "units": "rpm"},
        "IP_Nmech": {"val": float(params["IP_Nmech"]), "units": "rpm"},
        "HP_Nmech": {"val": float(params["HP_Nmech"]), "units": "rpm"},
        "lp_shaft.HPX": {"val": float(params["lp_shaft_HPX"]), "units": "hp"},
        "lpc.PR": {"val": float(params["lpc_PR"])},
        "lpc.eff": {"val": float(params["lpc_eff"])},
        "hpc_axi.PR": {"val": float(params["hpc_axi_PR"])},
        "hpc_axi.eff": {"val": float(params["hpc_axi_eff"])},
        "hpc_centri.PR": {"val": float(params["hpc_centri_PR"])},
        "hpc_centri.eff": {"val": float(params["hpc_centri_eff"])},
        "hpt.eff": {"val": float(params["hpt_eff"])},
        "lpt.eff": {"val": float(params["lpt_eff"])},
        "pt.eff": {"val": float(params["pt_eff"])},
    }

    mn_map = {
        "inlet.MN": 0.4, "duct1.MN": 0.4, "lpc.MN": 0.3,
        "icduct.MN": 0.3, "hpc_axi.MN": 0.25, "bld25.MN": 0.3,
        "hpc_centri.MN": 0.2, "bld3.MN": 0.2, "duct6.MN": 0.2,
        "burner.MN": 0.15, "hpt.MN": 0.3, "duct43.MN": 0.3,
        "lpt.MN": 0.4, "itduct.MN": 0.4, "pt.MN": 0.4, "duct12.MN": 0.4,
    }
    for k, v in mn_map.items():
        initial_values_with_units[k] = {"val": v}

    cycle_map = {
        "inlet.ram_recovery": params["inlet_ram_recovery"],
        "duct1.dPqP": params["duct1_dPqP"],
        "icduct.dPqP": params["icduct_dPqP"],
        "duct6.dPqP": params["duct6_dPqP"],
        "burner.dPqP": params["burner_dPqP"],
        "duct43.dPqP": params["duct43_dPqP"],
        "itduct.dPqP": params["itduct_dPqP"],
        "duct12.dPqP": params["duct12_dPqP"],
        "nozzle.Cv": params["nozzle_Cv"],
        "bld25.cool1:frac_W": params["cool1_frac_W"],
        "bld25.cool2:frac_W": params["cool2_frac_W"],
        "bld3.cool3:frac_W": params["cool3_frac_W"],
        "bld3.cool4:frac_W": params["cool4_frac_W"],
        "hpt.cool3:frac_P": params["hpt_cool3_frac_P"],
        "hpt.cool4:frac_P": params["hpt_cool4_frac_P"],
        "lpt.cool1:frac_P": params["lpt_cool1_frac_P"],
        "lpt.cool2:frac_P": params["lpt_cool2_frac_P"],
    }
    for k, v in cycle_map.items():
        initial_values_with_units[k] = {"val": float(v)}

    initial_values: dict[str, float] = {
        "balance.FAR": guesses.get("FAR", 0.02261),
        "balance.W": guesses.get("W", 10.76),
        "balance.hpt_PR": guesses.get("hpt_PR", 4.233),
        "balance.lpt_PR": guesses.get("lpt_PR", 1.979),
        "balance.pt_PR": guesses.get("pt_PR", 4.919),
        "fc.balance.Pt": guesses.get("fc_Pt", 5.666),
        "fc.balance.Tt": guesses.get("fc_Tt", 440.0),
    }

    metadata: dict[str, Any] = {
        "point_name": "multi_turboshaft",
        "output_names": ["perf.Fn", "perf.OPR", "perf.Fg"],
        "initial_values": initial_values,
        "initial_values_with_units": initial_values_with_units,
        "var_paths": {"Fn": "perf.Fn", "OPR": "perf.OPR", "Fg": "perf.Fg"},
        "archetype_meta": MULTI_SPOOL_TURBOSHAFT_META,
    }
    return prob, metadata


# ---------------------------------------------------------------------------
# Mixed-flow turbofan
# ---------------------------------------------------------------------------

def build_pyc_mixedflow_design(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a mixed-flow turbofan design-point problem."""
    params = _merge(DEFAULT_MIXEDFLOW_PARAMS, component_config)
    guesses = component_config.get("initial_guesses",
                                   DEFAULT_MIXEDFLOW_DESIGN_GUESSES)

    prob = om.Problem(reports=False)
    prob.model = MixedFlowTurbofan(params=params)

    defs = DEFAULT_MIXEDFLOW_DESIGN_CONDITIONS
    initial_values_with_units: dict[str, dict] = {
        "fc.alt": {"val": float(operating_points.get("alt", defs["alt"])), "units": "ft"},
        "fc.MN": {"val": float(operating_points.get("MN", defs["MN"]))},
        "balance.rhs:W": {"val": float(operating_points.get("Fn_target", defs["Fn_target"])), "units": "lbf"},
        "balance.rhs:FAR_core": {"val": float(operating_points.get("T4_target", defs["T4_target"])), "units": "degR"},
        "balance.rhs:FAR_ab": {"val": float(operating_points.get("T_ab_target", defs["T_ab_target"])), "units": "degR"},
        "balance.rhs:BPR": {"val": float(operating_points.get("BPR_target", defs["BPR_target"]))},
        "LP_Nmech": {"val": float(params["LP_Nmech"]), "units": "rpm"},
        "HP_Nmech": {"val": float(params["HP_Nmech"]), "units": "rpm"},
        "hp_shaft.HPX": {"val": float(params["hp_shaft_HPX"]), "units": "hp"},
        "fan.PR": {"val": float(params["fan_PR"])},
        "fan.eff": {"val": float(params["fan_eff"])},
        "lpc.PR": {"val": float(params["lpc_PR"])},
        "lpc.eff": {"val": float(params["lpc_eff"])},
        "hpc.PR": {"val": float(params["hpc_PR"])},
        "hpc.eff": {"val": float(params["hpc_eff"])},
        "hpt.eff": {"val": float(params["hpt_eff"])},
        "lpt.eff": {"val": float(params["lpt_eff"])},
    }

    mn_map = {
        "inlet.MN": 0.751, "inlet_duct.MN": 0.4463, "fan.MN": 0.4578,
        "splitter.MN1": 0.3104, "splitter.MN2": 0.4518,
        "splitter_core_duct.MN": 0.3121, "lpc.MN": 0.3059,
        "lpc_duct.MN": 0.3563, "hpc.MN": 0.2442, "bld3.MN": 0.3,
        "burner.MN": 0.1025, "hpt.MN": 0.365, "hpt_duct.MN": 0.3063,
        "lpt.MN": 0.4127, "lpt_duct.MN": 0.4463,
        "bypass_duct.MN": 0.4463, "mixer_duct.MN": 0.4463,
        "afterburner.MN": 0.1025,
    }
    for k, v in mn_map.items():
        initial_values_with_units[k] = {"val": v}

    cycle_map = {
        "inlet.ram_recovery": params["inlet_ram_recovery"],
        "inlet_duct.dPqP": params["inlet_duct_dPqP"],
        "splitter_core_duct.dPqP": params["splitter_core_duct_dPqP"],
        "lpc_duct.dPqP": params["lpc_duct_dPqP"],
        "burner.dPqP": params["burner_dPqP"],
        "hpt_duct.dPqP": params["hpt_duct_dPqP"],
        "lpt_duct.dPqP": params["lpt_duct_dPqP"],
        "bypass_duct.dPqP": params["bypass_duct_dPqP"],
        "mixer_duct.dPqP": params["mixer_duct_dPqP"],
        "afterburner.dPqP": params["afterburner_dPqP"],
        "mixed_nozz.Cfg": params["mixed_nozz_Cfg"],
        "hpc.cool1:frac_W": params["cool1_frac_W"],
        "hpc.cool1:frac_P": params["cool1_frac_P"],
        "hpc.cool1:frac_work": params["cool1_frac_work"],
        "bld3.cool3:frac_W": params["cool3_frac_W"],
        "hpt.cool3:frac_P": params["hpt_cool3_frac_P"],
        "lpt.cool1:frac_P": params["lpt_cool1_frac_P"],
    }
    for k, v in cycle_map.items():
        initial_values_with_units[k] = {"val": float(v)}

    initial_values: dict[str, float] = {
        "balance.FAR_core": guesses.get("FAR_core", 0.025),
        "balance.FAR_ab": guesses.get("FAR_ab", 0.025),
        "balance.BPR": guesses.get("BPR", 1.0),
        "balance.W": guesses.get("W", 100.0),
        "balance.lpt_PR": guesses.get("lpt_PR", 3.5),
        "balance.hpt_PR": guesses.get("hpt_PR", 2.5),
        "fc.balance.Pt": guesses.get("fc_Pt", 5.2),
        "fc.balance.Tt": guesses.get("fc_Tt", 440.0),
        "mixer.balance.P_tot": guesses.get("mixer_P_tot", 15.0),
    }

    metadata: dict[str, Any] = {
        "point_name": "mixedflow",
        "output_names": ["perf.Fn", "perf.TSFC", "perf.OPR", "perf.Fg"],
        "initial_values": initial_values,
        "initial_values_with_units": initial_values_with_units,
        "var_paths": {
            "Fn": "perf.Fn", "TSFC": "perf.TSFC",
            "OPR": "perf.OPR", "Fg": "perf.Fg",
        },
        "archetype_meta": MIXEDFLOW_TURBOFAN_META,
    }
    return prob, metadata


# pyCycle archetypes install their Cycle class as the model root and do
# not expose an external IVC that ``skip_fields`` could operate on.
# Contracts are declared empty so the integrity validator can run
# against them (and xfail on skip_fields), but nothing auto-shares.
# ``validate_shared_vars`` also rejects pyc/* consumers explicitly.
_PYC_EMPTY_CONTRACT = FactoryContract(produces={}, consumes={})

build_pyc_turbojet_design.contract = _PYC_EMPTY_CONTRACT
build_pyc_turbojet_multipoint.contract = _PYC_EMPTY_CONTRACT
build_pyc_hbtf_design.contract = _PYC_EMPTY_CONTRACT
build_pyc_ab_turbojet_design.contract = _PYC_EMPTY_CONTRACT
build_pyc_single_turboshaft_design.contract = _PYC_EMPTY_CONTRACT
build_pyc_multi_turboshaft_design.contract = _PYC_EMPTY_CONTRACT
build_pyc_mixedflow_design.contract = _PYC_EMPTY_CONTRACT
