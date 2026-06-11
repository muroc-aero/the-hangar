"""MCP prompts for the omd server -- guided plan workflows."""

from __future__ import annotations

from mcp.server.fastmcp.prompts import base


def prompt_author_plan_study(
    study_goal: str = "minimize cruise drag of a transport wing",
    component_type: str = "oas/AeroPoint",
    plan_name: str = "my-study",
) -> list[base.Message]:
    """Author a plan from scratch over MCP, then validate, run, and conclude."""
    return [
        base.UserMessage(f"""Run a complete omd plan study: {study_goal}.

Follow this workflow, logging decisions as you go:

1. start_session -- begin a provenance session.
2. plan_init(plan_dir="{plan_name}", plan_id="{plan_name}", name="{plan_name}")
3. plan_add_component -- add a "{component_type}" component. Read
   omd://reference first for the config keys this factory accepts, and pass
   a rationale for the mesh/geometry choices.
4. plan_set_operating_point -- set the flight condition fields
   (Mach_number, alpha, altitude or v/rho/Re), with a rationale.
5. plan_add_requirement -- record at least one requirement with
   acceptance_criteria so record_conclusion can derive a verdict later.
6. For optimization: plan_add_dv for each design variable (validate names
   via the tool's error feedback), then plan_set_objective. Log a
   log_decision(decision_type="dv_selection") explaining the choices.
7. assemble_plan(plan_dir="{plan_name}") -- produces the canonical plan.yaml.
8. validate_plan on the assembled path; fix any findings before running.
9. review_plan -- check completeness; address MISSING findings.
10. run_plan(mode="optimize" if you added DVs, else "analysis"). Check the
    envelope's validation block before trusting results; log a
    log_decision(decision_type="result_interpretation", prior_call_id=...).
11. generate_plots + get_run_summary -- inspect the run; share the urls.
12. record_conclusion -- judge the run against the requirements with a
    short narrative.
13. export_session_graph -- save the provenance DAG.

Report the run_id, key results, the per-requirement verdicts, and every
URL the tools returned (problem DAG, plots, range-safety dashboard)."""),
    ]


def prompt_run_existing_plan(
    plan_path: str = "plan.yaml",
    mode: str = "analysis",
) -> list[base.Message]:
    """Validate, run, and review an existing plan file."""
    return [
        base.UserMessage(f"""Run the existing omd plan at {plan_path} in {mode} mode.

1. start_session -- begin a provenance session.
2. read_plan("{plan_path}") -- inspect the plan; summarize the components,
   operating point, and (if present) the optimization formulation.
3. validate_plan -- fix or report any schema/semantic findings first.
4. run_plan(plan_path="{plan_path}", mode="{mode}"). Check the envelope's
   validation block: a failed run_status or an optimizer that converged in
   1-2 iterations means the result is not trustworthy yet.
5. get_results(run_id, summary=True) and generate_plots(run_id).
6. log_decision(decision_type="result_interpretation", prior_call_id=...)
   with your reading of the results.
7. If the plan has requirements: record_conclusion(run_id, narrative=...).
8. export_session_graph.

Report status, key metrics, the validation findings, and the view URLs."""),
    ]
