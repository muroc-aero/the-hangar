"""Shared constants for the loose-coupled OAS -> Aviary wing-mass case (B2).

The multitool composition the tight-coupled cases cannot show: an OAS
aerostructural wing (main venv, numpy<2) computes a structural wing mass
that omd feeds -- across the venv boundary -- into an Aviary sizing
(subprocess into .venv-avy, numpy 2) as a deck override on
``aircraft:wing:mass``, through the ``avy/Sizing`` factory's
``override_inputs`` mechanism. One-way coupling; OpenMDAO converts the
kg -> lbm units on the plan connection.

Physical honesty: the wing here is a single-aisle-*scaled* rectangular
tube-spar surface (the certified ``oas_aerostruct_rect`` formulation with
transport-scale numbers), NOT the aircraft's real planform -- this case
certifies the cross-venv composition plumbing; the physically-grounded
wing-mass study is ``avy_oas_wing`` / the per-tool
``single_aisle_oas_wing`` (upstream's own wingbox integration).

Lane A is compositional (no single upstream script does this): raw OAS in
the main venv -> hand the mass to a raw-Aviary override run in .venv-avy.
"""

# ── OAS side (single-aisle-scaled rect tube wing) ────────────────────────
WING = {
    "name": "wing",
    "wing_type": "rect",
    "num_x": 2,
    "num_y": 7,
    "span": 35.0,
    "root_chord": 4.2,
    "symmetry": True,
    "fem_model_type": "tube",
    "E": 7.0e10,
    "G": 3.0e10,
    "yield_stress": 5.0e8,
    "mrho": 2780.0,
    "thickness_cp": [0.015, 0.02, 0.015],
    "with_viscous": True,
}

# M0.785 cruise at ~35 kft
FLIGHT = {
    "velocity": 231.5,
    "alpha": 3.0,
    "Mach_number": 0.785,
    "re": 1.0e6,
    "rho": 0.38,
}

# ── Aviary side ──────────────────────────────────────────────────────────
DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"
PHASE_INFO_MODULE = "aviary.models.missions.energy_state_default"  # 1906 nmi
OVERRIDE_VAR = "aircraft:wing:mass"
OVERRIDE_INPUT = "wing_mass_override_lbm"
OPTIMIZER = "SLSQP"
MAX_ITER = 50

# Both lanes hand the identical structural mass through the identical
# override path -> round-off agreement.
TOL_PARITY = dict(rel=1e-6)

# Golden anchors (OAS v2.12.0 structural mass; Aviary v1.0.1 sizing with
# that mass overriding aircraft:wing:mass). Recorded from Lane A.
GOLDEN = dict(
    structural_mass_kg=6283.00,
    wing_mass_lbm=13851.64,
    gross_mass_lbm=122560.10,
    total_fuel_mass_lbm=14198.05,
    range_nmi=1906.0,
)
TOL_GOLDEN = dict(rel=2e-3)

METRICS = [
    "wing_mass_lbm",
    "gross_mass_lbm",
    "total_fuel_mass_lbm",
    "range_nmi",
    "final_time_min",
]
