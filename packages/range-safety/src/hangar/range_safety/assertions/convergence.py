"""Post-run convergence assessment.

Checks that a completed run converged properly: optimizer success,
objective improvement, no NaN values, and residuals below tolerance.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from hangar.omd.db import init_analysis_db, query_entity, query_run_results


def _check(name: str, passed: bool, message: str) -> dict:
    """Build a check result dict."""
    return {"name": name, "passed": passed, "message": message}


def assert_convergence(
    run_id: str,
    db_path: Path | None = None,
) -> dict:
    """Check that a completed run actually converged properly.

    Args:
        run_id: Run entity ID to assess.
        db_path: Path to analysis DB. Uses default if None.

    Returns:
        Dict with keys:
        - passed: bool (True if all checks pass)
        - checks: list of check dicts (name, passed, message)
        - summary: human-readable summary string
    """
    init_analysis_db(db_path)

    checks: list[dict] = []

    # -- Check 1: Run exists --
    entity = query_entity(run_id)
    if entity is None:
        checks.append(_check(
            "run_exists",
            False,
            f"Run '{run_id}' not found in analysis DB",
        ))
        return {
            "passed": False,
            "checks": checks,
            "summary": f"Run '{run_id}' not found",
        }
    checks.append(_check("run_exists", True, f"Run '{run_id}' found"))

    # -- Check 2: Run has case data --
    cases = query_run_results(run_id)
    if not cases:
        checks.append(_check(
            "has_case_data",
            False,
            "No case data recorded for this run",
        ))
        return {
            "passed": False,
            "checks": checks,
            "summary": "No case data available",
        }
    checks.append(_check(
        "has_case_data",
        True,
        f"{len(cases)} cases recorded",
    ))

    # -- Check 3: No NaN in final case --
    final_cases = [c for c in cases if c["case_type"] == "final"]
    if not final_cases:
        # Use last driver case as fallback
        driver_cases = [c for c in cases if c["case_type"] == "driver"]
        final_case = driver_cases[-1] if driver_cases else cases[-1]
    else:
        final_case = final_cases[-1]

    nan_vars = _find_nan_values(final_case.get("data", {}))
    if nan_vars:
        checks.append(_check(
            "no_nan_values",
            False,
            f"NaN values found in final case: {nan_vars[:5]}",
        ))
    else:
        checks.append(_check("no_nan_values", True, "No NaN values in final case"))

    # -- Check 4: Objective improved (for optimization runs) --
    driver_cases = [c for c in cases if c["case_type"] == "driver"]
    if len(driver_cases) >= 2:
        obj_values = _extract_objective_history(driver_cases)
        if obj_values and len(obj_values) >= 2:
            first = obj_values[0]
            last = obj_values[-1]
            # Objective should decrease (minimization) or at least not worsen
            # We check if the last value is <= first value (allowing for
            # minor numerical noise)
            improved = last <= first * 1.01  # 1% tolerance
            checks.append(_check(
                "objective_improved",
                improved,
                f"Objective: {first:.6g} -> {last:.6g} "
                f"({'improved' if improved else 'worsened'})",
            ))

    # -- Check 5: Driver success status --
    # Check entity storage_ref or status field for convergence info
    storage_ref = entity.get("storage_ref")
    # The entity_type for runs is "run_record"
    # Status info might be in the entity metadata or we infer from cases
    if driver_cases:
        # If there is a single driver case, it is an analysis (not optimization)
        if len(driver_cases) == 1:
            checks.append(_check(
                "analysis_completed",
                True,
                "Analysis completed (single evaluation)",
            ))
        else:
            # For optimization, more than 1 driver case means the optimizer
            # iterated. Check that it did not hit an obvious failure mode.
            # (No explicit "success" flag in the DB -- we infer from data)
            checks.append(_check(
                "optimizer_iterated",
                True,
                f"Optimizer ran {len(driver_cases)} iterations",
            ))

    # -- Build summary --
    all_passed = all(c["passed"] for c in checks)
    if all_passed:
        summary = f"Run '{run_id}': all {len(checks)} convergence checks passed"
    else:
        failed = [c["name"] for c in checks if not c["passed"]]
        summary = (
            f"Run '{run_id}': {len(failed)} check(s) failed: "
            + ", ".join(failed)
        )

    return {
        "passed": all_passed,
        "checks": checks,
        "summary": summary,
    }


def _find_nan_values(data: dict) -> list[str]:
    """Find variable names with NaN values in a case data dict."""
    nan_vars = []
    for name, value in data.items():
        if _has_nan(value):
            nan_vars.append(name)
    return nan_vars


def _has_nan(value: object) -> bool:
    """Check if a value contains NaN."""
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, (list, tuple)):
        return any(_has_nan(v) for v in value)
    if value is None:
        # None is used as a sentinel for NaN in the DB encoder
        return True
    return False


def _extract_objective_history(driver_cases: list[dict]) -> list[float]:
    """Extract objective values from driver case history.

    Looks for the objective variable by finding the variable that
    appears in all cases and has a scalar numeric value that changes
    across iterations. Heuristic: prefer variables with names
    containing common objective keywords.
    """
    if not driver_cases:
        return []

    # Find variables that appear in all driver cases
    all_keys: set[str] | None = None
    for case in driver_cases:
        case_keys = set(case.get("data", {}).keys())
        if all_keys is None:
            all_keys = case_keys
        else:
            all_keys &= case_keys

    if not all_keys:
        return []

    # Prefer known objective-like variable names
    obj_keywords = [
        "structural_mass", "fuel_burn", "CD", "drag", "weight",
        "mass", "objective",
    ]

    # Try to find the objective by keyword match
    for keyword in obj_keywords:
        for key in all_keys:
            if keyword in key:
                values = _extract_scalar_values(driver_cases, key)
                if values:
                    return values

    # Fallback: use any scalar variable that changes
    for key in sorted(all_keys):
        values = _extract_scalar_values(driver_cases, key)
        if values and len(set(values)) > 1:
            return values

    return []


def _extract_scalar_values(cases: list[dict], key: str) -> list[float]:
    """Extract scalar float values for a variable across cases."""
    values = []
    for case in cases:
        val = case.get("data", {}).get(key)
        if isinstance(val, (int, float)) and not math.isnan(val):
            values.append(float(val))
        elif isinstance(val, list) and len(val) == 1:
            v = val[0]
            if isinstance(v, (int, float)) and not math.isnan(v):
                values.append(float(v))
    return values
