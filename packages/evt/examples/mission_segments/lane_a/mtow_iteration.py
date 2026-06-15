"""Lane A: MTOW convergence via the direct evtolpy API.

Replicates upstream ``analysis/mission-segment-weight/src/log_mtow_iteration.py``,
returning the converged MTOW and history instead of writing a CSV.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import CONFIG_PATH  # noqa: E402


def run() -> dict:
    """Return {sized_mtow_kg, iterations, history} from a directly-built Aircraft."""
    from evtol.aircraft import Aircraft

    aircraft = Aircraft(CONFIG_PATH)
    final_mtow, history = aircraft._iterate_mtow()
    return {
        "sized_mtow_kg": float(final_mtow),
        "iterations": len(history),
        "history": history,
    }


if __name__ == "__main__":
    out = run()
    print(f"sized MTOW: {out['sized_mtow_kg']:.4f} kg in {out['iterations']} iters")
