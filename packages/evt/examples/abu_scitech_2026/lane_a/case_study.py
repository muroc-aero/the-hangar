"""Lane A: the case study via the direct evtolpy API (ground truth).

This is the paper's own method: build an evtolpy ``Aircraft`` from each of the
18 vendored case configs and harvest the headline non-ABU metrics:

  * total mission energy (kW*hr)        -- as-configured MTOW, no iteration
  * peak segment average electric power (kW)
  * sized MTOW (kg)                     -- evtolpy's ``_iterate_mtow`` loop

``_iterate_mtow`` raises ``ValueError`` on divergence (the upstream safeguard);
that case is recorded with ``sized_mtow_kg=None`` and ``converged=False`` rather
than aborting the sweep, so the two non-convergent Joby S4 60-mile cases surface
instead of disappearing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import all_cases, case_id, config_path  # noqa: E402

# 18 mission segment attribute stems (upstream order); peak power is the max
# average electric power across all of them.
_SEGMENT_KEYS = [
    "depart_taxi", "hover_climb", "trans_climb", "depart_proc", "accel_climb",
    "cruise", "decel_descend", "arrive_proc", "trans_descend", "hover_descend",
    "arrive_taxi", "reserve_hover_climb", "reserve_trans_climb",
    "reserve_accel_climb", "reserve_cruise", "reserve_decel_descend",
    "reserve_trans_descend", "reserve_hover_descend",
]


def run_case(vehicle: str, alt_ft: int, range_mi: int) -> dict:
    """Return the headline metrics for one case via the direct evtolpy API."""
    from evtol.aircraft import Aircraft

    cfg = str(config_path(vehicle, alt_ft, range_mi))
    aircraft = Aircraft(cfg)

    energy = float(aircraft.total_mission_energy_kw_hr)
    peak_power = max(
        float(getattr(aircraft, f"{k}_avg_electric_power_kw"))
        for k in _SEGMENT_KEYS
    )

    try:
        final_mtow, history = aircraft._iterate_mtow()
        sized = float(final_mtow)
        iters = len(history)
        converged = bool(history) and abs(history[-1]["delta_kg"]) < 1e-3
    except ValueError:
        # evtolpy's MTOW-divergence safeguard tripped: not a code error, a
        # real result -- this vehicle/range does not close MTOW.
        sized = None
        iters = None
        converged = False

    return {
        "case_id": case_id(vehicle, alt_ft, range_mi),
        "vehicle": vehicle,
        "alt_ft": alt_ft,
        "range_mi": range_mi,
        "total_mission_energy_kw_hr": energy,
        "peak_avg_electric_power_kw": peak_power,
        "sized_mtow_kg": sized,
        "iterations": iters,
        "converged": converged,
    }


def run_all() -> list[dict]:
    """Run all 18 cases; returns a list of metric dicts in matrix order."""
    return [run_case(v, alt, r) for (v, alt, r) in all_cases()]


if __name__ == "__main__":
    for row in run_all():
        mtow = "diverged" if row["sized_mtow_kg"] is None else f"{row['sized_mtow_kg']:9.3f}"
        print(
            f"{row['case_id']:26s} E={row['total_mission_energy_kw_hr']:8.3f} "
            f"Ppk={row['peak_avg_electric_power_kw']:8.2f} MTOW={mtow}"
        )
