"""Single source of truth for the AIAA SciTech 2026 case-study reproduction.

The paper *"Autonomous Battery Units as an Enabling Technology for Urban Air
Mobility"* (AIAA SciTech 2026) evaluates three eVTOL aircraft over a fully
crossed matrix:

  * 3 vehicles  -- Archer Midnight, Joby S4, Supernal S-A2
  * 2 cruise altitudes -- 1500 ft, 3000 ft
  * 3 mission ranges  -- 30, 45, 60 miles
  = 18 cases

The 18 ``cfg/*.json`` files are the upstream case configs at the pinned evtolpy
ref (vendored, like ``mission_segments/cfg/test-all.json``). All three lanes
read from these exact files, so any lane difference is a wrapper bug, not a
difference in inputs.

Scope: this reproduces the **non-ABU** result summaries the paper builds on
(sized MTOW, mission energy, peak electric power). The ABU economics/charging/
queuing analysis is out of scope for evt v1 (see ``packages/evt/CLAUDE.md``).
"""

from __future__ import annotations

from pathlib import Path

CFG_DIR = Path(__file__).resolve().parent / "cfg"

# Matrix axes, in upstream order.
VEHICLES = ["archer-midnight", "joby-s4", "supernal"]
VEHICLE_LABELS = {
    "archer-midnight": "Archer Midnight",
    "joby-s4": "Joby S4",
    "supernal": "Supernal S-A2",
}
ALTITUDES_FT = [1500, 3000]
RANGES_MI = [30, 45, 60]


def case_id(vehicle: str, alt_ft: int, range_mi: int) -> str:
    """Stable case id, matching the vendored config basenames."""
    return f"{vehicle}-{alt_ft}-{range_mi}"


def config_path(vehicle: str, alt_ft: int, range_mi: int) -> Path:
    """Path to one vendored case config."""
    return CFG_DIR / f"{case_id(vehicle, alt_ft, range_mi)}.json"


def all_cases() -> list[tuple[str, int, int]]:
    """The 18 (vehicle, alt_ft, range_mi) tuples, in a deterministic order."""
    return [
        (v, alt, r)
        for alt in ALTITUDES_FT
        for v in VEHICLES
        for r in RANGES_MI
    ]


# Both lanes run identical pure-Python algebra, so parity is exact to round-off.
TOL = dict(rtol=1e-9, atol=1e-9)

# ---------------------------------------------------------------------------
# Golden reference values (Lane A == the paper's own method, run directly on
# the vendored configs at the pinned evtolpy ref). Pinned so an upstream-pin
# bump that silently shifts the physics is caught. ``sized_mtow_kg`` is None
# for the two cases where evtolpy's MTOW iteration hits its divergence
# safeguard (Joby S4 at 60 mi, both altitudes) -- a faithful upstream result,
# surfaced rather than hidden.
#
# keyed by case_id -> (total_mission_energy_kw_hr, peak_avg_electric_power_kw,
#                      sized_mtow_kg or None)
GOLDEN: dict[str, tuple[float, float, float | None]] = {
    "archer-midnight-1500-30": (65.9496, 846.5208, 2019.4756),
    "archer-midnight-1500-45": (92.3732, 846.5208, 2262.1183),
    "archer-midnight-1500-60": (118.7969, 846.5208, 2545.0073),
    "joby-s4-1500-30": (44.176, 525.8326, 2303.6613),
    "joby-s4-1500-45": (60.801, 525.8326, 2677.282),
    "joby-s4-1500-60": (77.4259, 525.8326, None),
    "supernal-1500-30": (71.9896, 624.2555, 2417.2195),
    "supernal-1500-45": (101.5147, 624.2555, 2757.5004),
    "supernal-1500-60": (131.0397, 624.2555, 3203.0768),
    "archer-midnight-3000-30": (63.9335, 796.5834, 1973.7508),
    "archer-midnight-3000-45": (89.7735, 796.5834, 2210.902),
    "archer-midnight-3000-60": (115.6135, 796.5834, 2488.8259),
    "joby-s4-3000-30": (46.0474, 494.813, 2357.6298),
    "joby-s4-3000-45": (62.5876, 494.813, 2831.3708),
    "joby-s4-3000-60": (79.1278, 494.813, None),
    "supernal-3000-30": (68.6425, 587.4298, 2364.5872),
    "supernal-3000-45": (97.543, 587.4298, 2694.5332),
    "supernal-3000-60": (126.4435, 587.4298, 3132.6511),
}

# ---------------------------------------------------------------------------
# Paper-published reference values, transcribed from the upstream summary
# workbook ``result-summary/weight-analysis/mtow_iteration_1500_3000_ft.xlsx``
# (2-decimal precision as published):
#   * energy = "Total Mission Energy, Without Resizing (kWh)" (column N), the
#     as-configured mission energy -- directly comparable to Lane A's
#     total_mission_energy_kw_hr.
#   * sized_mtow = "MTOW, Final (kg)" (column D). The paper converged all 18;
#     none are None here.
#
# keyed by case_id -> (energy_without_resizing_kw_hr, sized_mtow_final_kg)
PAPER: dict[str, tuple[float, float]] = {
    "archer-midnight-1500-30": (65.95, 1995.81),
    "archer-midnight-1500-45": (92.37, 2231.79),
    "archer-midnight-1500-60": (118.80, 2504.90),
    "joby-s4-1500-30": (44.18, 2159.26),
    "joby-s4-1500-45": (60.80, 2442.37),
    "joby-s4-1500-60": (77.43, 2909.02),
    "supernal-1500-30": (71.99, 2357.74),
    "supernal-1500-45": (101.51, 2675.69),
    "supernal-1500-60": (131.04, 3080.45),
    "archer-midnight-3000-30": (63.93, 1950.12),
    "archer-midnight-3000-45": (89.77, 2180.52),
    "archer-midnight-3000-60": (115.61, 2448.44),
    "joby-s4-3000-30": (46.05, 2190.80),
    "joby-s4-3000-45": (62.59, 2515.65),
    "joby-s4-3000-60": (79.13, 3217.61),
    "supernal-3000-30": (68.64, 2305.66),
    "supernal-3000-45": (97.54, 2613.47),
    "supernal-3000-60": (126.44, 3008.03),
}
