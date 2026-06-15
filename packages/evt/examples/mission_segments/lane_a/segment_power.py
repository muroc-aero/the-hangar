"""Lane A: per-segment average electric power via the direct evtolpy API.

Replicates upstream ``analysis/mission-segment-power/src/log_power_all.py``,
returning a dict instead of writing a CSV.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import CONFIG_PATH, SEGMENT_KEYS  # noqa: E402


def run() -> dict[str, float]:
    """Return {segment_stem: avg_electric_power_kw} from a directly-built Aircraft."""
    from evtol.aircraft import Aircraft

    aircraft = Aircraft(CONFIG_PATH)
    return {
        key: float(getattr(aircraft, f"{key}_avg_electric_power_kw"))
        for key in SEGMENT_KEYS
    }


if __name__ == "__main__":
    for k, v in run().items():
        print(f"{k:28s} {v:.6f}")
