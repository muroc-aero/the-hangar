"""Lane A: per-segment mission energy via the direct evtolpy API.

Replicates upstream ``analysis/mission-segment-energy/src/log_mission_segment_energy.py``,
returning a dict instead of writing a CSV.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import CONFIG_PATH, SEGMENT_KEYS  # noqa: E402


def run() -> dict[str, float]:
    """Return {segment_stem: energy_kw_hr} from a directly-built Aircraft."""
    from evtol.aircraft import Aircraft

    aircraft = Aircraft(CONFIG_PATH)
    return {
        key: float(getattr(aircraft, f"{key}_energy_kw_hr")) for key in SEGMENT_KEYS
    }


if __name__ == "__main__":
    for k, v in run().items():
        print(f"{k:28s} {v:.6f}")
