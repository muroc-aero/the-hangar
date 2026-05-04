"""Physics-level cross-check: omd OCP factory vs upstream
HybridTwinTestCase published values.

Replicates upstream openconcept/examples/HybridTwin.py
``run_hybrid_twin_analysis`` exactly:
    design_range = 500 nmi
    spec_energy  = 450 Wh/kg
    cruise.hybridization  = 0.05840626452293813
    climb.hybridization   = 0.0    (upstream default)
    descent.hybridization = 0.0    (upstream default)
    num_nodes = 11
    Newton + DirectSolver, run_model() (no driver)

Then reads the same 5 outputs the upstream test fixture asserts on
(``test_example_aircraft.py:HybridTwinTestCase``) and compares to the
published values at the published 1e-5 tolerance.

If physics matches, the optimizer differences we see in Table 4
comparisons are NOT due to differing physics models -- they're
purely due to which local optimum the SLSQP run converges to.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import numpy as np

# ----- Upstream HybridTwinTestCase published values -----
# Source: upstream/openconcept/openconcept/examples/tests/test_example_aircraft.py
# (lines reading "class HybridTwinTestCase")
UPSTREAM_PUBLISHED = {
    "climb.OEW":                              ("lb",   6648.424765080086),
    "rotate.range_final":                     ("ft",   4383.871458066499),
    "engineoutclimb.gamma":                   ("deg",  1.7659046316724112),
    "descent.fuel_used_final":                ("lb",   854.8937776195904),
    "descent.propmodel.batt1.SOC_final":      (None,  -0.00030626412),
}
UPSTREAM_TOL_REL = 1e-5  # the test fixture's tolerance


def run_omd_analysis() -> dict:
    """Build omd's OCP factory at the upstream operating point, run_model,
    return the 5 published outputs."""
    from hangar.omd.factories.ocp.builder import build_ocp_full_mission

    component_config = {
        "aircraft_template": "kingair",
        "architecture": "twin_series_hybrid",
        "num_nodes": 11,
        "mission_params": {
            "cruise_altitude_ft":         29000,
            "mission_range_NM":           500,
            "climb_vs_ftmin":             1500,
            "climb_Ueas_kn":              124,
            "cruise_Ueas_kn":             170,
            "descent_vs_ftmin":           600,
            "descent_Ueas_kn":            140,
            "payload_lb":                 1000,
            "cruise_hybridization":       0.05840626452293813,
            "climb_hybridization":        0.0,
            "descent_hybridization":      0.0,
            "battery_specific_energy":    450,
        },
        "propulsion_overrides": {
            "battery_specific_energy":    450,
        },
    }

    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        prob, meta = build_ocp_full_mission(component_config, {})
        # The factory already called prob.setup() and applied mission_params
        # via _set_mission_values -- meta["_setup_done"] signals this.
        # Do NOT call setup() again here; that would wipe the values.
        if not meta.get("_setup_done"):
            prob.setup(check=False)
            for path, spec in (meta.get("initial_values_with_units") or {}).items():
                if isinstance(spec, dict):
                    prob.set_val(path, spec["val"], units=spec.get("units"))
                else:
                    prob.set_val(path, spec)
            for path, val in (meta.get("initial_values") or {}).items():
                prob.set_val(path, val)

        # Apply the upstream-specific overrides that the kingair template
        # doesn't bake in -- these are paper-specific modifications of the
        # stock King Air for the hybrid architecture (see HybridTwin.py:243-245).
        prob["analysis.cruise.acmodel.OEW.const.structural_fudge"] = 2.0
        prob["ac|propulsion|propeller|diameter"] = 2.2
        prob["ac|propulsion|engine|rating"] = 1117.2

        prob.run_model()

        out = {}
        for name, (units, _published) in UPSTREAM_PUBLISHED.items():
            try:
                v = prob.get_val(name, units=units)
            except Exception:
                v = prob.get_val(name)
            out[name] = float(np.asarray(v).flatten()[0])
        return out


def run_upstream_analysis() -> dict:
    """Sanity check: run upstream's own ``run_hybrid_twin_analysis`` and
    extract the same 5 outputs.  Should match the published values to
    floating-point precision since that function is what generated them.
    """
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        from openconcept.examples.HybridTwin import run_hybrid_twin_analysis
        prob = run_hybrid_twin_analysis(plots=False)
        out = {}
        for name, (units, _) in UPSTREAM_PUBLISHED.items():
            try:
                v = prob.get_val(name, units=units)
            except Exception:
                v = prob.get_val(name)
            out[name] = float(np.asarray(v).flatten()[0])
        return out


def main() -> int:
    print()
    print("=" * 92)
    print(" PHYSICS CROSS-CHECK: omd OCP factory vs upstream HybridTwinTestCase")
    print("=" * 92)
    print(f"  operating point: design_range=500 nmi, spec_energy=450 Wh/kg,")
    print(f"                   cruise.hybridization=0.05840626, run_model only")
    print()

    print(" Computing upstream baseline (run_hybrid_twin_analysis) ...", flush=True)
    up = run_upstream_analysis()
    print(" Computing omd factory output (build_ocp_full_mission + run_model) ...", flush=True)
    omd = run_omd_analysis()
    print()

    fmt = (f"  {'output':<40s}  {'published':>16s}  "
           f"{'upstream':>16s}  {'omd':>16s}  {'omd-pub rel':>11s}  pass?")
    print(fmt)
    print("  " + "-" * (len(fmt) - 2))

    n_pass = 0
    for name, (units, published) in UPSTREAM_PUBLISHED.items():
        u_val = up[name]
        o_val = omd[name]
        denom = max(abs(published), 1e-30)
        rel_omd = abs(o_val - published) / denom
        rel_up = abs(u_val - published) / denom
        passed = rel_omd <= UPSTREAM_TOL_REL
        if passed:
            n_pass += 1
        unit_tag = f" {units}" if units else ""
        print(f"  {name + unit_tag:<40s}  {published:>16.8g}  "
              f"{u_val:>16.8g}  {o_val:>16.8g}  {rel_omd:>11.2e}  "
              f"{'OK' if passed else 'FAIL'}")

    print()
    print(f"  upstream-vs-published agreement: should be ~zero (it's the source)")
    print(f"  omd-vs-published     pass rate : {n_pass}/{len(UPSTREAM_PUBLISHED)} "
          f"at tol={UPSTREAM_TOL_REL:g}")
    if n_pass == len(UPSTREAM_PUBLISHED):
        print()
        print("  CONCLUSION: omd's physics matches upstream physics to the published")
        print("  test tolerance.  Any MDO-result divergence is an OPTIMIZER convergence")
        print("  difference, not a model difference.")
    else:
        print()
        print("  CONCLUSION: omd produces different physics than upstream at the same")
        print("  operating point.  This means the model itself differs (factory mismatch,")
        print("  initial-value drift, etc.) and would need to be reconciled before any")
        print("  meaningful MDO comparison.")
    return 0 if n_pass == len(UPSTREAM_PUBLISHED) else 1


if __name__ == "__main__":
    sys.exit(main())
