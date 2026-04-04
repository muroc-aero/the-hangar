"""Post-run constraint satisfaction checks.

Verifies that all constraints specified in the plan are satisfied
at the final point of a completed run.
"""

from __future__ import annotations

import math
from pathlib import Path

from hangar.omd.db import init_analysis_db, query_run_results


def _check(name: str, passed: bool, message: str) -> dict:
    """Build a check result dict."""
    return {"name": name, "passed": passed, "message": message}


def assert_constraints(
    run_id: str,
    plan: dict,
    db_path: Path | None = None,
    tol: float = 1e-6,
) -> dict:
    """Check that all plan constraints are satisfied at the final point.

    Args:
        run_id: Run entity ID to assess.
        plan: Plan dictionary containing constraints.
        db_path: Path to analysis DB. Uses default if None.
        tol: Tolerance for constraint satisfaction.

    Returns:
        Dict with keys:
        - passed: bool (True if all constraints satisfied)
        - checks: list of check dicts (name, passed, message)
        - summary: human-readable summary string
    """
    init_analysis_db(db_path)

    checks: list[dict] = []
    constraints = plan.get("constraints", [])

    if not constraints:
        return {
            "passed": True,
            "checks": [_check(
                "no_constraints",
                True,
                "No constraints defined in plan",
            )],
            "summary": "No constraints to check",
        }

    # Get final case data
    cases = query_run_results(run_id)
    if not cases:
        return {
            "passed": False,
            "checks": [_check(
                "has_case_data",
                False,
                f"No case data for run '{run_id}'",
            )],
            "summary": "No case data available",
        }

    # Use final case, fall back to last driver case
    final_cases = [c for c in cases if c["case_type"] == "final"]
    if final_cases:
        final_data = final_cases[-1].get("data", {})
    else:
        final_data = cases[-1].get("data", {})

    # Check each constraint
    for con in constraints:
        con_name = con.get("name", "<unknown>")

        # Find the variable value in final data
        value = _find_constraint_value(con_name, final_data)
        if value is None:
            checks.append(_check(
                f"constraint_{con_name}",
                False,
                f"Constraint '{con_name}' not found in final case data",
            ))
            continue

        # Check bounds
        satisfied = True
        details = f"value={value:.6g}"

        if "upper" in con:
            upper = con["upper"]
            if value > upper + tol:
                satisfied = False
                details += f", violates upper={upper} by {value - upper:.6g}"
            else:
                details += f", upper={upper} OK"

        if "lower" in con:
            lower = con["lower"]
            if value < lower - tol:
                satisfied = False
                details += f", violates lower={lower} by {lower - value:.6g}"
            else:
                details += f", lower={lower} OK"

        if "equals" in con:
            equals = con["equals"]
            if abs(value - equals) > tol:
                satisfied = False
                details += f", violates equals={equals} by {abs(value - equals):.6g}"
            else:
                details += f", equals={equals} OK"

        checks.append(_check(
            f"constraint_{con_name}",
            satisfied,
            f"Constraint '{con_name}': {details}",
        ))

    all_passed = all(c["passed"] for c in checks)
    n_satisfied = sum(1 for c in checks if c["passed"])
    summary = (
        f"Constraints: {n_satisfied}/{len(checks)} satisfied"
        if checks
        else "No constraint checks performed"
    )

    return {
        "passed": all_passed,
        "checks": checks,
        "summary": summary,
    }


def _find_constraint_value(
    con_name: str,
    data: dict,
) -> float | None:
    """Find a constraint variable's scalar value in case data.

    Tries exact match first, then partial/suffix matching for
    OAS variable path conventions.
    """
    # Exact match
    if con_name in data:
        return _to_scalar(data[con_name])

    # Partial match: look for keys ending with the constraint name
    for key, val in data.items():
        if key.endswith(f".{con_name}") or key.endswith(f"_{con_name}"):
            return _to_scalar(val)

    # Broader partial match
    for key, val in data.items():
        if con_name in key:
            return _to_scalar(val)

    return None


def _to_scalar(value: object) -> float | None:
    """Convert a value to a scalar float, or None if not possible."""
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if isinstance(value, (list, tuple)):
        # For array constraints, use the max value (worst case)
        scalars = [_to_scalar(v) for v in value]
        valid = [s for s in scalars if s is not None]
        if valid:
            return max(valid)
    return None
