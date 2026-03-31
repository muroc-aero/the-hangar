# OpenAeroStruct MCP — step-by-step workflows

---
## Workflow A — aerodynamic analysis of a new wing

Goal: characterise CL, CD, L/D of a wing at cruise.

Step 1 — define the geometry:
  create_surface(
      name="wing", wing_type="CRM",
      num_x=2, num_y=7, symmetry=True,
      with_viscous=True, CD0=0.015
  )

Step 2 — single-point cruise analysis:
  run_aero_analysis(
      surfaces=["wing"],
      velocity=248.136, alpha=5.0,
      Mach_number=0.84, density=0.38
  )

Step 3 — drag polar to find best L/D:
  compute_drag_polar(
      surfaces=["wing"],
      alpha_start=0.0, alpha_end=12.0, num_alpha=13,
      Mach_number=0.84, density=0.38
  )
  → inspect best_L_over_D to find operating point

Step 4 (optional) — stability check:
  compute_stability_derivatives(
      surfaces=["wing"],
      alpha=5.0, Mach_number=0.84, density=0.38,
      cg=[<x_cg>, 0, 0]   # x_cg in metres from leading edge
  )

---
## Workflow B — aerostructural sizing

Goal: check whether a wing structure can carry the aerodynamic loads at cruise,
and compute mission fuel burn.

Step 1 — define wing with structural properties:
  create_surface(
      name="wing", wing_type="CRM",
      num_x=2, num_y=7, symmetry=True,
      with_viscous=True, CD0=0.015,
      fem_model_type="tube",
      E=70e9, G=30e9, yield_stress=500e6, safety_factor=2.5, mrho=3000.0
  )

Step 2 — coupled aerostructural analysis:
  run_aerostruct_analysis(
      surfaces=["wing"],
      velocity=248.136, alpha=5.0,
      Mach_number=0.84, density=0.38,
      W0=120000,         # aircraft empty weight excl. wing, kg
      R=11.165e6,        # mission range, m
      speed_of_sound=295.4, load_factor=1.0
  )

Step 3 — interpret results:
  • failure < 0  →  structure is safe at this load
  • failure > 0  →  increase thickness_cp values or reduce load_factor
  • L_equals_W ≈ 0  →  wing is sized for aircraft weight; large residual means
    alpha or W0 needs adjustment
  • fuelburn / structural_mass are the primary sizing metrics

---
## Workflow C — aerodynamic optimisation

Goal: minimise drag at a fixed lift coefficient by varying twist and alpha.

Step 1 — define geometry (aero-only surface is fine):
  create_surface(
      name="wing", wing_type="CRM",
      num_x=2, num_y=7, symmetry=True,
      with_viscous=True, CD0=0.015
  )

Step 2 — run optimisation:
  run_optimization(
      surfaces=["wing"],
      analysis_type="aero",
      objective="CD",
      design_variables=[
          {"name": "twist", "lower": -10.0, "upper": 15.0},
          {"name": "alpha", "lower": -5.0,  "upper": 15.0}
      ],
      constraints=[{"name": "CL", "equals": 0.5}],
      Mach_number=0.84, density=0.38
  )

Step 3 — check result:
  • success=True and final_results.CL ≈ 0.5  →  converged
  • success=False  →  try wider DV bounds or a different starting alpha

---
## Workflow D — aerostructural optimisation (minimum fuel burn)

Step 1 — define wing with structural properties (see Workflow B, Step 1)

Step 2:
  run_optimization(
      surfaces=["wing"],
      analysis_type="aerostruct",
      objective="fuelburn",
      design_variables=[
          {"name": "twist",     "lower": -10.0, "upper": 15.0},
          {"name": "thickness", "lower":  0.003, "upper": 0.25,  "scaler": 1e2},
          {"name": "alpha",     "lower":  -5.0,  "upper": 10.0}
      ],
      constraints=[
          {"name": "L_equals_W",  "equals": 0.0},
          {"name": "failure",     "upper":  0.0},
          {"name": "thickness_intersects", "upper": 0.0}
      ],
      W0=120000, R=11.165e6, Mach_number=0.84, density=0.38
  )

---
## Workflow E — multi-surface (wing + tail)

Step 1 — create both surfaces:
  create_surface(name="wing", wing_type="CRM", num_x=2, num_y=7, ...)
  create_surface(name="tail", wing_type="rect", span=6.0, root_chord=1.5,
                 num_x=2, num_y=5, offset=[20.0, 0.0, 0.0],
                 CD0=0.0, CL0=0.0)

Step 2 — analyse both together:
  run_aero_analysis(surfaces=["wing", "tail"], ...)
  compute_drag_polar(surfaces=["wing", "tail"], ...)

  Trimmed stability (CM=0) requires adjusting the tail incidence angle
  (twist_cp on the tail) until CM ≈ 0 at the desired operating CL.

NOTE: All *_cp arrays (twist_cp, chord_cp, thickness_cp, etc.) are ordered
  ROOT-to-TIP: cp[0]=root, cp[-1]=tip.  This applies to both inputs and the
  optimized_design_variables output from run_optimization.

---
## Provenance Tracking

The server records every tool call automatically (Tier 1).  Use the three
provenance tools to add Tier 2 explicit reasoning capture.

### Pattern for all workflows A-E

Step 0 — at the start of any workflow:
  start_session(notes="<brief description>")
  → returns {session_id, started_at}; the session is now active

At decision points (before/after major steps):
  log_decision(
      decision_type="mesh_resolution"|"dv_selection"|"constraint_choice"|"result_interpretation",
      reasoning="<why this choice>",
      selected_action="<what was chosen>",
      prior_call_id="<call_id from _provenance in previous tool result>",  # optional
      confidence="high"|"medium"|"low"
  )
  → returns {decision_id}

Final step — export the audit trail:
  export_session_graph(
      session_id="<session_id from step 0>",
      output_path="<workflow_name>_provenance.json"   # optional
  )
  → returns {session, nodes, edges, path}

### Viewer

Open packages/sdk/src/hangar/sdk/viz/viewer/index.html in a browser.
  • Drop the exported JSON file onto the page, OR
  • Connect live: http://127.0.0.1:7654/viewer (started automatically with the server)
  • Click any node to inspect inputs/outputs or reasoning
  • Toggle FSM mode to collapse repeated tool calls into state transitions

---
## CLI Visualization Tips

In CLI environments (Claude Code, Codex), MCP images render as `[image]` — not useful.
Use output modes to get plots as files or clickable URLs instead:

```python
# Option 1: Set session default (applies to all visualize calls)
configure_session(visualization_output="file")   # saves PNGs to disk
configure_session(visualization_output="url")    # returns clickable dashboard URLs

# Option 2: Per-call override
visualize(run_id=run_id, plot_type="lift_distribution", output="file")
visualize(run_id=run_id, plot_type="stress_distribution", output="url")
```

### Dashboard

Every run has a context-rich HTML dashboard at `/dashboard?run_id=X` that shows
flight conditions, key results, validation status, and all applicable plots.

  • Local:  http://localhost:7654/dashboard?run_id=X  (no auth)
  • VPS:    use visualize(run_id, output="url") to get the correct dashboard URL
