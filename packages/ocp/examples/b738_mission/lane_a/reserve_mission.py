"""Lane A: Boeing 737-800 reserve mission using raw OpenConcept.

Twin-turbofan ``MissionWithReserve``: climb/cruise/descent + reserve
climb/cruise/descent + loiter. Uses the upstream OpenConcept B738 example
directly (``run_738_analysis``), so this lane is the ground-truth reference the
other lanes are compared against.

The upstream script ramps every phase speed with ``np.linspace`` and flies the
reserve diversion at jet speeds; the MCP tools (Lane B) can only express
constant per-phase speeds and default the reserve speeds to GA values, so the
two lanes agree only approximately. See ../README.md.
"""

import contextlib
import io

import sys, os

os.environ["OPENMDAO_REPORTS"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def run() -> dict:
    """Run the upstream B738 reserve mission and return key results."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from openconcept.examples.B738 import run_738_analysis

        prob = run_738_analysis(plots=False)

    # Block fuel: fuel burned through the end of the main descent (pre-reserve).
    fuel_burn = float(prob.get_val("descent.fuel_used_final", units="kg")[0])
    # Total fuel including reserve diversion + loiter.
    total_fuel = float(prob.get_val("loiter.fuel_used_final", units="kg")[0])
    mtow = float(prob.get_val("ac|weights|MTOW", units="kg")[0])

    # The CFM56 model uses a constant OEW from the data dict; the path it lives
    # under varies, so probe a couple of likely locations and fall back to None.
    oew = None
    for path in ("climb.OEW", "cruise.OEW"):
        try:
            oew = float(prob.get_val(path, units="kg")[0])
            break
        except (KeyError, RuntimeError):
            continue

    return {
        "fuel_burn_kg": fuel_burn,
        "total_fuel_with_reserve_kg": total_fuel,
        "OEW_kg": oew,
        "MTOW_kg": mtow,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2))
