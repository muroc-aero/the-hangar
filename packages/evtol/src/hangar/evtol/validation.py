"""Physics and numerics validation for evtol results.

Each check returns a ValidationFinding from the SDK. Findings are advisory
context for the agent -- they never raise -- except that a *failed* MTOW
convergence is the load-bearing one: the divergence safeguard in evtolpy
raises before we get here, but a non-converged-but-returned result is flagged
as an error finding so a silent success can't slip through.
"""

from __future__ import annotations

from hangar.sdk.validation.checks import ValidationFinding, findings_to_dict  # noqa: F401

from hangar.evtol.config.limits import (
    BATT_MASS_FRAC_MAX,
    BATT_MASS_FRAC_MIN,
    DISK_LOADING_MAX,
    DISK_LOADING_MIN,
)


def _ok(check_id, category, message) -> ValidationFinding:
    return ValidationFinding(
        check_id=check_id, category=category, severity="info",
        confidence="high", passed=True, message=message,
    )


def _warn(check_id, category, message, remediation="") -> ValidationFinding:
    return ValidationFinding(
        check_id=check_id, category=category, severity="warning",
        confidence="medium", passed=False, message=message, remediation=remediation,
    )


# ---------------------------------------------------------------------------
# Mission-analysis checks
# ---------------------------------------------------------------------------

def _check_energy_nonneg(energy: dict) -> ValidationFinding:
    negatives = {k: v for k, v in energy.items() if v < 0}
    if negatives:
        return _warn(
            "energy.nonnegative", "physics",
            f"Negative segment energy for {sorted(negatives)}.",
            "Check mission segment speeds/durations and power efficiencies.",
        )
    return _ok("energy.nonnegative", "physics", "All segment energies are non-negative.")


def _check_energy_total_consistency(results: dict) -> ValidationFinding:
    energy = results.get("energy_kw_hr", {})
    total = results.get("totals", {}).get("total_mission_energy_kw_hr")
    if total is None or not energy:
        return _ok("energy.total_consistency", "numerics",
                   "Total energy not available; skipping consistency check.")
    # The upstream total is the non-reserve mission energy; check it does not
    # exceed the sum of all segments (reserves included) and is positive.
    seg_sum = sum(energy.values())
    if total <= 0:
        return _warn("energy.total_consistency", "physics",
                     f"Total mission energy is non-positive ({total:.4f} kW*hr).")
    if total > seg_sum + 1e-6:
        return _warn(
            "energy.total_consistency", "numerics",
            f"Total mission energy ({total:.3f}) exceeds the sum of all "
            f"segment energies ({seg_sum:.3f} kW*hr).",
        )
    return _ok("energy.total_consistency", "numerics",
               f"Total mission energy = {total:.3f} kW*hr (consistent with segments).")


def _check_battery_mass_fraction(results: dict) -> ValidationFinding:
    totals = results.get("totals", {})
    batt = totals.get("battery_mass_kg")
    mtow = results.get("max_takeoff_mass_kg") or totals.get("sized_mtow_kg")
    if not batt or not mtow:
        return _ok("battery.mass_fraction", "physics",
                   "Battery mass fraction not available; skipping.")
    frac = batt / mtow
    if BATT_MASS_FRAC_MIN <= frac <= BATT_MASS_FRAC_MAX:
        return _ok("battery.mass_fraction", "physics",
                   f"Battery mass fraction = {frac:.1%} (within typical eVTOL range).")
    return _warn(
        "battery.mass_fraction", "physics",
        f"Battery mass fraction = {frac:.1%} is outside the typical eVTOL range "
        f"[{BATT_MASS_FRAC_MIN:.0%}, {BATT_MASS_FRAC_MAX:.0%}].",
        "Check battery specific energy, mission energy, and MTOW.",
    )


def _check_disk_loading(results: dict) -> ValidationFinding:
    dl = results.get("propulsion", {}).get("disk_loading_kg_p_m2")
    if dl is None:
        return _ok("propulsion.disk_loading", "physics",
                   "Disk loading not available; skipping.")
    if DISK_LOADING_MIN <= dl <= DISK_LOADING_MAX:
        return _ok("propulsion.disk_loading", "physics",
                   f"Disk loading = {dl:.1f} kg/m^2 (plausible for rotorcraft).")
    return _warn(
        "propulsion.disk_loading", "physics",
        f"Disk loading = {dl:.1f} kg/m^2 is outside the plausible window "
        f"[{DISK_LOADING_MIN}, {DISK_LOADING_MAX}].",
        "Check rotor count and rotor diameter.",
    )


def validate_mission_results(results: dict) -> list[ValidationFinding]:
    """Run all checks for a run_mission_analysis result."""
    return [
        _check_energy_nonneg(results.get("energy_kw_hr", {})),
        _check_energy_total_consistency(results),
        _check_battery_mass_fraction(results),
        _check_disk_loading(results),
    ]


# ---------------------------------------------------------------------------
# Sizing checks
# ---------------------------------------------------------------------------

def _check_mtow_converged(results: dict) -> ValidationFinding:
    if results.get("converged"):
        return _ok(
            "mtow.converged", "numerics",
            f"MTOW converged to {results.get('sized_mtow_kg'):.2f} kg in "
            f"{results.get('iterations')} iterations.",
        )
    return ValidationFinding(
        check_id="mtow.converged", category="numerics", severity="error",
        confidence="high", passed=False,
        message=(
            f"MTOW iteration ran {results.get('iterations')} iterations without "
            f"meeting the convergence tolerance."
        ),
        remediation=(
            "The template parameters may be physically self-inconsistent. Check "
            "wingspan, rotor count/diameter, EPU/battery mass scaling, and mission "
            "energy. A diverging iteration raises before this point."
        ),
    )


def validate_sizing_results(results: dict) -> list[ValidationFinding]:
    """Run all checks for a run_sizing result."""
    return [
        _check_mtow_converged(results),
        _check_battery_mass_fraction(results),
    ]
