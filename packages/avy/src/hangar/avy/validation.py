"""Physics and numerics validation for Aviary sizing results.

Each check returns a ValidationFinding from the SDK. The optimizer-success
check is the load-bearing one: optimizer non-convergence is Aviary's primary
failure mode and it does NOT raise -- it returns a solved-looking problem
with a failed result flag.
"""

from __future__ import annotations

from hangar.sdk.validation.checks import ValidationFinding, findings_to_dict  # noqa: F401


def _check_optimizer_success(success: bool | None, optimizer: str, max_iter: int) -> ValidationFinding:
    if success is None:
        return ValidationFinding(
            check_id="optimizer.success",
            category="numerics",
            severity="warning",
            confidence="high",
            passed=False,
            message="Optimizer result flag not available.",
            remediation="Inspect the run logs; treat results as unverified.",
        )
    if not success:
        return ValidationFinding(
            check_id="optimizer.success",
            category="numerics",
            severity="error",
            confidence="high",
            passed=False,
            message=f"Optimizer {optimizer} did NOT converge (max_iter={max_iter}). "
            "All reported values are from the last iterate, not an optimum.",
            remediation="Increase max_iter, relax the mission (fewer constraints, "
            "wider bounds), or check the aircraft deck for inconsistent inputs.",
        )
    return ValidationFinding(
        check_id="optimizer.success",
        category="numerics",
        severity="info",
        confidence="high",
        passed=True,
        message=f"Optimizer {optimizer} converged.",
    )


def _check_fuel_fraction(gross: float | None, fuel: float | None) -> ValidationFinding:
    if not gross or not fuel:
        return ValidationFinding(
            check_id="fuel.fraction",
            category="physics",
            severity="info",
            confidence="low",
            passed=True,
            message="Gross mass or fuel mass unavailable; skipping fuel-fraction check.",
        )
    frac = fuel / gross
    if 0.03 <= frac <= 0.55:
        return ValidationFinding(
            check_id="fuel.fraction",
            category="physics",
            severity="info",
            confidence="medium",
            passed=True,
            message=f"Fuel fraction = {frac:.3f} is within the typical transport range [0.03, 0.55].",
        )
    return ValidationFinding(
        check_id="fuel.fraction",
        category="physics",
        severity="warning",
        confidence="medium",
        passed=False,
        message=f"Fuel fraction = {frac:.3f} outside typical transport range [0.03, 0.55].",
        remediation="Check target range, engine deck, and mass-method settings.",
    )


def _check_mass_closure(
    gross: float | None, zero_fuel: float | None, fuel: float | None
) -> ValidationFinding:
    if not gross or not zero_fuel or fuel is None:
        return ValidationFinding(
            check_id="mass.closure",
            category="physics",
            severity="info",
            confidence="low",
            passed=True,
            message="Mass components unavailable; skipping closure check.",
        )
    residual = abs(gross - (zero_fuel + fuel)) / gross
    if residual <= 0.01:
        return ValidationFinding(
            check_id="mass.closure",
            category="physics",
            severity="info",
            confidence="high",
            passed=True,
            message=f"Mass closure: |gross - (zero_fuel + fuel)| / gross = {residual:.4f}.",
        )
    return ValidationFinding(
        check_id="mass.closure",
        category="physics",
        severity="warning",
        confidence="medium",
        passed=False,
        message=f"Mass closure residual {residual:.3f} exceeds 1% of gross mass.",
        remediation="The mass residual constraint may not be satisfied; check "
        "optimizer convergence and reserve-fuel settings.",
    )


def _check_range_target(
    range_nmi: float | None, target_range_nmi: float | None
) -> ValidationFinding:
    if not range_nmi or not target_range_nmi:
        return ValidationFinding(
            check_id="range.target",
            category="physics",
            severity="info",
            confidence="low",
            passed=True,
            message="No range target to check against.",
        )
    rel = abs(range_nmi - target_range_nmi) / target_range_nmi
    if rel <= 0.01:
        return ValidationFinding(
            check_id="range.target",
            category="physics",
            severity="info",
            confidence="high",
            passed=True,
            message=f"Mission range {range_nmi:.1f} nmi matches target "
            f"{target_range_nmi:.1f} nmi (rel err {rel:.2e}).",
        )
    return ValidationFinding(
        check_id="range.target",
        category="physics",
        severity="warning",
        confidence="high",
        passed=False,
        message=f"Mission range {range_nmi:.1f} nmi misses target "
        f"{target_range_nmi:.1f} nmi by {rel:.1%}.",
        remediation="Range constraint not met -- usually optimizer non-convergence.",
    )


def _check_transport_domain(gross: float | None) -> ValidationFinding:
    if not gross:
        return ValidationFinding(
            check_id="domain.transport",
            category="physics",
            severity="info",
            confidence="low",
            passed=True,
            message="Gross mass unavailable; skipping domain check.",
        )
    if 10_000 <= gross <= 1_200_000:
        return ValidationFinding(
            check_id="domain.transport",
            category="physics",
            severity="info",
            confidence="medium",
            passed=True,
            message=f"Gross mass {gross:,.0f} lbm is within the transport-category "
            "domain the FLOPS/GASP correlations are calibrated for.",
        )
    return ValidationFinding(
        check_id="domain.transport",
        category="physics",
        severity="warning",
        confidence="medium",
        passed=False,
        message=f"Gross mass {gross:,.0f} lbm is outside the transport-category "
        "calibration domain of the FLOPS/GASP empirical methods.",
        remediation="Treat mass-buildup results as extrapolation; consider a "
        "tool calibrated for this vehicle class.",
    )


def design_point_finding(success: bool | None) -> ValidationFinding:
    """Convergence of the internal sizing underneath an off-design run.

    The off-design mission can 'converge' from an unsized last iterate, so
    the off-design optimizer flag alone is not sufficient.
    """
    if success:
        return ValidationFinding(
            check_id="optimizer.design_point_success",
            category="numerics",
            severity="info",
            confidence="high",
            passed=True,
            message="The internal sizing (design point) converged.",
        )
    return ValidationFinding(
        check_id="optimizer.design_point_success",
        category="numerics",
        severity="error",
        confidence="high",
        passed=False,
        message="The internal sizing did NOT converge -- the off-design "
        "mission was flown with an unsized design; all values are unreliable.",
        remediation="Fix the sizing first (see run_sizing with the same "
        "aircraft): increase max_iter or simplify the mission.",
    )


def payload_range_findings(payload_range: dict) -> ValidationFinding:
    """Completeness of the payload-range diagram.

    When the sizing fails, the off-design missions are skipped and only the
    first two points exist; a partial diagram must fail validation loudly.
    """
    points = payload_range.get("points") or []
    od_success = payload_range.get("off_design_success") or []
    if len(points) >= 4 and all(od_success):
        return ValidationFinding(
            check_id="payload_range.complete",
            category="numerics",
            severity="info",
            confidence="high",
            passed=True,
            message="All four payload-range points computed and converged.",
        )
    return ValidationFinding(
        check_id="payload_range.complete",
        category="numerics",
        severity="error",
        confidence="high",
        passed=False,
        message=f"Payload-range diagram incomplete: {len(points)}/4 points, "
        f"off-design convergence flags {od_success}. The off-design missions "
        "are skipped when the sizing fails.",
        remediation="Check the optimizer.success finding; fix the sizing "
        "before reading the diagram.",
    )


def validate_sizing_results(
    results: dict,
    optimizer: str,
    max_iter: int,
    target_range_nmi: float | None = None,
) -> list[ValidationFinding]:
    """Run all physics/numerics checks on a sizing result set."""
    perf = results.get("performance", {})
    opt = results.get("optimizer", {})
    return [
        _check_optimizer_success(opt.get("success"), optimizer, max_iter),
        _check_fuel_fraction(perf.get("gross_mass_lbm"), perf.get("total_fuel_mass_lbm")),
        _check_mass_closure(
            perf.get("gross_mass_lbm"),
            perf.get("zero_fuel_mass_lbm"),
            perf.get("total_fuel_mass_lbm"),
        ),
        _check_range_target(perf.get("range_nmi"), target_range_nmi),
        _check_transport_domain(perf.get("gross_mass_lbm")),
    ]


def external_subsystem_findings(
    specs: list[dict], template: str | None, wing_mass_lbm: float | None
) -> list[ValidationFinding]:
    """Findings for runs with external subsystems attached.

    The deck-scope check carries the WP4 caveat: the *default* OAS wing
    mesh is hard-coded to the advanced-single-aisle planform, so on any
    other deck the wing mass is not physically meaningful (warning, not
    error -- the numbers still solve) unless the config picks a
    deck-derived or explicit planform.
    """
    from hangar.avy.subsystems.oas_wing_mass import SUPPORTED_DECKS, mesh_source

    findings = []
    oas_specs = [s for s in specs if s.get("name") == "oas_wing_mass"]
    if oas_specs:
        source = mesh_source(oas_specs[0].get("config"))
        if source != "upstream-hardcoded":
            findings.append(
                ValidationFinding(
                    check_id="subsystem.deck_scope",
                    category="physics",
                    severity="info",
                    confidence="high",
                    passed=True,
                    message=f"oas_wing_mass wing mesh source: {source}. "
                    + (
                        "Simple-trapezoid planform derived from the deck's "
                        "span/area/taper/sweep (deck sweep applied as LE "
                        "sweep) -- planform-consistent with this aircraft, "
                        "cruder than a multi-segment FLOPS definition."
                        if source == "deck-derived"
                        else "Explicit planform from the subsystem config."
                    ),
                )
            )
        elif template in SUPPORTED_DECKS:
            findings.append(
                ValidationFinding(
                    check_id="subsystem.deck_scope",
                    category="physics",
                    severity="info",
                    confidence="high",
                    passed=True,
                    message=f"oas_wing_mass supports the '{template}' deck "
                    "(its wing mesh matches this planform).",
                )
            )
        else:
            findings.append(
                ValidationFinding(
                    check_id="subsystem.deck_scope",
                    category="physics",
                    severity="warning",
                    confidence="high",
                    passed=False,
                    message=f"oas_wing_mass's default wing mesh is hard-coded "
                    f"to the advanced-single-aisle planform; deck "
                    f"'{template}' has different wing geometry, so the OAS "
                    "wing mass is not physically meaningful for this aircraft.",
                    remediation="Set the subsystem's planform config to "
                    "'deck' (derives the planform from this deck's "
                    "span/area/taper/sweep), use one of the supported decks "
                    f"({', '.join(SUPPORTED_DECKS)}), or treat the result "
                    "as a plumbing exercise only.",
                )
            )
        findings.append(
            ValidationFinding(
                check_id="subsystem.wing_mass_applied",
                category="physics",
                severity="info",
                confidence="high",
                passed=wing_mass_lbm is not None and wing_mass_lbm > 0,
                message=(
                    f"OAS wingbox wing mass applied to Aircraft.Wing.MASS: "
                    f"{wing_mass_lbm:.1f} lbm (replaces the FLOPS estimate)."
                    if wing_mass_lbm
                    else "OAS wing mass output missing from the solved problem."
                ),
            )
        )
    return findings
