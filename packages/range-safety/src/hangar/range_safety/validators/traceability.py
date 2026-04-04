"""Requirements traceability validation.

Checks that requirements are fully traced to design variables, constraints,
and objectives, and that all trace references point to valid targets.
"""

from __future__ import annotations


def _finding(check: str, severity: str, message: str) -> dict:
    """Build a finding dict."""
    return {"check": check, "severity": severity, "message": message}


def validate_traceability(plan: dict) -> list[dict]:
    """Check that requirements are fully traced.

    Verifies that every requirement has traces, every trace target exists,
    and that constraints/objective/DVs link back to requirements.

    Args:
        plan: Parsed plan dictionary.

    Returns:
        List of finding dicts with keys: check, severity, message.
    """
    findings: list[dict] = []

    requirements = plan.get("requirements", [])
    design_variables = plan.get("design_variables", [])
    constraints = plan.get("constraints", [])
    objective = plan.get("objective", {})

    if not requirements:
        # No requirements to trace -- nothing to check
        return findings

    # Collect all requirement IDs
    req_ids = {r["id"] for r in requirements if "id" in r}

    # Collect all DV, constraint, and objective IDs/names
    dv_names = {dv["name"] for dv in design_variables if "name" in dv}
    con_names = {c["name"] for c in constraints if "name" in c}
    obj_name = objective.get("name") if objective else None

    # All valid trace targets: requirement IDs, DV names, constraint names,
    # objective name
    all_plan_names = dv_names | con_names
    if obj_name:
        all_plan_names.add(obj_name)

    # -- Check requirement traces_to targets exist --
    traced_req_ids: set[str] = set()
    for req in requirements:
        req_id = req.get("id", "<unknown>")
        traces_to = req.get("traces_to", [])

        if not traces_to:
            findings.append(_finding(
                "requirement_has_traces",
                "warning",
                f"Requirement '{req_id}' has no traces_to links",
            ))
            continue

        for target in traces_to:
            if target not in all_plan_names:
                findings.append(_finding(
                    "traces_to_target_exists",
                    "error",
                    f"Requirement '{req_id}' traces to '{target}' "
                    f"which is not a known DV, constraint, or objective name",
                ))
            else:
                traced_req_ids.add(req_id)

    # -- Check DV traces_to references point to valid requirement IDs --
    for dv in design_variables:
        dv_name = dv.get("name", "<unknown>")
        traces_to = dv.get("traces_to", [])
        for target in traces_to:
            if target not in req_ids:
                findings.append(_finding(
                    "dv_traces_to_requirement",
                    "error",
                    f"DV '{dv_name}' traces to '{target}' "
                    f"which is not a known requirement ID",
                ))

        if not traces_to:
            findings.append(_finding(
                "dv_has_traces",
                "warning",
                f"DV '{dv_name}' does not trace to any requirement",
            ))

    # -- Check constraint traces_to references --
    for con in constraints:
        con_name = con.get("name", "<unknown>")
        traces_to = con.get("traces_to", [])
        for target in traces_to:
            if target not in req_ids:
                findings.append(_finding(
                    "constraint_traces_to_requirement",
                    "error",
                    f"Constraint '{con_name}' traces to '{target}' "
                    f"which is not a known requirement ID",
                ))

        if not traces_to:
            findings.append(_finding(
                "constraint_has_traces",
                "warning",
                f"Constraint '{con_name}' does not trace to any requirement",
            ))

    # -- Check objective traces_to references --
    if objective:
        traces_to = objective.get("traces_to", [])
        for target in traces_to:
            if target not in req_ids:
                findings.append(_finding(
                    "objective_traces_to_requirement",
                    "error",
                    f"Objective '{obj_name}' traces to '{target}' "
                    f"which is not a known requirement ID",
                ))

        if not traces_to:
            findings.append(_finding(
                "objective_has_traces",
                "warning",
                f"Objective '{obj_name}' does not trace to any requirement",
            ))

    # -- Orphan requirements (no DV/constraint/objective traces to them) --
    # Collect requirement IDs that are referenced by DV/constraint/objective
    # traces_to fields
    referenced_reqs: set[str] = set()
    for dv in design_variables:
        referenced_reqs.update(dv.get("traces_to", []))
    for con in constraints:
        referenced_reqs.update(con.get("traces_to", []))
    if objective:
        referenced_reqs.update(objective.get("traces_to", []))

    for req in requirements:
        req_id = req.get("id", "<unknown>")
        if req_id not in referenced_reqs:
            findings.append(_finding(
                "orphan_requirement",
                "warning",
                f"Requirement '{req_id}' is not referenced by any "
                f"DV, constraint, or objective traces_to",
            ))

    return findings
