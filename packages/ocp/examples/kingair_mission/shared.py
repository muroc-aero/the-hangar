"""Shared constants for the King Air C90GT mission demonstration.

Single source of truth for parameters used across Lane A (raw OpenConcept),
Lane B (MCP / ocp-cli), Lane C (agent prompts), and the parity tests.

This demonstration is also the verification harness for the twin-turboprop
parity work (issues #36, #38, #39):
  * #36 -- structural_fudge and takeoff_throttle exposed in configure_mission
  * #38 -- twin OEW (engines_weight) and balanced-field propulsor_active wiring
  * #39 -- per-aircraft propeller rpm read from the template (King Air = 1900)

With all three in place, Lane B (built via the OCP builder) reproduces the
upstream OpenConcept ``run_kingair_analysis`` essentially bit-for-bit.
"""

# ── Aircraft ─────────────────────────────────────────────────────────────
# Beechcraft King Air C90GT, twin turboprop (2x PT6A).
# Mirrors openconcept/examples/KingAirC90GT.py + the OCP "kingair" template.
AIRCRAFT = dict(
    template="kingair",
    architecture="twin_turboprop",
)

# ── Mission parameters ───────────────────────────────────────────────────
# Matches openconcept/examples/KingAirC90GT.py set_values() exactly.
#   structural_fudge = 1.67  -> scales OEW to the real airframe weight
#   takeoff_throttle = 0.75  -> derates the PT6A during the takeoff roll
MISSION_FULL = dict(
    mission_type="full",
    cruise_altitude_ft=29000.0,
    mission_range_NM=1000.0,
    climb_vs_ftmin=1500.0,
    climb_Ueas_kn=124.0,
    cruise_Ueas_kn=170.0,
    descent_vs_ftmin=600.0,  # positive; tool negates internally
    descent_Ueas_kn=140.0,
    payload_lb=1000.0,
    structural_fudge=1.67,
    takeoff_throttle=0.75,
    num_nodes=11,
)

# ── Tolerances for parity tests ──────────────────────────────────────────
# Observed parity with all three fixes applied:
#   OEW   exact     (engines_weight sums both PT6A)
#   fuel  exact     (mission dynamics keyed off fixed MTOW, not per-phase OEW)
#   TOFL  ~1e-10    (when both sides converge Newton to 1e-10)
#
# Lane A calls the upstream run_kingair_analysis, which stops Newton at
# atol=rtol=1e-6; the OCP builder drives to 1e-10. That tolerance gap, not any
# model difference, is the only reason TOFL is not bit-identical: tightening the
# reference to 1e-10 yields 3054.641429 ft, matching OCP exactly. TOL_TOFL is
# sized to absorb the reference's 1e-6 under-convergence (~0.03 ft on ~3055 ft).
TOL_FUEL = dict(rtol=1e-3)
TOL_OEW = dict(rtol=1e-3)
TOL_TOFL = dict(rtol=2e-3)
TOL_SCALARS = dict(rtol=1e-3)
