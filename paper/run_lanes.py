#!/usr/bin/env python
"""Run the three-lane parity suites and collect results for the paper.

Drives the existing pytest parity suites (Lane A vs Lane B, and Lane A vs
the scripted Lane C MCP tool surface) with the PARITY_RESULTS_JSONL hook
enabled, so every comparison the tests print is also recorded as a JSON
line. No lane orchestration is duplicated here -- the tests stay the
single source of truth for how each lane runs.

Usage (from the repo root):

    uv run python paper/run_lanes.py                # full suite (slow, ~tens of minutes)
    uv run python paper/run_lanes.py --quick        # skip @pytest.mark.slow cases
    uv run python paper/run_lanes.py --lanes ab     # only Lane A vs B
    uv run python paper/run_lanes.py -k paraboloid  # subset by pytest -k expression

Then render tables with:  uv run python paper/make_tables.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parent
REPO_ROOT = PAPER_DIR.parent
RESULTS_JSONL = PAPER_DIR / "results" / "lane_parity.jsonl"
RESULTS_META = PAPER_DIR / "results" / "lane_parity_meta.json"

SUITES = {
    "ab": ["packages/omd/examples/tests/test_parity.py"],
    "c": ["packages/omd/examples/tests/test_parity_lane_c.py"],
}

# Known gap, excluded by default: ocp_pyc_coupled has no Lane B plan on
# purpose -- a faithful plan cannot reach parity with the current Lane A
# reference (see packages/omd/examples/ocp_pyc_coupled/TODO.md).
# Nodeids are rootdir-relative and pytest resolves rootdir to packages/omd
# for these suites, so list both forms; unmatched deselects are ignored.
# ocp_three_tool is deactivated with a pytest skip mark in both suites (not
# a deselect here, so --include-known-gaps does not revive it): it belongs
# to PR #88, which reworks the case. See its README for the numbers.
KNOWN_GAPS = [
    "examples/tests/test_parity.py"
    "::TestOCPPyCycleCoupledParity::test_coupled_mission_parity",
    "packages/omd/examples/tests/test_parity.py"
    "::TestOCPPyCycleCoupledParity::test_coupled_mission_parity",
]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True,
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lanes", choices=["ab", "c", "all"], default="all",
                        help="Which parity suite(s) to run (default: all)")
    parser.add_argument("--quick", action="store_true",
                        help="Skip tests marked slow (paraboloid-only smoke)")
    parser.add_argument("-k", default=None,
                        help="pytest -k expression to subset cases")
    parser.add_argument("--out", type=Path, default=RESULTS_JSONL,
                        help=f"JSONL output path (default: {RESULTS_JSONL})")
    parser.add_argument("--include-known-gaps", action="store_true",
                        help="Also run cases documented as unable to reach "
                             "parity (see KNOWN_GAPS in this script)")
    args = parser.parse_args()

    suites = SUITES["ab"] + SUITES["c"] if args.lanes == "all" else SUITES[args.lanes]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("")  # truncate: one run = one coherent result set

    env = dict(os.environ, PARITY_RESULTS_JSONL=str(args.out))

    cmd = [sys.executable, "-m", "pytest", *suites, "-v", "-s"]
    if not args.include_known_gaps:
        for nodeid in KNOWN_GAPS:
            cmd += ["--deselect", nodeid]
    if args.quick:
        cmd += ["-m", "not slow"]
    if args.k:
        cmd += ["-k", args.k]

    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env)

    n_rows = sum(1 for line in args.out.read_text().splitlines() if line.strip())
    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "lanes": args.lanes,
        "quick": args.quick,
        "k": args.k,
        "pytest_exit_code": proc.returncode,
        "n_comparisons": n_rows,
        "results_jsonl": str(args.out.relative_to(REPO_ROOT)),
    }
    RESULTS_META.write_text(json.dumps(meta, indent=2) + "\n")

    print(f"\nRecorded {n_rows} lane comparisons to {args.out}")
    print(f"Run metadata written to {RESULTS_META}")
    if proc.returncode != 0:
        print("WARNING: pytest exited nonzero -- some parity checks failed; "
              "the table will still render but flag the run as failing.")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
