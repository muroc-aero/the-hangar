"""Lane A: the per-tool OAS-in-Aviary reference, executed in .venv-avy.

Same subprocess-per-example pattern as avy_single_aisle's Lane A: the
script executed is the already-certified per-tool Lane A
(packages/avy/examples/single_aisle_oas_wing/lane_a/coupled_sizing.py),
so the omd lane and the per-tool lane share one reference implementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_AVY_PYTHON = _REPO_ROOT / ".venv-avy" / "bin" / "python"
_LANE_A_SCRIPT = (
    _REPO_ROOT
    / "packages/avy/examples/single_aisle_oas_wing/lane_a/coupled_sizing.py"
)


def run() -> dict:
    """Run the raw upstream OAS-in-Aviary reference; return the metric dict."""
    if not _AVY_PYTHON.exists():
        raise RuntimeError(
            f"{_AVY_PYTHON} not found -- run `bash scripts/setup-avy-venv.sh`."
        )
    proc = subprocess.run(
        [str(_AVY_PYTHON), str(_LANE_A_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=1800,
        cwd=_REPO_ROOT,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"Lane A subprocess failed:\n{tail}")

    metrics: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            try:
                metrics[key.strip()] = float(value)
            except ValueError:
                continue
    return metrics


if __name__ == "__main__":
    for key, val in run().items():
        print(f"{key}: {val:.4f}")
