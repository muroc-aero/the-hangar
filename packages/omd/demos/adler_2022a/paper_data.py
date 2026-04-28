"""Adler & Martins 2022a converged optima from paper Tables 5/6/7.

Tables 5 (300 nmi), 6 (1500 nmi), and 7 (2900 nmi) in the SciTech 2022
paper's appendix (PDF pages 14-15) list the exact converged optima for
all four methods. These are the gold reference for any single-cell
parity test.

Caveat on direct comparison
---------------------------
The paper's tabulated `mission_fuel_burn_kg` is the *mission-integrated*
fuel of the optimized wing run through the mission_based plan, not the
Bréguet objective the optimizer minimizes. For Bréguet-objective methods
this number is therefore NOT the value the optimizer is reducing. To
compare to the paper's mission_fuel_burn_kg directly, take the optimized
wing geometry and re-run through the mission_based plan.

The geometric DVs (taper, sweep, twist_cp, toverc_cp, skin_cp, spar_cp)
ARE directly comparable across methods.

Twist control points are listed root-to-tip with the tip locked at 0
(paper convention). If the factory orders tip-to-root, reverse before
comparing.

Fields with `None` are not transcribed yet (Tables 6 and 7 in the
paper appendix list only a subset of DVs).
"""
from __future__ import annotations


PAPER_TABLES: dict = {
    300: {
        "single_point": {
            "mission_fuel_burn_kg": 2770.44,
            "AR": 10.401,
            "taper": 0.168,
            "c4sweep_deg": 23.046,
            "twist_cp_deg": [0.0, 2.072, -2.862, -1.072],
            "toverc_cp": [0.034, 0.086, 0.090, 0.118],
            "spar_cp_mm": [3.99, 3.0, 8.72, 5.43],
            "skin_cp_mm": [5.0, 14.94, 18.47, 19.15],
            "two_five_g_failure": 2.8e-6,
        },
        "multipoint": {
            "mission_fuel_burn_kg": 2765.53,
            "AR": 10.401,
            "taper": 0.174,
            "c4sweep_deg": 23.524,
            "twist_cp_deg": [0.0, 5.274, -3.630, 0.588],
            "toverc_cp": [0.030, 0.096, 0.085, 0.119],
            "spar_cp_mm": [7.09, 3.0, 6.44, 5.49],
            "skin_cp_mm": [4.94, 13.35, 19.23, 18.93],
            "two_five_g_failure": 1.3e-7,
        },
        "mission_based": {
            "mission_fuel_burn_kg": 2733.49,
            "AR": 10.401,
            "taper": 0.180,
            "c4sweep_deg": 21.577,
            "twist_cp_deg": [0.0, 4.997, -2.787, 1.055],
            "toverc_cp": [0.034, 0.112, 0.123, 0.147],
            "spar_cp_mm": [4.31, 3.0, 4.18, 4.21],
            "skin_cp_mm": [3.70, 11.20, 12.40, 14.38],
            "two_five_g_failure": 9.1e-8,
        },
        "single_point_plus_climb": {
            "mission_fuel_burn_kg": 2740.63,
            "AR": 10.401,
            "taper": 0.180,
            "c4sweep_deg": 21.754,
            "twist_cp_deg": [0.0, 4.084, -1.460, 1.206],
            "toverc_cp": [0.038, 0.117, 0.136, 0.157],
            "spar_cp_mm": [3.43, 3.0, 3.79, 4.06],
            "skin_cp_mm": [3.0, 10.44, 11.31, 13.70],
            "two_five_g_failure": 6.2e-8,
        },
    },
    1500: {
        "single_point": {
            "mission_fuel_burn_kg": 11173.83,
            "AR": None,
            "taper": 0.155,
            "c4sweep_deg": 22.45,
            "twist_cp_deg": None,
            "toverc_cp": [0.030, 0.096, 0.088, 0.114],
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
        "multipoint": {
            "mission_fuel_burn_kg": 11168.74,
            "AR": None,
            "taper": 0.162,
            "c4sweep_deg": 22.75,
            "twist_cp_deg": None,
            "toverc_cp": [0.030, 0.094, 0.088, 0.115],
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
        "mission_based": {
            "mission_fuel_burn_kg": 11141.58,
            "AR": None,
            "taper": 0.158,
            "c4sweep_deg": 22.67,
            "twist_cp_deg": None,
            "toverc_cp": [0.030, 0.093, 0.093, 0.119],
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
        "single_point_plus_climb": {
            "mission_fuel_burn_kg": 11164.54,
            "AR": None,
            "taper": 0.161,
            "c4sweep_deg": 23.07,
            "twist_cp_deg": None,
            "toverc_cp": [0.030, 0.100, 0.093, 0.123],
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
    },
    2900: {
        "single_point": {
            "mission_fuel_burn_kg": 20345.36,
            "AR": None,
            "taper": 0.140,
            "c4sweep_deg": 21.50,
            "twist_cp_deg": None,
            "toverc_cp": None,
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
        "multipoint": {
            "mission_fuel_burn_kg": 20338.33,
            "AR": None,
            "taper": 0.146,
            "c4sweep_deg": 21.85,
            "twist_cp_deg": None,
            "toverc_cp": None,
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
        "mission_based": {
            "mission_fuel_burn_kg": 20297.51,
            "AR": None,
            "taper": 0.137,
            "c4sweep_deg": 21.27,
            "twist_cp_deg": None,
            "toverc_cp": None,
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
        "single_point_plus_climb": {
            "mission_fuel_burn_kg": 20335.74,
            "AR": None,
            "taper": 0.145,
            "c4sweep_deg": 21.79,
            "twist_cp_deg": None,
            "toverc_cp": None,
            "spar_cp_mm": None,
            "skin_cp_mm": None,
            "two_five_g_failure": None,
        },
    },
}
