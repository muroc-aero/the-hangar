"""OpenMDAO problem assembly for pyCycle archetypes.

Handles building single design-point, off-design, and multi-point problems
from archetype definitions and user parameters.
"""

from __future__ import annotations

import openmdao.api as om

from hangar.omd.pyc.archetypes import get_archetype
from hangar.omd.pyc.defaults import (
    DEFAULT_TURBOJET_PARAMS,
    DEFAULT_TURBOJET_DESIGN_GUESSES,
    DEFAULT_TURBOJET_OD_GUESSES,
)


def _prefix(point: str, path: str) -> str:
    """Build a dotted path with optional point prefix."""
    return f"{point}.{path}" if point else path


def _merge_params(archetype_name: str, user_params: dict) -> dict:
    """Merge user params over archetype defaults."""
    defaults_map = {
        "turbojet": DEFAULT_TURBOJET_PARAMS,
    }
    defaults = defaults_map.get(archetype_name, {})
    return {**defaults, **user_params}


def _get_design_guesses(archetype_name: str) -> dict:
    """Get default initial guesses for the design point."""
    guesses_map = {
        "turbojet": DEFAULT_TURBOJET_DESIGN_GUESSES,
    }
    return guesses_map.get(archetype_name, {})


def _get_od_guesses(archetype_name: str) -> dict:
    """Get default initial guesses for off-design points."""
    guesses_map = {
        "turbojet": DEFAULT_TURBOJET_OD_GUESSES,
    }
    return guesses_map.get(archetype_name, {})


def _apply_turbojet_design_guesses(
    prob: om.Problem, point: str, guesses: dict
) -> None:
    """Set Newton initial guesses for turbojet design point."""
    prob[_prefix(point, "balance.FAR")] = guesses.get("FAR", 0.0176)
    prob[_prefix(point, "balance.W")] = guesses.get("W", 168.5)
    prob[_prefix(point, "balance.turb_PR")] = guesses.get("turb_PR", 4.46)
    prob[_prefix(point, "fc.balance.Pt")] = guesses.get("fc_Pt", 14.696)
    prob[_prefix(point, "fc.balance.Tt")] = guesses.get("fc_Tt", 518.67)


def _apply_turbojet_od_guesses(
    prob: om.Problem, point: str, guesses: dict
) -> None:
    """Set Newton initial guesses for turbojet off-design point."""
    prob[_prefix(point, "balance.W")] = guesses.get("W", 166.0)
    prob[_prefix(point, "balance.FAR")] = guesses.get("FAR", 0.0168)
    prob[_prefix(point, "balance.Nmech")] = guesses.get("Nmech", 8197.0)
    prob[_prefix(point, "fc.balance.Pt")] = guesses.get("fc_Pt", 15.7)
    prob[_prefix(point, "fc.balance.Tt")] = guesses.get("fc_Tt", 558.3)
    prob[_prefix(point, "turb.PR")] = guesses.get("turb_PR", 4.669)


_DESIGN_GUESS_APPLICATORS = {
    "turbojet": _apply_turbojet_design_guesses,
}

_OD_GUESS_APPLICATORS = {
    "turbojet": _apply_turbojet_od_guesses,
}


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_design_problem(
    archetype_name: str,
    params: dict,
    design_conditions: dict,
    guesses: dict | None = None,
) -> om.Problem:
    """Build a single design-point pyCycle problem.

    Parameters
    ----------
    archetype_name : str
        Key into the archetype registry (e.g. "turbojet").
    params : dict
        Cycle parameters (PR, eff, etc.) merged over defaults.
    design_conditions : dict
        Must contain ``alt``, ``MN``, ``Fn_target``, and ``T4_target``.
    guesses : dict or None
        Optional initial guesses for Newton solver; defaults used if None.

    Returns
    -------
    om.Problem
        Assembled and set-up problem, ready for ``run_model()``.
    """
    arch = get_archetype(archetype_name)
    merged = _merge_params(archetype_name, params)
    cycle_cls = arch["class"]

    prob = om.Problem(reports=False)
    cycle = cycle_cls(params=merged)
    prob.model = cycle
    prob.setup(check=False)

    # Set design-point flight conditions
    prob.set_val("fc.alt", design_conditions["alt"], units="ft")
    prob.set_val("fc.MN", design_conditions["MN"])

    # Set component parameters
    if archetype_name == "turbojet":
        prob.set_val("comp.PR", merged["comp_PR"])
        prob.set_val("comp.eff", merged["comp_eff"])
        prob.set_val("turb.eff", merged["turb_eff"])
        prob.set_val("balance.Fn_target", design_conditions["Fn_target"], units="lbf")
        prob.set_val("balance.T4_target", design_conditions["T4_target"], units="degR")

    # Apply initial guesses
    default_guesses = _get_design_guesses(archetype_name)
    final_guesses = {**default_guesses, **(guesses or {})}
    applicator = _DESIGN_GUESS_APPLICATORS.get(archetype_name)
    if applicator:
        applicator(prob, "", final_guesses)

    return prob


def build_multipoint_problem(
    archetype_name: str,
    params: dict,
    design_conditions: dict,
    od_points: list[dict],
    design_guesses: dict | None = None,
    od_guesses: dict | None = None,
) -> om.Problem:
    """Build a multi-point problem (design + off-design).

    Parameters
    ----------
    archetype_name : str
        Key into the archetype registry.
    params : dict
        Cycle parameters.
    design_conditions : dict
        Design point: ``alt``, ``MN``, ``Fn_target``, ``T4_target``.
    od_points : list[dict]
        Off-design points, each with ``name``, ``alt``, ``MN``, ``Fn_target``.
    design_guesses, od_guesses : dict or None
        Optional overrides for Newton initial guesses.

    Returns
    -------
    om.Problem
        Assembled MPCycle problem, ready for ``run_model()``.
    """
    arch = get_archetype(archetype_name)
    merged = _merge_params(archetype_name, params)
    mp_cls = arch["mp_class"]

    prob = om.Problem(reports=False)
    prob.model = mp_cls(params=merged, od_points=od_points)
    prob.setup(check=False)

    # Set design-point inputs
    prob.set_val("DESIGN.fc.alt", design_conditions["alt"], units="ft")
    prob.set_val("DESIGN.fc.MN", design_conditions["MN"])

    if archetype_name == "turbojet":
        prob.set_val("DESIGN.comp.PR", merged["comp_PR"])
        prob.set_val("DESIGN.comp.eff", merged["comp_eff"])
        prob.set_val("DESIGN.turb.eff", merged["turb_eff"])
        prob.set_val("DESIGN.balance.Fn_target", design_conditions["Fn_target"], units="lbf")
        prob.set_val("DESIGN.balance.T4_target", design_conditions["T4_target"], units="degR")

    # Apply design-point guesses
    default_dg = _get_design_guesses(archetype_name)
    final_dg = {**default_dg, **(design_guesses or {})}
    d_applicator = _DESIGN_GUESS_APPLICATORS.get(archetype_name)
    if d_applicator:
        d_applicator(prob, "DESIGN", final_dg)

    # Apply off-design guesses
    default_og = _get_od_guesses(archetype_name)
    final_og = {**default_og, **(od_guesses or {})}
    od_applicator = _OD_GUESS_APPLICATORS.get(archetype_name)
    if od_applicator:
        for od in od_points:
            od_applicator(prob, od["name"], final_og)

    return prob
