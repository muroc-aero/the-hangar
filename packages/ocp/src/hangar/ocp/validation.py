"""Physics and numerics validation checks for OpenConcept results.

Each check returns a ``ValidationFinding`` from ``hangar.sdk``.
"""

from __future__ import annotations

from hangar.sdk.validation.checks import ValidationFinding, findings_to_dict  # noqa: F401
from hangar.ocp.config.limits import THROTTLE_MAX, TOFL_MAX_FT


def validate_mission_results(
    results: dict,
    context: dict | None = None,
) -> list[ValidationFinding]:
    """Run physics checks on mission analysis results."""
    findings: list[ValidationFinding] = []
    ctx = context or {}

    # Fuel burn positive (if applicable)
    fuel_burn = results.get("fuel_burn_kg")
    if fuel_burn is not None:
        findings.append(ValidationFinding(
            check_id="physics.fuel_burn_positive",
            category="physics",
            severity="error",
            confidence="high",
            passed=fuel_burn > 0,
            message=(
                f"Fuel burn = {fuel_burn:.1f} kg > 0"
                if fuel_burn > 0
                else f"Fuel burn = {fuel_burn:.1f} kg <= 0 -- non-physical"
            ),
            remediation="Check mission range, throttle settings, and engine rating.",
        ))

    # OEW positive and less than MTOW
    oew = results.get("OEW_kg")
    mtow = results.get("MTOW_kg")
    if oew is not None:
        findings.append(ValidationFinding(
            check_id="physics.oew_positive",
            category="physics",
            severity="error",
            confidence="high",
            passed=oew > 0,
            message=(
                f"OEW = {oew:.0f} kg > 0"
                if oew > 0
                else f"OEW = {oew:.0f} kg <= 0 -- non-physical"
            ),
            remediation="Check weight model inputs and aircraft configuration.",
        ))

    if oew is not None and mtow is not None:
        findings.append(ValidationFinding(
            check_id="physics.oew_less_than_mtow",
            category="physics",
            severity="error",
            confidence="high",
            passed=oew < mtow,
            message=(
                f"OEW ({oew:.0f} kg) < MTOW ({mtow:.0f} kg)"
                if oew < mtow
                else f"OEW ({oew:.0f} kg) >= MTOW ({mtow:.0f} kg) -- cannot carry payload"
            ),
            remediation="Reduce structural weight or increase MTOW.",
        ))

    # TOFL reasonable
    tofl = results.get("TOFL_ft")
    if tofl is not None:
        findings.append(ValidationFinding(
            check_id="physics.tofl_reasonable",
            category="physics",
            severity="warning",
            confidence="medium",
            passed=0 < tofl < TOFL_MAX_FT,
            message=(
                f"TOFL = {tofl:.0f} ft (within limits)"
                if 0 < tofl < TOFL_MAX_FT
                else f"TOFL = {tofl:.0f} ft -- outside expected range"
            ),
            remediation="Check engine rating, MTOW, and CLmax_TO.",
        ))

    # Battery SOC non-negative
    soc = results.get("battery_SOC_final")
    if soc is not None:
        findings.append(ValidationFinding(
            check_id="physics.battery_soc_nonnegative",
            category="physics",
            severity="error",
            confidence="high",
            passed=soc >= 0,
            message=(
                f"Battery SOC final = {soc:.3f} >= 0"
                if soc >= 0
                else f"Battery SOC final = {soc:.3f} < 0 -- battery over-discharged"
            ),
            remediation="Reduce hybridization fraction, increase battery weight, or shorten mission.",
        ))

    # MTOW margin non-negative (hybrid)
    margin = results.get("MTOW_margin_lb")
    if margin is not None:
        findings.append(ValidationFinding(
            check_id="constraints.mtow_margin",
            category="constraints",
            severity="warning",
            confidence="high",
            passed=margin >= -1.0,  # small tolerance
            message=(
                f"MTOW margin = {margin:.1f} lb >= 0"
                if margin >= -1.0
                else f"MTOW margin = {margin:.1f} lb < 0 -- weight closure violated"
            ),
            remediation="Increase MTOW or reduce component weights.",
        ))

    return findings


def validate_aircraft_config(
    aircraft_data: dict,
    architecture: str,
) -> list[ValidationFinding]:
    """Run sanity checks on aircraft configuration."""
    findings: list[ValidationFinding] = []
    ac = aircraft_data.get("ac", {})

    # Wing loading check
    mtow = ac.get("weights", {}).get("MTOW", {})
    sref = ac.get("geom", {}).get("wing", {}).get("S_ref", {})

    mtow_val = mtow.get("value")
    sref_val = sref.get("value")

    if mtow_val is not None and sref_val is not None and sref_val > 0:
        # Convert MTOW to kg if needed
        mtow_units = mtow.get("units", "kg")
        if mtow_units == "lb":
            mtow_kg = mtow_val * 0.453592
        else:
            mtow_kg = mtow_val

        sref_units = sref.get("units", "m**2")
        if sref_units == "ft**2":
            sref_m2 = sref_val * 0.092903
        else:
            sref_m2 = sref_val

        wl = mtow_kg / sref_m2
        findings.append(ValidationFinding(
            check_id="physics.wing_loading_reasonable",
            category="physics",
            severity="warning",
            confidence="medium",
            passed=30.0 < wl < 1000.0,
            message=(
                f"Wing loading = {wl:.0f} kg/m^2 (reasonable)"
                if 30.0 < wl < 1000.0
                else f"Wing loading = {wl:.0f} kg/m^2 -- outside typical range"
            ),
            remediation="Check MTOW and wing area values.",
        ))

    return findings


def validate_optimization_results(
    results: dict,
    context: dict | None = None,
) -> list[ValidationFinding]:
    """Validate optimization convergence and results."""
    findings: list[ValidationFinding] = []
    ctx = context or {}

    opt_success = results.get("optimization_successful")
    if opt_success is not None:
        findings.append(ValidationFinding(
            check_id="numerics.opt_converged",
            category="numerics",
            severity="error",
            confidence="high",
            passed=opt_success,
            message=(
                "Optimizer converged successfully"
                if opt_success
                else "Optimizer did NOT converge -- results may be unreliable"
            ),
            remediation="Check DV bounds, constraints, and max_iterations.",
        ))

    num_iters = results.get("num_iterations")
    if num_iters is not None and num_iters <= 2:
        findings.append(ValidationFinding(
            check_id="numerics.suspicious_convergence",
            category="numerics",
            severity="warning",
            confidence="medium",
            passed=False,
            message=(
                f"Optimizer converged in only {num_iters} iterations -- "
                "DV bounds may be too tight or DVs not applied"
            ),
            remediation="Widen DV bounds or check that DVs are connected.",
        ))

    return findings
