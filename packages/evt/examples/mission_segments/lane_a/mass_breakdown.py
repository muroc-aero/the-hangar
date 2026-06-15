"""Lane A: component empty-mass breakdown via the direct evtolpy API.

Replicates upstream ``analysis/mission-segment-weight/src/log_mass_breakdown.py``,
returning a dict instead of writing a CSV.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import CONFIG_PATH, MASS_ATTRS  # noqa: E402


def run() -> dict[str, float]:
    """Return {mass_attr: kg} plus empty_mass_kg from a directly-built Aircraft."""
    from evtol.aircraft import Aircraft

    aircraft = Aircraft(CONFIG_PATH)
    masses = {attr: float(getattr(aircraft, attr)) for attr in MASS_ATTRS}
    masses["empty_mass_kg"] = float(aircraft.empty_mass_kg)
    return masses


if __name__ == "__main__":
    for k, v in run().items():
        print(f"{k:40s} {v:.3f}")
