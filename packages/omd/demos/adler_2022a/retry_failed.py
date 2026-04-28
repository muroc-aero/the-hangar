"""Retry failed cells in a sweep CSV using warm starts from converged
neighbours. Mirrors brelje_2018a/retry_failed.py.

Usage:
    uv run python packages/omd/demos/adler_2022a/retry_failed.py \
        --csv results/sweep_coarse.csv --workers 4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from sweep import (
    METHOD_PLANS, METHODS, _read_final_values, _run_one,
    _checkpoint_path, _append_row, _patch_plan, RESULTS_DIR,
    _read_warm_vectors,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True, help="Path to sweep CSV with failed rows")
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 2

    df = pd.read_csv(csv_path)
    failed = df[df["converged"].astype(str).str.lower() != "true"]
    if len(failed) == 0:
        print("No failed cells.")
        return 0
    print(f"Retrying {len(failed)} failed cells with neighbour warm-starts...")

    converged = df[df["converged"].astype(str).str.lower() == "true"]

    # Build warm-start dicts using nearest converged same-method neighbour
    work = []
    for _, fr in failed.iterrows():
        rng = float(fr["mission_range_nmi"])
        mth = fr["method"]
        same = converged[converged["method"] == mth]
        if len(same) == 0:
            continue
        d = np.abs(same["mission_range_nmi"].to_numpy() - rng)
        near = same.iloc[int(np.argmin(d))]
        warm = {
            "AR": float(near["AR"]),
            "taper": float(near["taper"]),
            "c4sweep_deg": float(near["c4sweep_deg"]),
        }
        warm.update(_read_warm_vectors(float(near["mission_range_nmi"]), mth))
        work.append((rng, mth, False, warm))

    if not work:
        print("No converged neighbours to warm-start from; aborting.")
        return 1

    new_rows = list(map(_run_one, work))

    # Replace failed rows in the CSV
    out_path = csv_path.with_name(csv_path.stem + "_retried.csv")
    keep_idx = df[df["converged"].astype(str).str.lower() == "true"].index
    df = df.loc[keep_idx].reset_index(drop=True)
    out_df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    out_df.to_csv(out_path, index=False)
    print(f"Wrote retried sweep to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
