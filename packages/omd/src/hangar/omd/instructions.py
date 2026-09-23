"""The omd MCP server's instruction block, importable without the server.

``server.py`` hands this to FastMCP as ``instructions`` (delivered at MCP
initialize). Harnesses that do not forward server instructions to the model
(OpenCode 1.17.5 discards them) read it from here instead and deliver it
their own way -- hangar-evals writes it into the agent's ``AGENTS.md``.
"""

INSTRUCTIONS = """MDAO analysis plan server (OpenMDAO plan runner).

omd materializes YAML analysis plans into OpenMDAO problems, runs them, and
records results with PROV-Agent provenance. It composes the other hangar
tools (OAS aero/aerostruct, OpenConcept missions, pyCycle engines) into one
declarative plan -- use it for plan-based multi-tool studies.

REQUIRED WORKFLOW -- always follow this order:
  0. start_session       -- begin a provenance session (once per workflow)
  1. Author the plan, either way:
       a. builder tools: plan_init -> plan_add_component ->
          plan_set_operating_point -> [plan_add_requirement] ->
          [plan_add_dv + plan_set_objective] -> assemble_plan
       b. direct YAML: write_plan, then use the written path
     log_decision         -- record component/DV/objective choices
  2. validate_plan        -- schema + semantic preflight (typo suggestions)
     review_plan          -- advisory completeness check (requirements, decisions)
  3. run_plan             -- mode="analysis" or "optimize"
     run_polar            -- alpha-sweep mode for OAS plans (drag polar)
     log_decision         -- interpret results (decision_type="result_interpretation")
  4. get_results / get_run_summary / generate_plots -- inspect the run
  5. record_conclusion    -- judge the run against the plan's requirements
  6. export_session_graph -- save the provenance DAG at workflow end

PLAN WORKSPACE:
  Relative paths resolve into a server-side workspace, so you can author,
  run, and read plans entirely through tool calls (no filesystem needed).
  read_plan on a directory lists its files.

STUDIES (multi-case):
  A study runs many cases (each one plan run) from a single study YAML:
  matrix (DOE-style) expansion plus manual case insertion. Workflow:
  author the study YAML (write_plan) -> review_study (case count +
  compute estimate; ALWAYS review before running -- matrix axes multiply)
  -> run_study with a small max_cases pilot batch -> inspect via
  get_study_status / get_study_results (and the per-case run_refs) ->
  continue in batches. Completed cases are checkpointed and skipped
  automatically on the next run_study call.

CRITICAL CONSTRAINTS:
  * run_plan refuses semantically invalid plans -- unknown component types
    and DV/constraint/objective names fail fast with suggestions.
  * An optimizer that converges in 1-2 iterations usually means DV bounds
    are wrong or DVs are not being applied; the validation block flags this.
  * record_conclusion needs requirements with acceptance_criteria in the
    plan to derive per-requirement verdicts.
  * OCP components accept slots (drag/propulsion/weight providers) for
    multi-tool composition -- see omd://reference.

RESPONSE ENVELOPE (run_plan / run_polar):
  Versioned envelope (schema_version="1.0") with results, validation
  (check "passed" before trusting numbers), telemetry, run_id, and error
  (USER_INPUT_ERROR, SOLVER_CONVERGENCE_ERROR, INTERNAL_ERROR).

VIEWS & URLS:
  Run/plan tools return a "urls" block: interactive problem DAG, plot
  gallery, N2 diagram, plan provenance/knowledge graph, the SDK provenance
  viewer, and the range-safety study dashboard when one is running. Use
  get_view_urls(run_id, plan_id) to fetch them at any time.

Use the prompts (author_plan_study, run_existing_plan) for guided
workflows, and the resources (omd://reference, omd://plan-schema,
omd://plans/{plan_id}) for parameter lookup."""
