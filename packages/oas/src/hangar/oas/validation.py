"""OAS-specific physics and numerics validation.

Migrated from: OpenAeroStruct/oas_mcp/core/validation.py (OAS-specific parts)
"""

from __future__ import annotations

from typing import Any

from hangar.sdk.validation.checks import ValidationFinding, findings_to_dict


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------


def _check_cd_positive(CD: float) -> ValidationFinding:
    passed = CD > 0
    return ValidationFinding(
        check_id="physics.cd_positive",
        category="physics",
        severity="error",
        confidence="high",
        passed=passed,
        message=f"CD = {CD:.6f} (must be > 0)" if not passed else f"CD = {CD:.6f} > 0 \u2713",
        remediation="Negative CD violates physics. Check mesh quality and that viscous/wave drag is correctly configured.",
    )


def _check_cl_reasonable(CL: float, alpha: float | None) -> ValidationFinding:
    """CL should be reasonable -- context-aware for alpha sweeps with negative alpha."""
    # For negative alpha, negative CL is expected
    if alpha is not None and alpha < -5.0:
        # Allow negative CL but check it's not absurdly large
        passed = abs(CL) < 5.0
        message = (
            f"CL = {CL:.4f} at alpha = {alpha:.1f}\u00b0 (negative CL expected for negative alpha)"
            if passed
            else f"|CL| = {abs(CL):.4f} seems unreasonably large at alpha = {alpha:.1f}\u00b0"
        )
        remediation = "Very large |CL| at negative alpha may indicate mesh or solver issue."
    else:
        # Positive alpha: CL should generally be positive and < ~3
        passed = -0.5 <= CL <= 3.0
        message = (
            f"CL = {CL:.4f} is in expected range [-0.5, 3.0]"
            if passed
            else f"CL = {CL:.4f} is outside expected range [-0.5, 3.0]"
        )
        remediation = (
            "CL > 3 may indicate stall or mesh issues. CL < -0.5 at positive alpha is unusual. "
            "Check twist, angle of attack, and mesh quality."
        )
    return ValidationFinding(
        check_id="physics.cl_reasonable",
        category="physics",
        severity="warning",
        confidence="medium",
        passed=passed,
        message=message,
        remediation=remediation if not passed else "",
    )


def _check_ld_reasonable(CL: float, CD: float, alpha: float | None) -> ValidationFinding:
    """L/D should be reasonable -- positive at moderate positive alpha."""
    if CD <= 0:
        return ValidationFinding(
            check_id="physics.ld_reasonable",
            category="physics",
            severity="info",
            confidence="low",
            passed=True,
            message="L/D check skipped: CD \u2264 0 (see cd_positive check)",
        )
    LD = CL / CD
    # Context-aware: skip check for obviously negative-alpha cases
    if alpha is not None and alpha < 0.0:
        return ValidationFinding(
            check_id="physics.ld_reasonable",
            category="physics",
            severity="info",
            confidence="low",
            passed=True,
            message=f"L/D = {LD:.2f} (skipping positive-L/D check for negative alpha = {alpha:.1f}\u00b0)",
        )
    passed = LD > 0
    return ValidationFinding(
        check_id="physics.ld_reasonable",
        category="physics",
        severity="warning",
        confidence="medium",
        passed=passed,
        message=f"L/D = {LD:.2f}" + (" > 0 \u2713" if passed else " \u2264 0 \u2014 unexpected at positive alpha"),
        remediation="Negative L/D at positive alpha suggests CL < 0. Check wing orientation and twist.",
    )


def _check_cd_not_too_large(CD: float) -> ValidationFinding:
    """CD > 1.0 is physically implausible for a lifting wing."""
    passed = CD < 1.0
    return ValidationFinding(
        check_id="physics.cd_not_too_large",
        category="physics",
        severity="error",
        confidence="high",
        passed=passed,
        message=f"CD = {CD:.4f} < 1.0 \u2713" if passed else f"CD = {CD:.4f} \u2265 1.0 \u2014 physically implausible",
        remediation="CD \u2265 1 is physically impossible for a subsonic lifting wing. Check mesh, Mach, and drag model settings.",
    )


# ---------------------------------------------------------------------------
# Aerodynamic-only validation
# ---------------------------------------------------------------------------


def validate_aero(results: dict, context: dict | None = None) -> list[ValidationFinding]:
    """Run all aerodynamic validation checks.

    Parameters
    ----------
    results:
        Output of ``extract_aero_results``.
    context:
        Dict with optional keys: ``alpha`` (float), ``alpha_start`` (float).
    """
    ctx = context or {}
    alpha = ctx.get("alpha")

    CL = results.get("CL", 0.0)
    CD = results.get("CD", 0.0)

    findings: list[ValidationFinding] = [
        _check_cd_positive(CD),
        _check_cd_not_too_large(CD),
        _check_cl_reasonable(CL, alpha),
        _check_ld_reasonable(CL, CD, alpha),
    ]
    return findings


# ---------------------------------------------------------------------------
# Drag polar validation
# ---------------------------------------------------------------------------


def validate_drag_polar(results: dict, context: dict | None = None) -> list[ValidationFinding]:
    """Validate a drag polar (sweep over alpha).

    Checks:
    - CD always > 0
    - CL monotonically increases with alpha (physics.cl_monotonic)
    - L/D polar has a clear maximum (physics.ld_has_max)
    """
    ctx = context or {}
    CLs = results.get("CL", [])
    CDs = results.get("CD", [])
    alphas = results.get("alpha_deg", [])

    findings: list[ValidationFinding] = []

    # CD > 0 everywhere
    neg_cd = [i for i, cd in enumerate(CDs) if cd <= 0]
    findings.append(ValidationFinding(
        check_id="physics.cd_positive_polar",
        category="physics",
        severity="error",
        confidence="high",
        passed=len(neg_cd) == 0,
        message=(
            "All CD values > 0 \u2713"
            if len(neg_cd) == 0
            else f"CD \u2264 0 at {len(neg_cd)} alpha point(s): indices {neg_cd}"
        ),
        remediation="CD \u2264 0 at any alpha is physically impossible. Check drag model and mesh.",
    ))

    # CL monotonically increasing with alpha
    if len(CLs) >= 2:
        non_monotone = [
            i for i in range(1, len(CLs))
            if CLs[i] < CLs[i - 1] - 1e-4
        ]
        findings.append(ValidationFinding(
            check_id="physics.cl_monotonic",
            category="physics",
            severity="warning",
            confidence="medium",
            passed=len(non_monotone) == 0,
            message=(
                "CL increases monotonically with alpha \u2713"
                if len(non_monotone) == 0
                else f"CL is non-monotone at {len(non_monotone)} alpha transition(s)"
            ),
            remediation=(
                "Non-monotone CL vs alpha may indicate flow separation (not modeled by VLM) "
                "or numerical issues. Consider a narrower alpha range."
            ),
        ))

    # Best L/D exists
    best = results.get("best_L_over_D", {})
    best_ld = best.get("L_over_D") if best else None
    findings.append(ValidationFinding(
        check_id="physics.ld_has_max",
        category="physics",
        severity="warning",
        confidence="medium",
        passed=best_ld is not None and best_ld > 0,
        message=(
            f"Best L/D = {best_ld:.2f} at alpha = {best.get('alpha_deg', '?')}\u00b0 \u2713"
            if best_ld and best_ld > 0
            else "No positive L/D found in polar"
        ),
        remediation="No positive L/D suggests all computed CL values are negative. Check alpha range.",
    ))

    return findings


# ---------------------------------------------------------------------------
# Aerostructural validation
# ---------------------------------------------------------------------------


def validate_aerostruct(results: dict, context: dict | None = None) -> list[ValidationFinding]:
    """Run all aerostructural validation checks.

    Includes all aero checks plus structural ones.
    """
    ctx = context or {}
    alpha = ctx.get("alpha")

    CL = results.get("CL", 0.0)
    CD = results.get("CD", 0.0)

    findings: list[ValidationFinding] = [
        _check_cd_positive(CD),
        _check_cd_not_too_large(CD),
        _check_cl_reasonable(CL, alpha),
        _check_ld_reasonable(CL, CD, alpha),
    ]

    # L=W residual (normalized)
    lew = results.get("L_equals_W")
    if lew is not None:
        # L_equals_W is L - W; normalize by W0 if available
        W0 = ctx.get("W0", 1.0)  # fallback to avoid div-by-zero
        normalized = abs(lew) / max(abs(W0), 1.0)
        passed = normalized < 0.01  # 1% tolerance
        findings.append(ValidationFinding(
            check_id="numerics.lew_residual",
            category="numerics",
            severity="warning",
            confidence="high",
            passed=passed,
            message=(
                f"|L - W| / W\u2080 = {normalized:.4f} < 0.01 \u2713"
                if passed
                else f"|L - W| / W\u2080 = {normalized:.4f} \u2265 0.01 \u2014 lift-weight balance not satisfied"
            ),
            remediation=(
                "Large L=W residual means the solver did not converge the coupled aero-structural "
                "trim. Consider tighter solver tolerances or adjusting W0."
            ),
        ))

    # Structural mass positive
    struct_mass = results.get("structural_mass")
    if struct_mass is not None:
        passed = struct_mass > 0
        findings.append(ValidationFinding(
            check_id="physics.structural_mass_positive",
            category="physics",
            severity="error",
            confidence="high",
            passed=passed,
            message=(
                f"Structural mass = {struct_mass:.1f} kg > 0 \u2713"
                if passed
                else f"Structural mass = {struct_mass:.1f} kg \u2264 0 \u2014 physically impossible"
            ),
            remediation="Non-positive structural mass indicates a problem with material properties or FEM setup.",
        ))

    # Per-surface structural failure checks
    surfaces_by_name = {
        s["name"]: s for s in ctx.get("surfaces", []) if isinstance(s, dict)
    }
    for surf_name, surf_res in results.get("surfaces", {}).items():
        failure = surf_res.get("failure")
        if failure is not None:
            struct_failed = failure > 1.0
            is_composite = surf_res.get(
                "material_model", surfaces_by_name.get(surf_name, {}).get("useComposite", False)
            ) == "composite" or surfaces_by_name.get(surf_name, {}).get("useComposite", False)

            if struct_failed:
                if is_composite:
                    fail_msg = f"Surface '{surf_name}': failure index = {failure:.4f} > 1.0 \u2014 Tsai-Wu FAILURE"
                    fail_rem = (
                        "Tsai-Wu failure criterion exceeded. "
                        "Increase skin/spar thickness, adjust ply layup (angles/fractions), or reduce load factor."
                    )
                else:
                    fail_msg = f"Surface '{surf_name}': failure index = {failure:.4f} > 1.0 \u2014 STRUCTURAL FAILURE"
                    fail_rem = (
                        "failure > 1 means von Mises stress exceeds yield/safety_factor. "
                        "Increase thickness, reduce load factor, or choose a stronger material."
                    )
            else:
                fail_msg = f"Surface '{surf_name}': failure index = {failure:.4f} \u2264 1.0 \u2713 (structure intact)"
                fail_rem = ""

            findings.append(ValidationFinding(
                check_id=f"constraints.structural_failure.{surf_name}",
                category="constraints",
                severity="error" if struct_failed else "info",
                confidence="high",
                passed=not struct_failed,
                message=fail_msg,
                remediation=fail_rem,
            ))

    # Fuel burn sanity (if present)
    fuelburn = results.get("fuelburn")
    if fuelburn is not None:
        passed = fuelburn > 0
        findings.append(ValidationFinding(
            check_id="physics.fuelburn_positive",
            category="physics",
            severity="error",
            confidence="high",
            passed=passed,
            message=(
                f"Fuel burn = {fuelburn:.1f} kg > 0 \u2713"
                if passed
                else f"Fuel burn = {fuelburn:.1f} kg \u2264 0 \u2014 physically impossible"
            ),
            remediation="Non-positive fuel burn indicates a problem with mission parameters (CT, R, W0).",
        ))

    return findings


# ---------------------------------------------------------------------------
# Stability validation
# ---------------------------------------------------------------------------


def validate_stability(results: dict, context: dict | None = None) -> list[ValidationFinding]:
    """Run stability-specific validation checks."""
    findings: list[ValidationFinding] = []

    # CL_alpha should be positive (typically 2pi/rad ~ 0.11/deg for thin wings)
    cl_alpha = results.get("CL_alpha")
    if cl_alpha is not None:
        # Note: sign convention can vary; this is an "info" only check
        findings.append(ValidationFinding(
            check_id="stability.cl_alpha_sign",
            category="stability",
            severity="info",
            confidence="low",
            passed=cl_alpha > 0,
            message=f"CL_alpha = {cl_alpha:.4f} /deg" + (" (positive \u2713)" if cl_alpha > 0 else " (negative \u2014 check sign convention)"),
            remediation="Negative CL_alpha is unusual but may occur depending on sign conventions.",
        ))

    # Static margin: flag dangerous values as warnings
    sm = results.get("static_margin")
    if sm is not None:
        dangerous = sm < 0.05 or sm > 0.40
        findings.append(ValidationFinding(
            check_id="stability.static_margin",
            category="stability",
            severity="warning" if dangerous else "info",
            confidence="high",
            passed=not dangerous,
            message=(
                f"Static margin = {sm:.4f} (statically stable)"
                if 0.05 <= sm <= 0.40
                else f"Static margin = {sm:.4f} — outside typical range [0.05, 0.40]"
                if sm > 0
                else f"Static margin = {sm:.4f} (statically UNSTABLE)"
            ),
            remediation=(
                "Static margin < 0.05 means nearly neutral stability (difficult to control). "
                "Static margin > 0.40 means excessive stability (poor maneuverability, tail sizing issue)."
                if dangerous else ""
            ),
        ))

    return findings


# ---------------------------------------------------------------------------
# Optimization validation
# ---------------------------------------------------------------------------


def validate_optimization(results: dict, context: dict | None = None) -> list[ValidationFinding]:
    """Validate optimization results."""
    findings: list[ValidationFinding] = []
    ctx = context or {}

    success = results.get("success", False)
    findings.append(ValidationFinding(
        check_id="numerics.optimizer_converged",
        category="numerics",
        severity="error" if not success else "info",
        confidence="high",
        passed=success,
        message="Optimizer converged successfully \u2713" if success else "Optimizer did NOT converge",
        remediation=(
            "Optimizer failed to converge. Try: looser tolerance, smaller design variable bounds, "
            "better initial conditions, or fewer design variables."
            if not success
            else ""
        ),
    ))

    # Run aero/aerostruct checks on final results
    final = results.get("final_results", {})
    if final:
        # Minimal checks on final design
        CD = final.get("CD", 0.0)
        findings.append(_check_cd_positive(CD))
        findings.append(_check_cd_not_too_large(CD))

    # --- Convergence diagnostics (especially useful when success=False) ---
    findings.extend(_diagnose_optimization(results, ctx))

    return findings


def _diagnose_optimization(
    results: dict, context: dict
) -> list[ValidationFinding]:
    """Generate diagnostic findings from optimization history and final state.

    These provide actionable remediation hints beyond the generic "did not
    converge" message -- e.g. scaling issues, constraint violations, DVs pinned
    at bounds.
    """
    findings: list[ValidationFinding] = []
    final = results.get("final_results", {})
    history = results.get("optimization_history", {})
    obj_vals = history.get("objective_values", [])

    # 1. Iteration-limit check
    max_iters = context.get("max_iterations", 200)
    n_iters = history.get("num_iterations", len(obj_vals))
    if n_iters >= max_iters:
        findings.append(ValidationFinding(
            check_id="numerics.iteration_limit_reached",
            category="numerics",
            severity="warning",
            confidence="high",
            passed=False,
            message=f"Optimizer used all {n_iters} iterations (limit={max_iters})",
            remediation=(
                "The optimizer exhausted its iteration budget. "
                "Increase max_iterations, or improve scaling "
                "(objective_scaler, DV scaler) to help SLSQP converge faster."
            ),
        ))

    # 2. Objective scaling heuristic
    if obj_vals:
        obj_magnitude = abs(obj_vals[0])
        obj_scaler = context.get("objective_scaler", 1.0)
        scaled_magnitude = obj_magnitude * obj_scaler
        if scaled_magnitude > 1e4 or scaled_magnitude < 1e-4:
            findings.append(ValidationFinding(
                check_id="numerics.objective_scaling",
                category="numerics",
                severity="warning",
                confidence="medium",
                passed=False,
                message=(
                    f"Objective magnitude \u2248 {obj_magnitude:.2e} with scaler={obj_scaler} "
                    f"\u2192 scaled value \u2248 {scaled_magnitude:.2e} (ideal range: 0.1\u2013100)"
                ),
                remediation=(
                    f"SLSQP works best when the scaled objective is O(1). "
                    f"Try objective_scaler \u2248 {1.0 / obj_magnitude:.1e}."
                ),
            ))

    # 3. Constraint violations at termination
    for surf_name, surf_res in final.get("surfaces", {}).items():
        failure = surf_res.get("failure")
        if failure is not None and failure > 1e-6:
            findings.append(ValidationFinding(
                check_id=f"constraints.failure_violated.{surf_name}",
                category="constraints",
                severity="error",
                confidence="high",
                passed=False,
                message=(
                    f"Surface '{surf_name}': failure = {failure:.4f} > 0 "
                    f"(max stress exceeds allowable by {failure * 100:.1f}%)"
                ),
                remediation=(
                    "The structural failure constraint is violated at the optimum. "
                    "This usually means the optimizer could not find a feasible design. "
                    "Try: thicker initial thickness_cp, wider thickness bounds, "
                    "or add objective_scaler/DV scaler to improve convergence."
                ),
            ))

    # 4. Design variables pinned at bounds
    dv_history = history.get("dv_history", {})
    opt_dvs = results.get("optimized_design_variables", {})
    initial_dvs = history.get("initial_dvs", {})
    dv_specs = context.get("design_variables", [])
    dv_bounds = {dv["name"]: dv for dv in dv_specs if isinstance(dv, dict)}

    for dv_name, final_val in opt_dvs.items():
        spec = dv_bounds.get(dv_name, {})
        lower = spec.get("lower")
        upper = spec.get("upper")
        if lower is None or upper is None:
            continue
        vals = final_val if isinstance(final_val, list) else [final_val]
        pinned = []
        for i, v in enumerate(vals):
            bound_range = abs(upper - lower)
            if bound_range == 0:
                continue
            tol = bound_range * 1e-4
            if abs(v - lower) < tol:
                pinned.append(f"[{i}] at lower={lower}")
            elif abs(v - upper) < tol:
                pinned.append(f"[{i}] at upper={upper}")
        if pinned:
            findings.append(ValidationFinding(
                check_id=f"numerics.dv_at_bound.{dv_name}",
                category="numerics",
                severity="warning",
                confidence="medium",
                passed=False,
                message=f"DV '{dv_name}' pinned at bound: {', '.join(pinned)}",
                remediation=(
                    f"Design variable '{dv_name}' hit its bound, which may indicate "
                    f"the bound is too restrictive or the optimizer wants to go further. "
                    f"Consider widening the bounds for '{dv_name}'."
                ),
            ))

    # 5. Objective stagnation (last 20% of iterations show < 0.1% change)
    if len(obj_vals) >= 10:
        tail_start = int(len(obj_vals) * 0.8)
        tail = obj_vals[tail_start:]
        if len(tail) >= 2 and tail[0] != 0:
            rel_change = abs(tail[-1] - tail[0]) / abs(tail[0])
            if rel_change < 1e-3:
                findings.append(ValidationFinding(
                    check_id="numerics.objective_stagnant",
                    category="numerics",
                    severity="info",
                    confidence="medium",
                    passed=True,
                    message=(
                        f"Objective changed < 0.1% over final {len(tail)} iterations "
                        f"({tail[0]:.4e} \u2192 {tail[-1]:.4e})"
                    ),
                    remediation=(
                        "The objective plateaued. If the optimizer did not converge, "
                        "this suggests it is near a local minimum but constraints "
                        "may be preventing further progress."
                    ),
                ))

    return findings
