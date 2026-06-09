"""Shared constants for the Boeing 737-800 mission demonstration.

Single source of truth for parameters used across Lane A (raw OpenConcept),
Lane B (MCP / ocp-cli), Lane C (agent prompts), and the parity tests.

Why this example exists
-----------------------
The other OCP demonstrations (caravan_mission, kingair_mission) are all
*propeller* aircraft -- single and twin turboprops plus a series-hybrid twin,
flown on short GA missions with a balanced-field takeoff. This one is
deliberately as different as possible:

  * a transonic jet airliner (Boeing 737-800, MTOW ~79 t) instead of a GA prop,
  * the ``twin_turbofan`` architecture, which routes through OpenConcept's
    CFM56 surrogate and the ``IntegratorGroup`` code path (a different builder
    branch -- ``is_cfm56`` -- from every other example here),
  * a ``with_reserve`` mission (climb/cruise/descent + reserve climb/cruise/
    descent + loiter), which neither other example exercises.

It mirrors ``openconcept/examples/B738.py`` (``run_738_analysis``): 2050 NM at
FL330 with a reserve diversion at FL150 plus a loiter.

A note on parity
----------------
Unlike kingair_mission, this example does **not** reproduce the upstream
numbers bit-for-bit, and that is the point. Two structural differences between
the upstream script and the MCP tools are responsible:

  1. **Ramped vs constant speed schedules.** ``B738.py`` ramps the airspeed and
     vertical speed across each phase with ``np.linspace`` (e.g. climb vs
     2300 -> 600 ft/min, cruise Ueas 265 -> 258 kn). ``configure_mission``
     exposes only a single constant value per phase, so Lane B flies each phase
     at the representative constants below. The block-fuel difference from this
     is a few percent.

  2. **Reserve-phase speeds are not exposed.** ``configure_mission`` lets you
     set the reserve *altitude* (and range/loiter time) but not the reserve
     climb/cruise/descent/loiter *speeds*. The OCP builder defaults those to
     King-Air values (124/170/140 kn), not the jet speeds the upstream B738
     uses (230/250/250 kn). So the reserve + loiter fuel diverges more than the
     block fuel. See README.md ("Where the lanes differ") for the full write-up.

The constants below are the closest the constant-schedule ``configure_mission``
API can get to the upstream ramps (means of the linspace endpoints).
"""

# -- Aircraft -------------------------------------------------------------
# Boeing 737-800, twin turbofan (2x CFM56-7B).
# Mirrors openconcept/examples/B738.py + the OCP "b738" template.
AIRCRAFT = dict(
    template="b738",
    architecture="twin_turbofan",
)

# -- Mission parameters ---------------------------------------------------
# Maps openconcept/examples/B738.py onto the constant-per-phase
# configure_mission API. Upstream ramp endpoints are noted alongside.
RESERVE_MISSION = dict(
    mission_type="with_reserve",
    cruise_altitude_ft=33000.0,     # upstream cruise|h0 = 33000 ft
    mission_range_NM=2050.0,        # upstream mission_range = 2050 NM
    # Climb: upstream vs 2300 -> 600 ft/min, Ueas 230 -> 220 kn
    climb_vs_ftmin=1450.0,
    climb_Ueas_kn=225.0,
    # Cruise: upstream Ueas 265 -> 258 kn
    cruise_Ueas_kn=261.0,
    # Descent: upstream vs -1000 -> -150 ft/min, Ueas 250 kn
    descent_vs_ftmin=575.0,         # positive; tool negates internally
    descent_Ueas_kn=250.0,
    # Reserve diversion: upstream reserve|h0 = 15000 ft
    reserve_altitude_ft=15000.0,
    num_nodes=11,
)

# -- Tolerances for parity tests ------------------------------------------
# These are intentionally loose. Exact parity is NOT expected (see module
# docstring and README). The block fuel agrees to within a few percent;
# OEW/MTOW come straight from the shared aircraft data dict and match closely.
TOL_BLOCK_FUEL = dict(rtol=0.15)    # descent.fuel_used_final, ramp-vs-constant
TOL_OEW = dict(rtol=0.02)           # OEW from the same data dict
TOL_MTOW = dict(rtol=1e-6)          # MTOW is a direct passthrough
