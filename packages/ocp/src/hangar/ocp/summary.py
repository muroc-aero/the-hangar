"""Narrative summaries and derived metrics for OpenConcept results."""

from __future__ import annotations


def summarize_mission(
    results: dict,
    trajectory: dict | None,
    inputs: dict,
    previous_results: dict | None,
) -> dict:
    """Generate a narrative summary of mission analysis results.

    Returns a dict with 'narrative', 'derived_metrics', 'delta_vs_previous', and 'flags'.
    """
    narrative_parts = []
    derived: dict = {}
    flags: list[str] = []

    fuel_burn = results.get("fuel_burn_kg")
    oew = results.get("OEW_kg")
    mtow = results.get("MTOW_kg")

    # Basic narrative
    if fuel_burn is not None and mtow is not None:
        fuel_frac = fuel_burn / mtow * 100
        derived["fuel_fraction_pct"] = round(fuel_frac, 1)
        narrative_parts.append(
            f"Mission fuel burn: {fuel_burn:.1f} kg ({fuel_frac:.1f}% of MTOW)"
        )

    if oew is not None and mtow is not None:
        oew_frac = oew / mtow * 100
        derived["oew_fraction_pct"] = round(oew_frac, 1)
        narrative_parts.append(f"OEW: {oew:.0f} kg ({oew_frac:.1f}% of MTOW)")

    tofl = results.get("TOFL_ft")
    if tofl is not None:
        narrative_parts.append(f"Takeoff field length: {tofl:.0f} ft")

    soc = results.get("battery_SOC_final")
    if soc is not None:
        narrative_parts.append(f"Battery SOC at end of mission: {soc:.1%}")
        if soc < 0.1:
            flags.append("low_battery_soc")

    margin = results.get("MTOW_margin_lb")
    if margin is not None:
        narrative_parts.append(f"MTOW margin: {margin:.0f} lb")
        if margin < 0:
            flags.append("weight_closure_violated")

    # Mission range and altitude context
    mission_range = inputs.get("mission_range_NM")
    cruise_alt = inputs.get("cruise_altitude_ft")
    if mission_range and cruise_alt:
        narrative_parts.append(
            f"Mission: {mission_range:.0f} NM at FL{cruise_alt/100:.0f}"
        )

    # Derived: specific range (NM per kg fuel)
    if fuel_burn and fuel_burn > 0 and mission_range:
        spec_range = mission_range / fuel_burn
        derived["specific_range_NM_per_kg"] = round(spec_range, 3)

    # Delta vs previous
    delta: dict = {}
    if previous_results:
        prev_fuel = previous_results.get("fuel_burn_kg")
        if prev_fuel is not None and fuel_burn is not None and prev_fuel > 0:
            delta["fuel_burn_pct"] = round((fuel_burn - prev_fuel) / prev_fuel * 100, 1)

        prev_oew = previous_results.get("OEW_kg")
        if prev_oew is not None and oew is not None and prev_oew > 0:
            delta["OEW_pct"] = round((oew - prev_oew) / prev_oew * 100, 1)

    return {
        "narrative": "; ".join(narrative_parts) if narrative_parts else "Analysis complete.",
        "derived_metrics": derived,
        "delta_vs_previous": delta,
        "flags": flags,
    }


def summarize_optimization(
    results: dict,
    context: dict | None,
) -> dict:
    """Generate a narrative summary of optimization results."""
    narrative_parts = []
    flags: list[str] = []

    success = results.get("optimization_successful")
    iters = results.get("num_iterations")

    if success:
        narrative_parts.append(f"Optimization converged in {iters} iterations")
    else:
        narrative_parts.append("Optimization did NOT converge")
        flags.append("opt_not_converged")

    # Optimized values
    opt_vals = results.get("optimized_values", {})
    for name, val in opt_vals.items():
        narrative_parts.append(f"{name} = {val}")

    objective = results.get("objective_value")
    if objective is not None:
        narrative_parts.append(f"Objective value: {objective:.4f}")

    return {
        "narrative": "; ".join(narrative_parts),
        "derived_metrics": {},
        "delta_vs_previous": {},
        "flags": flags,
    }
