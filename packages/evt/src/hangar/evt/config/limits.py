"""Physical sanity bounds used by input validators and result checks.

These are deliberately wide -- they catch transcription blunders (negative
masses, zero battery specific energy, > 1 efficiencies), not marginal design
choices. Borderline-but-plausible values surface as validation findings on
the result, not as hard input errors.
"""

from __future__ import annotations

# Battery specific energy (Wh/kg). Today's cells ~150-300; research ~500+.
BATT_SPEC_ENERGY_MIN = 50.0
BATT_SPEC_ENERGY_MAX = 1000.0

# Fractions/efficiencies that must lie in (0, 1].
FRACTION_KEYS = frozenset({
    "batt_inaccessible_energy_frac",
    "batt_eol_capacity",
    "batt_int_factor",
    "epu_effic",
    "hover_power_effic",
    "rotor_effic",
    "span_effic_factor",
    "cruise_wing_lift_fraction",
})

# Battery mass fraction of MTOW that is plausible for an eVTOL (advisory).
BATT_MASS_FRAC_MIN = 0.10
BATT_MASS_FRAC_MAX = 0.60

# Disk loading sanity window (kg/m^2) for rotorcraft (advisory).
DISK_LOADING_MIN = 5.0
DISK_LOADING_MAX = 200.0
