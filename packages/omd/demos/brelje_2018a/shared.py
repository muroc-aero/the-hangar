"""Shared constants for the Brelje 2018a reproduction demo.

Mirrors the MDO problem in upstream HybridTwin.py (lines 372-418),
which implements the exact formulation from:

    Brelje & Martins, "Development of a Conceptual Design Model
    for Aircraft Electric Propulsion with Efficient Gradients,"
    AIAA/IEEE EATS 2018.  Figs 5 (fuel) and 6 (cost).
"""

from __future__ import annotations

AIRCRAFT = dict(template="kingair", architecture="twin_series_hybrid")

# Mission parameters shared with examples/ocp_hybrid_twin/shared.py.
# Design range and battery specific energy are swept; defaults here are
# the single-cell verification point (matches HybridTwin.py defaults).
MISSION_BASE = dict(
    cruise_altitude_ft=29000.0,
    climb_vs_ftmin=1500.0,
    climb_Ueas_kn=124.0,
    cruise_Ueas_kn=170.0,
    descent_vs_ftmin=600.0,
    descent_Ueas_kn=140.0,
    num_nodes=11,
    payload_lb=1000.0,
)

DEFAULT_DESIGN_RANGE_NM = 500.0
DEFAULT_SPEC_ENERGY_WHKG = 450.0

# Full paths on the materialized problem. Short aliases where the
# materializer/factory already exposes them; pipe- and dot-paths pass
# through the OpenConcept convention.
DESIGN_VARIABLES = [
    dict(name="ac|weights|MTOW",               lower=4000.0, upper=5700.0, units="kg"),
    dict(name="ac|geom|wing|S_ref",            lower=15.0,   upper=40.0,   units="m**2"),
    dict(name="ac|propulsion|engine|rating",   lower=1.0,    upper=3000.0, units="hp"),
    dict(name="ac|propulsion|motor|rating",    lower=450.0,  upper=3000.0, units="hp"),
    dict(name="ac|propulsion|generator|rating", lower=1.0,   upper=3000.0, units="hp"),
    dict(name="ac|weights|W_battery",          lower=20.0,   upper=2250.0, units="kg"),
    dict(name="ac|weights|W_fuel_max",         lower=500.0,  upper=3000.0, units="kg"),
    dict(name="cruise.hybridization",          lower=0.001,  upper=0.999),
    dict(name="climb.hybridization",           lower=0.001,  upper=0.999),
    dict(name="descent.hybridization",         lower=0.01,   upper=1.0),
]

# Vector constraints are shaped (num_nodes,) -- the materializer/OMDAO
# broadcasts scalar lower/upper across the vector.
SCALAR_CONSTRAINTS = [
    dict(name="margins.MTOW_margin",                  lower=0.0),
    dict(name="rotate.range_final",                   upper=1357.0),  # BFL, ft
    dict(name="v0v1.Vstall_eas",                      upper=42.0),
    dict(name="descent.propmodel.batt1.SOC_final",    lower=0.0),
    dict(name="engineoutclimb.gamma",                 lower=0.02),
]

VECTOR_CONSTRAINTS = [
    dict(name="climb.throttle",                          upper=1.05),
    dict(name="climb.propmodel.eng1.component_sizing_margin",   upper=1.0),
    dict(name="climb.propmodel.gen1.component_sizing_margin",   upper=1.0),
    dict(name="climb.propmodel.batt1.component_sizing_margin",  upper=1.0),
    dict(name="cruise.propmodel.eng1.component_sizing_margin",  upper=1.0),
    dict(name="cruise.propmodel.gen1.component_sizing_margin",  upper=1.0),
    dict(name="cruise.propmodel.batt1.component_sizing_margin", upper=1.0),
    dict(name="descent.propmodel.eng1.component_sizing_margin", upper=1.0),
    dict(name="descent.propmodel.gen1.component_sizing_margin", upper=1.0),
    dict(name="descent.propmodel.batt1.component_sizing_margin", upper=1.0),
    dict(name="v0v1.propmodel.batt1.component_sizing_margin",   upper=1.0),
]
