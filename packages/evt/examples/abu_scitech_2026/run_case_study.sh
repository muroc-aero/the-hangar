#!/usr/bin/env bash
# Full non-ABU reproduction of the AIAA SciTech 2026 case study:
# the 18-case grid CSV, the comparison figures, and the fidelity table.
# Lane A (direct evtolpy) is the ground truth; ~minutes (16 of 18 cases
# run an MTOW iteration).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== aggregate: 18 cases -> grid CSV =="
uv run python "$HERE/pipeline/aggregate.py"

echo "== plot: comparison figures =="
uv run python "$HERE/pipeline/plotting.py"

echo "== plot: wrapper parity (direct evtolpy vs cli/mcp) =="
uv run python "$HERE/pipeline/compare_lanes_plot.py"

echo "== fidelity: reproduced vs paper =="
uv run python "$HERE/pipeline/compare_to_paper.py"

echo "== done. artifacts in results/ and figures/reproduced/ =="
