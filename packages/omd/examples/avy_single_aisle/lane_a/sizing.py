"""Lane A: the per-tool single-aisle Lane A reference, run in-process.

The script executed is the already-certified per-tool Lane A
(packages/avy/examples/single_aisle_sizing/lane_a/sizing.py),
so the omd lane and the per-tool lane share one reference implementation.
Aviary lives in the workspace venv, so the reference is imported and
called directly (no subprocess); the per-tool script's own ``shared``
module is loaded in isolation so it cannot collide with another example's.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_LANE_A_SCRIPT = _REPO_ROOT / "packages/avy/examples/single_aisle_sizing/lane_a/sizing.py"


def run() -> dict:
    """Run the raw-Aviary reference in this process; return the metric dict."""
    example_dir = _LANE_A_SCRIPT.parent.parent
    saved_shared = sys.modules.pop("shared", None)
    sys.path.insert(0, str(example_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_lane_a_avy_single_aisle", _LANE_A_SCRIPT
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run()
    finally:
        sys.path.remove(str(example_dir))
        sys.modules.pop("shared", None)
        if saved_shared is not None:
            sys.modules["shared"] = saved_shared


if __name__ == "__main__":
    for key, val in run().items():
        print(f"{key}: {val:.4f}")
