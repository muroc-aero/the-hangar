"""Physics interpretation and narrative summaries of OAS results.

Migrated from: OpenAeroStruct/oas_mcp/core/summary.py
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_max_failure(data: dict) -> float | None:
    """Return the maximum failure metric across all surfaces in *data*."""
    failure: float | None = None
    for surf in data.get("surfaces", {}).values():
        f = surf.get("failure")
        if f is not None:
            failure = max(failure, f) if failure is not None else float(f)
    return failure


def _sectional_metrics(standard_detail: dict, surface_name: str) -> dict:
    """Extract spanwise Cl metrics from standard_detail."""
    metrics: dict[str, Any] = {}
    if not standard_detail:
        return metrics
    sect = standard_detail.get("sectional_data", {}).get(surface_name, {})
    cl_vals = sect.get("Cl", [])
    if len(cl_vals) < 2:
        return metrics
    # OAS symmetric mesh: node 0 = tip, last node = root — so cl_vals[0] is tip
    cl_tip = float(cl_vals[0])
    cl_root = float(cl_vals[-1])
    metrics["cl_root"] = round(cl_root, 4)
    metrics["cl_tip"] = round(cl_tip, 4)
    if abs(cl_root) > 1e-6:
        ratio = cl_tip / cl_root
        metrics["cl_ratio_tip_root"] = round(ratio, 3)
        max_idx = max(range(len(cl_vals)), key=lambda i: abs(cl_vals[i]))
        # max_idx=0 → tip (100%); max_idx=last → root (0%)
        metrics["cl_max_location_pct_span"] = round(
            (1.0 - max_idx / max(len(cl_vals) - 1, 1)) * 100.0, 1
        )
    return metrics


def _drag_breakdown(surf_results: dict) -> dict:
    """Compute drag component percentages for a single surface."""
    cdi = surf_results.get("CDi", 0.0) or 0.0
    cdv = surf_results.get("CDv", 0.0) or 0.0
    cdw = surf_results.get("CDw", 0.0) or 0.0
    total = cdi + cdv + cdw
    if total < 1e-12:
        return {}
    return {
        "CDi": round(100.0 * cdi / total, 1),
        "CDv": round(100.0 * cdv / total, 1),
        "CDw": round(100.0 * cdw / total, 1),
    }


def _deflection_metrics(
    results: dict, standard_detail: dict | None, surface_name: str
) -> dict:
    """Extract tip deflection metrics from results."""
    metrics: dict[str, Any] = {}
    surf = results.get("surfaces", {}).get(surface_name, {})
    tip_defl = surf.get("tip_deflection_m")
    if tip_defl is not None:
        metrics["tip_deflection_m"] = round(tip_defl, 4)
        # Compute as % of semi-span from mesh snapshot
        if standard_detail:
            snap = standard_detail.get("mesh_snapshot", {}).get(surface_name, {})
            le = snap.get("leading_edge")
            if le and len(le) >= 2:
                y_coords = [pt[1] for pt in le]
                semi_span = max(abs(y_coords[0]), abs(y_coords[-1]))
                if semi_span > 0.01:
                    metrics["tip_deflection_pct_span"] = round(
                        100.0 * abs(tip_defl) / semi_span, 2
                    )
    return metrics


def _weight_balance(lew: float | None) -> str:
    """Classify the L=W residual (upstream: L_equals_W = 1 - L/W, normalized)."""
    if lew is None:
        return "unknown"
    if abs(lew) < 0.01:
        return "trimmed"
    # Positive residual means lift falls short of weight
    return "lift_deficit" if lew > 0 else "lift_surplus"


def _compute_delta(current: dict, previous: dict | None, keys: list[str]) -> dict | None:
    """Return signed deltas for numeric keys between current and previous results."""
    if previous is None:
        return None
    delta: dict = {}
    for k in keys:
        c = current.get(k)
        p = previous.get(k)
        if (
            isinstance(c, (int, float))
            and isinstance(p, (int, float))
            and not math.isnan(float(c))
            and not math.isnan(float(p))
        ):
            delta[k] = round(float(c) - float(p), 6)
    return delta if delta else None


def _classify_flags(results: dict, derived: dict, analysis_type: str) -> list[str]:
    """Return short actionable tags based on results."""
    flags = []
    cl_ratio = derived.get("cl_ratio_tip_root")
    if cl_ratio is not None:
        if cl_ratio > 1.05:
            flags.append("tip_loaded")
        elif cl_ratio < 0.85:
            flags.append("tip_unloaded")
    drag_bd = derived.get("drag_breakdown_pct", {})
    if drag_bd.get("CDi", 0) > 70:
        flags.append("induced_drag_dominant")
    elif drag_bd.get("CDv", 0) > 50:
        flags.append("viscous_drag_dominant")
    if analysis_type == "aerostruct":
        # OAS convention: failure = stress/allowable - 1, so failure > 0 is overstress
        failure = _extract_max_failure(results)
        if failure is not None:
            if failure > 0.0:
                flags.append("structural_failure")
            elif failure > -0.2:
                flags.append("near_yield")
        wb = derived.get("weight_balance")
        if wb == "lift_deficit":
            flags.append("lift_deficit")
        elif wb == "lift_surplus":
            flags.append("lift_surplus")
        pct_span = derived.get("tip_deflection_pct_span")
        if pct_span is not None and pct_span > 15.0:
            flags.append("high_deflection")
    return flags


# ---------------------------------------------------------------------------
# Narrative builders
# ---------------------------------------------------------------------------


def _narrative_aero(results: dict, derived: dict, context: dict) -> str:
    CL = results.get("CL")
    CD = results.get("CD")
    LD = results.get("L_over_D")
    alpha = context.get("alpha")
    parts = []
    if CL is not None and CD is not None and alpha is not None:
        ld_str = f" with L/D={LD:.1f}" if LD else ""
        parts.append(f"Wing produces CL={CL:.3f} at α={alpha:.1f}°{ld_str}.")
    cl_ratio = derived.get("cl_ratio_tip_root")
    if cl_ratio is not None:
        if cl_ratio > 1.05:
            parts.append(
                f"Lift distribution is tip-loaded (Cl_tip/Cl_root={cl_ratio:.2f})."
            )
        elif cl_ratio < 0.85:
            parts.append(
                f"Lift distribution is tip-unloaded (Cl_tip/Cl_root={cl_ratio:.2f})."
            )
        else:
            parts.append(
                f"Lift distribution is well-balanced (Cl_tip/Cl_root={cl_ratio:.2f})."
            )
    drag_bd = derived.get("drag_breakdown_pct", {})
    if drag_bd.get("CDi", 0) > 70:
        parts.append(f"Induced drag dominates at {drag_bd['CDi']:.0f}% of total.")
    elif drag_bd.get("CDv", 0) > 40:
        parts.append(f"Viscous drag is significant at {drag_bd['CDv']:.0f}% of total.")
    return " ".join(parts) or "Aerodynamic analysis complete."


def _narrative_aerostruct(results: dict, derived: dict, context: dict) -> str:
    parts = [_narrative_aero(results, derived, context)]
    failure = _extract_max_failure(results)
    if failure is not None:
        # failure = stress/allowable - 1: > 0 is overstress, margin to allowable is -failure
        margin = -failure * 100.0
        if failure > 0.0:
            parts.append(f"Structure FAILS (failure={failure:.3f} > 0).")
        elif failure > -0.2:
            parts.append(
                f"Structure is near yield (failure={failure:.3f}, margin {margin:.0f}%)."
            )
        else:
            parts.append(
                f"Structure is safe with {margin:.0f}% margin (failure={failure:.3f})."
            )
    tip_defl = derived.get("tip_deflection_m")
    pct_span = derived.get("tip_deflection_pct_span")
    if tip_defl is not None:
        direction = "upward" if tip_defl > 0 else "downward"
        defl_str = f"Tip deflects {abs(tip_defl):.3f} m {direction}"
        if pct_span is not None:
            defl_str += f" ({pct_span:.1f}% of semi-span)"
        parts.append(defl_str + ".")
    wb = derived.get("weight_balance")
    if wb == "trimmed":
        parts.append("Wing is trimmed (L≈W).")
    elif wb == "lift_deficit":
        parts.append("Lift deficit — increase alpha or chord.")
    elif wb == "lift_surplus":
        parts.append("Lift surplus — decrease alpha.")
    return " ".join(p for p in parts if p) or "Aerostructural analysis complete."


def _narrative_drag_polar(results: dict, derived: dict) -> str:
    best = results.get("best_L_over_D", {})
    ld = best.get("L_over_D")
    best_alpha = best.get("alpha_deg")
    parts = []
    if ld is not None and best_alpha is not None:
        parts.append(f"Best L/D={ld:.1f} occurs at α={best_alpha:.1f}°.")
    cl_alpha = derived.get("cl_alpha_approx")
    if cl_alpha is not None:
        parts.append(f"Lift-curve slope CL_α≈{cl_alpha:.3f} 1/deg.")
    cd_min = derived.get("cd_min")
    if cd_min is not None:
        parts.append(f"Minimum CD={cd_min:.4f}.")
    return " ".join(parts) or "Drag polar computed."


def _narrative_stability(results: dict, derived: dict) -> str:
    sm = results.get("static_margin")
    cla = results.get("CL_alpha")
    parts = []
    if sm is not None:
        stability = results.get("stability", "")
        parts.append(f"Static margin = {sm:.3f} ({stability}).")
    if cla is not None:
        parts.append(f"Lift-curve slope CL_α = {cla:.3f} 1/deg.")
    return " ".join(parts) or "Stability derivatives computed."


def _narrative_optimization(results: dict, derived: dict) -> str:
    success = results.get("success", False)
    final = results.get("final_results", {})
    parts = []
    if not success:
        parts.append("Optimization did not converge — check bounds or constraints.")
    else:
        parts.append("Optimization converged successfully.")
    obj_imp = derived.get("objective_improvement_pct")
    if obj_imp is not None:
        parts.append(f"Objective improved by {obj_imp:.1f}%.")
    failure = _extract_max_failure(final)
    if failure is not None and failure > 0.0:
        parts.append(f"Warning: optimized design has structural failure (failure={failure:.3f}).")
    return " ".join(parts) or "Optimization complete."


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def summarize_aero(
    results: dict,
    standard_detail: dict | None = None,
    context: dict | None = None,
    previous: dict | None = None,
) -> dict:
    """Build a summary dict for run_aero_analysis results."""
    context = context or {}
    derived: dict = {}
    # Single pass over first surface: sectional metrics + drag breakdown
    for surf_name, surf in results.get("surfaces", {}).items():
        if standard_detail:
            derived.update(_sectional_metrics(standard_detail, surf_name))
        bd = _drag_breakdown(surf)
        if bd:
            derived["drag_breakdown_pct"] = bd
        break
    narrative = _narrative_aero(results, derived, context)
    flags = _classify_flags(results, derived, "aero")
    delta = _compute_delta(results, previous, ["CL", "CD", "L_over_D", "CM"])
    return {"narrative": narrative, "derived_metrics": derived, "flags": flags, "delta": delta}


def summarize_aerostruct(
    results: dict,
    standard_detail: dict | None = None,
    context: dict | None = None,
    previous: dict | None = None,
) -> dict:
    """Build a summary dict for run_aerostruct_analysis results."""
    context = context or {}
    derived: dict = {}
    # Single pass over first surface: sectional metrics + drag breakdown + structural margin
    for surf_name, surf in results.get("surfaces", {}).items():
        if standard_detail:
            derived.update(_sectional_metrics(standard_detail, surf_name))
        bd = _drag_breakdown(surf)
        if bd:
            derived["drag_breakdown_pct"] = bd
        failure = surf.get("failure")
        if failure is not None:
            # failure = stress/allowable - 1, so margin to allowable is -failure
            derived["structural_margin_pct"] = round(-float(failure) * 100.0, 1)
        derived.update(_deflection_metrics(results, standard_detail, surf_name))
        fv = surf.get("total_fuel_volume_m3")
        if fv is not None:
            derived["total_fuel_volume_m3"] = fv
        break
    # Aircraft CG x-location
    cg = results.get("cg")
    if cg is not None and len(cg) >= 1:
        derived["cg_x_m"] = round(float(cg[0]), 4)
    derived["weight_balance"] = _weight_balance(results.get("L_equals_W"))
    struct_mass = results.get("structural_mass")
    W0 = context.get("W0")
    if struct_mass is not None and W0 and W0 > 0:
        derived["structural_mass_fraction_pct"] = round(100.0 * struct_mass / W0, 1)
    narrative = _narrative_aerostruct(results, derived, context)
    flags = _classify_flags(results, derived, "aerostruct")
    delta = _compute_delta(results, previous, ["CL", "CD", "L_over_D", "fuelburn", "structural_mass"])
    return {"narrative": narrative, "derived_metrics": derived, "flags": flags, "delta": delta}


def summarize_drag_polar(
    results: dict,
    context: dict | None = None,
    previous: dict | None = None,
) -> dict:
    """Build a summary dict for compute_drag_polar results."""
    derived: dict = {}
    alphas = results.get("alpha_deg", [])
    CLs = results.get("CL", [])
    CDs = results.get("CD", [])
    if CDs:
        derived["cd_min"] = round(min(CDs), 6)
    # Zero-lift alpha via linear interpolation
    if alphas and CLs and len(alphas) == len(CLs):
        for i in range(len(CLs) - 1):
            if CLs[i] * CLs[i + 1] <= 0:
                da = alphas[i + 1] - alphas[i]
                dcl = CLs[i + 1] - CLs[i]
                if abs(dcl) > 1e-8:
                    derived["alpha_at_zero_cl"] = round(
                        alphas[i] - CLs[i] * da / dcl, 2
                    )
                break
    # CL_alpha slope from middle portion of polar
    if len(alphas) >= 3 and len(CLs) >= 3:
        lo = max(0, len(alphas) // 4)
        hi = min(len(alphas) - 1, 3 * len(alphas) // 4)
        if hi > lo:
            da = alphas[hi] - alphas[lo]
            if abs(da) > 1e-6:
                derived["cl_alpha_approx"] = round((CLs[hi] - CLs[lo]) / da, 4)
    narrative = _narrative_drag_polar(results, derived)
    delta: dict | None = None
    if previous:
        prev_best = previous.get("best_L_over_D", {}).get("L_over_D")
        curr_best = results.get("best_L_over_D", {}).get("L_over_D")
        if prev_best is not None and curr_best is not None:
            delta = {"best_L_over_D": round(curr_best - prev_best, 4)}
    return {"narrative": narrative, "derived_metrics": derived, "flags": [], "delta": delta}


def summarize_stability(
    results: dict,
    context: dict | None = None,
    previous: dict | None = None,
) -> dict:
    """Build a summary dict for compute_stability_derivatives results."""
    derived: dict = {}
    narrative = _narrative_stability(results, derived)
    sm = results.get("static_margin")
    flags: list[str] = []
    if sm is not None:
        if sm < 0:
            flags.append("unstable")
        elif sm < 0.05:
            flags.append("marginally_stable")
        else:
            flags.append("stable")
    delta = _compute_delta(results, previous, ["CL_alpha", "static_margin", "CM_alpha"])
    return {"narrative": narrative, "derived_metrics": derived, "flags": flags, "delta": delta}


def summarize_optimization(
    results: dict,
    standard_detail: dict | None = None,
    context: dict | None = None,
) -> dict:
    """Build a summary dict for run_optimization results."""
    derived: dict = {}
    history = results.get("optimization_history", {})
    obj_values = history.get("objective_values", [])
    if len(obj_values) >= 2:
        initial_obj = obj_values[0]
        final_obj = obj_values[-1]
        if abs(initial_obj) > 1e-12:
            derived["objective_improvement_pct"] = round(
                100.0 * (initial_obj - final_obj) / abs(initial_obj), 2
            )
        derived["num_iterations"] = len(obj_values)
    final = results.get("final_results", {})
    constraints: dict[str, float] = {}
    if final.get("CL") is not None:
        constraints["CL"] = round(float(final["CL"]), 4)
    failure = _extract_max_failure(final)
    if failure is not None:
        constraints["failure"] = round(failure, 4)
    if constraints:
        derived["constraint_margins"] = constraints
    # Max DV changes
    initial_dvs = history.get("initial_dvs", {})
    opt_dvs = results.get("optimized_design_variables", {})
    dv_max_changes: dict[str, float] = {}
    for dv_name in opt_dvs:
        if dv_name in initial_dvs:
            ini = np.asarray(initial_dvs[dv_name]).ravel()
            opt = np.asarray(opt_dvs[dv_name]).ravel()
            if len(ini) == len(opt):
                dv_max_changes[dv_name] = round(float(np.abs(opt - ini).max()), 6)
    if dv_max_changes:
        derived["dv_max_changes"] = dv_max_changes
    narrative = _narrative_optimization(results, derived)
    flags: list[str] = []
    if not results.get("success"):
        flags.append("not_converged")
    if failure is not None and failure > 0.0:
        flags.append("structural_failure_in_opt")
    return {"narrative": narrative, "derived_metrics": derived, "flags": flags, "delta": None}
