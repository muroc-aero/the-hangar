"""Design variable bounds and constraint lists for the Adler 2022a demo.

Single source of truth shared by all four lane_b plans plus the Lane A
programmatic script. Mirrors paper Tables 2 (mission-based), 3 (single
point), and 4 (multipoint), and the Section IV.A modification for
single point + climb.

The wingbox DV count is 14 in all variants (taper / sweep / aspect
ratio + 3 free twist cps + 4 t/c + 4 skin + 4 spar). Per-method extras
are angles of attack — but the AerostructBreguet factory does not
take alpha as a free DV (it solves CL = W/(qS) directly), so the
Bréguet-variant lane_b plans share the same 14 DVs as mission_based.
The paper's extra alpha DVs are an artefact of its different lift-
balance approach.
"""
from __future__ import annotations

import numpy as np


# Common wingbox DVs (matches paper Section IV).
# `num_X_cp` values must match the surface_grid in each plan.
NUM_TWIST_CP = 4
NUM_TOVERC_CP = 4
NUM_SKIN_CP = 4
NUM_SPAR_CP = 4

# Twist control points: tip locked at 0 to prevent rigid rotation
# (upstream B738_aerostructural.py:347). Bounds matched to
# upstream's ([0, -10, -10] lower / [0, 10, 10] upper) extended for
# our 4-cp spline.
TWIST_LOWER_DEG = np.array([0.0, -10.0, -10.0, -10.0])
TWIST_UPPER_DEG = np.array([0.0, 10.0, 10.0, 10.0])

# t/c lower bound increases toward the root (paper Section IV).
TOVERC_LOWER = np.linspace(0.03, 0.10, NUM_TOVERC_CP)
TOVERC_UPPER = 0.25

# Skin/spar minimum thickness 3 mm (paper Section IV; Chauhan & Martins).
SKIN_LOWER_M = 0.003
SKIN_UPPER_M = 0.10
SPAR_LOWER_M = 0.003
SPAR_UPPER_M = 0.10

# Aspect ratio limited to fit a Group III gate (paper Table 2).
AR_UPPER = 10.4
AR_LOWER = 5.0

# Taper and sweep bounds from upstream B738_aerostructural.py.
TAPER_LOWER = 0.01
TAPER_UPPER = 0.35
SWEEP_LOWER_DEG = 0.0
SWEEP_UPPER_DEG = 35.0


def common_design_variables() -> list[dict]:
    """Return the 14 wingbox DVs as a list of plan-format dicts."""
    return [
        {
            "name": "ac|geom|wing|AR",
            "lower": AR_LOWER,
            "upper": AR_UPPER,
        },
        {
            "name": "ac|geom|wing|c4sweep",
            "lower": SWEEP_LOWER_DEG,
            "upper": SWEEP_UPPER_DEG,
            "units": "deg",
        },
        {
            "name": "ac|geom|wing|taper",
            "lower": TAPER_LOWER,
            "upper": TAPER_UPPER,
            "scaler": 10.0,
        },
        {
            "name": "ac|geom|wing|twist",
            "lower": TWIST_LOWER_DEG.tolist(),
            "upper": TWIST_UPPER_DEG.tolist(),
            "units": "deg",
        },
        {
            "name": "ac|geom|wing|toverc",
            "lower": TOVERC_LOWER.tolist(),
            "upper": TOVERC_UPPER,
        },
        {
            "name": "ac|geom|wing|skin_thickness",
            "lower": SKIN_LOWER_M,
            "upper": SKIN_UPPER_M,
            "units": "m",
            "scaler": 100.0,
        },
        {
            "name": "ac|geom|wing|spar_thickness",
            "lower": SPAR_LOWER_M,
            "upper": SPAR_UPPER_M,
            "units": "m",
            "scaler": 100.0,
        },
    ]


def common_constraints() -> list[dict]:
    """Return the structural failure constraint, common to all
    variants. Upper bound 0 corresponds to the KS-aggregated
    failure index landing at the 280 MPa / SF=1.5 yield surface.
    """
    return [
        {"name": "2_5g_KS_failure", "upper": 0.0},
    ]
