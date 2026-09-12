"""Lane A: the per-tool avy Lane A reference, executed in .venv-avy.

Aviary cannot be imported in the main workspace venv (numpy-2 split), so
the raw-upstream reference runs as a subprocess with the isolated venv's
interpreter -- the same subprocess-per-example approach the agent-eval
harness uses for its Lane A references. The script executed is the
already-certified per-tool Lane A
(packages/avy/examples/single_aisle_sizing/lane_a/sizing.py), so the omd
lane and the per-tool lane share one reference implementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_AVY_PYTHON = _REPO_ROOT / ".venv-avy" / "bin" / "python"
_LANE_A_SCRIPT = (
    _REPO_ROOT
    / "packages/avy/examples/single_aisle_sizing/lane_a/sizing.py"
)


def run() -> dict:
    """Run the raw-Aviary reference in .venv-avy; return the metric dict."""
    if not _AVY_PYTHON.exists():
        raise RuntimeError(
            f"{_AVY_PYTHON} not found -- run `bash scripts/setup-avy-venv.sh`."
        )
    proc = subprocess.run(
        [str(_AVY_PYTHON), str(_LANE_A_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=900,
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
