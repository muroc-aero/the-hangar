"""Shared constants for the single-aisle sizing parity example.

Single source of truth for parameters used across Lane A (raw Aviary
Level 1), Lane B (MCP tool-call script), and the parity tests. See
docs/parity-lanes-and-agent-eval.md for the lane design and
docs/aviary-server-plan.md for this example's spec.

Both lanes must solve the *same* optimization problem: same deck, same
default energy_state phase_info, same optimizer and iteration cap.
"""

# ── Aircraft ─────────────────────────────────────────────────────────────
# The canonical Aviary docs example: advanced technology single aisle
# (N3CC-like), FLOPS mass + aero, energy_state mission.
TEMPLATE = "advanced_single_aisle"
DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"

# ── Mission ──────────────────────────────────────────────────────────────
# The upstream energy_state default: 3-phase climb/cruise/descent,
# constrain_range to 1906 nmi. Lane A imports the default phase_info
# directly; Lane B lets the server build the identical default.
TARGET_RANGE_NM = 1906.0

# ── Optimizer (identical in every lane) ─────────────────────────────────
OPTIMIZER = "SLSQP"
MAX_ITER = 50

# ── Tolerances ───────────────────────────────────────────────────────────
# Parity: both lanes drive the same optimizer on the same problem from the
# same initial guesses, so converged outputs should agree to round-off; the
# loose-ish tier guards against BLAS/ordering nondeterminism only.
TOL_PARITY = dict(rel=1e-6)
# Range is an input echoed through the constraint.
TOL_RANGE = dict(rel=1e-6)

# Golden anchors: pin Lane A itself to values recorded from Aviary v1.0.1
# so an upstream physics regression on a pin bump is caught independently
# of lane-to-lane agreement (see parity-lanes doc §6).
GOLDEN = dict(
    gross_mass_lbm=116423.45,
    total_fuel_mass_lbm=13813.96,
    range_nmi=1906.0,
    final_time_min=300.69,
)
TOL_GOLDEN = dict(rel=2e-3)

# Headline metrics compared across lanes.
METRICS = ["gross_mass_lbm", "total_fuel_mass_lbm", "range_nmi", "final_time_min"]

# ── Case: override_sizing ────────────────────────────────────────────────
# Same aircraft with a wing aspect-ratio override (deck value 11.56 -> 13.0).
# Exercises the deck-override path: Lane A via create_vehicle + set_val,
# Lane B via the define_aircraft tool.
AR_OVERRIDE = {"aircraft:wing:aspect_ratio": 13.0}
GOLDEN_OVERRIDE = dict(
    gross_mass_lbm=116449.33,
    total_fuel_mass_lbm=13457.17,
    range_nmi=1906.0,
    final_time_min=300.98,
)

# ── Case: short_mission ──────────────────────────────────────────────────
# Same aircraft on a modified mission: 1200 nmi range constraint and a
# coarser cruise transcription. Exercises the phase_info merge path:
# Lane A mutates the default dict by hand, Lane B goes through
# configure_mission(target_range_nm=..., phase_options=...).
SHORT_RANGE_NM = 1200.0
SHORT_CRUISE_SEGMENTS = 3
GOLDEN_SHORT = dict(
    gross_mass_lbm=111495.35,
    total_fuel_mass_lbm=9200.15,
    range_nmi=1200.0,
    final_time_min=199.53,
)
