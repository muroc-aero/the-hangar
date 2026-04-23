"""2x2 contour grid plotting for Brelje 2018a Figs 5 and 6.

Reads the per-figure CSV produced by ``sweep.py`` and produces a single
4-panel matplotlib figure in the paper's style: design range on the x
axis, battery specific energy on the y axis, filled contours for (a)
fuel mileage, (b) trip DOC, (c) electric %, (d) MTOW.

Matches the paper's axis labels and colorbar ranges where possible;
NaN cells are left blank so partial sweeps still produce a readable plot.

Usage:
    uv run python packages/omd/demos/brelje_2018a/plotting.py --figure 5
    uv run python packages/omd/demos/brelje_2018a/plotting.py --figure 6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DEMO_DIR = Path(__file__).resolve().parent
RESULTS_DIR = DEMO_DIR / "results"
OUT_DIR = DEMO_DIR / "figures" / "reproduced"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Paper Fig 5/6 colorbar ranges (visual estimates from pages 14 and 16).
_PANEL_SPECS = {
    5: {
        "fuel_mileage_lb_per_nmi":  {"vmin": 0.0, "vmax": 1.8,  "label": "Fuel mileage (lb/nmi)"},
        "doc_per_nmi":              {"vmin": 0.2, "vmax": 0.9,  "label": "Trip DOC (USD) per nmi"},
        "electric_percent":         {"vmin": 0.0, "vmax": 100.0, "label": "Degree of hybridization (electric percent)"},
        "MTOW_lb":                  {"vmin": 8000, "vmax": 12000, "label": "Maximum Takeoff Weight (lb)"},
    },
    6: {
        "fuel_mileage_lb_per_nmi":  {"vmin": 0.0, "vmax": 2.0,  "label": "Fuel mileage (lb/nmi)"},
        "doc_per_nmi":              {"vmin": 0.2, "vmax": 0.875, "label": "Trip DOC (USD) per nmi"},
        "electric_percent":         {"vmin": 0.0, "vmax": 100.0, "label": "Degree of hybridization (electric percent)"},
        "MTOW_lb":                  {"vmin": 8000, "vmax": 12000, "label": "Maximum Takeoff Weight (lb)"},
    },
}


def _pivot_grid(df: pd.DataFrame, column: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (range_axis, energy_axis, grid) with grid shape (n_energy, n_range)."""
    sub = df[["design_range_nm", "spec_energy_whkg", column]].copy()
    sub[column] = pd.to_numeric(sub[column], errors="coerce")
    piv = sub.pivot_table(
        index="spec_energy_whkg",
        columns="design_range_nm",
        values=column,
        aggfunc="last",
    )
    return piv.columns.to_numpy(), piv.index.to_numpy(), piv.to_numpy()


def _plot_panel(ax, x, y, z, spec: dict, paper_fig: int) -> None:
    vmin = spec["vmin"]
    vmax = spec["vmax"]
    levels = np.linspace(vmin, vmax, 11)
    # Mask any cells that failed to converge
    zmasked = np.ma.masked_invalid(z)
    if zmasked.count() == 0:
        ax.set_facecolor("#eeeeee")
        ax.text(0.5, 0.5, "no converged cells", ha="center", va="center",
                transform=ax.transAxes, color="#888888")
    else:
        cf = ax.contourf(x, y, zmasked, levels=levels, cmap="viridis",
                         extend="both")
        cbar = plt.colorbar(cf, ax=ax, pad=0.02)
        cbar.set_label(spec["label"])
    ax.set_xlabel("Design range (nmi)")
    ax.set_ylabel("Specific energy (Whr/kg)")
    ax.set_xlim(300, 800)
    ax.set_ylim(300, 800)


def plot_figure(figure_num: int, csv_path: Path | None = None,
                out_path: Path | None = None) -> Path:
    if figure_num not in (5, 6):
        raise ValueError(f"figure must be 5 or 6, got {figure_num}")
    if csv_path is None:
        csv_path = RESULTS_DIR / f"fig{figure_num}_grid.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No sweep results at {csv_path}.  Run sweep.py first.")

    df = pd.read_csv(csv_path)
    # keep only converged cells in the fields we're plotting
    for col in ["fuel_mileage_lb_per_nmi", "doc_per_nmi",
                "electric_percent", "MTOW_lb"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # When the sweep used the min-fuel objective without the cost
    # model, the recorder never produced a doc_per_nmi value.  Estimate
    # it offline from the same Brelje Section IV.D coefficients used
    # in factories/ocp/builder.py.  OEW is backed out from the weight
    # equation MTOW = OEW + fuel + W_battery + payload + margin
    # (margin ~ 0 at the MTOW-limited optimum).
    if df["doc_per_nmi"].isna().all():
        payload_kg = 1000.0 / 2.20462
        oew_kg = (df["MTOW_kg"] - df["fuel_burn_kg"] - df["W_battery_kg"]
                  - payload_kg).clip(lower=0.0)
        batt_energy_MJ = 0.9 * df["W_battery_kg"] * df["spec_energy_whkg"] * 0.0036
        fuel_usd = df["fuel_burn_kg"] * (2.50 / 3.08)
        elec_usd = batt_energy_MJ * (36.0 / 3600.0)
        airframe_NR_cost = (
            277.0 * oew_kg * 1.1
            + 775.0 * df["engine_rating_hp"] * 1.1
            + 100.0 * df["motor_rating_hp"] * 1.1
            + 100.0 * df["generator_rating_hp"] * 1.1
        )
        depreciation_usd = airframe_NR_cost / (5.0 * 365.0 * 15.0)
        battery_trip_usd = 50.0 * df["W_battery_kg"] / 1500.0
        trip_doc_usd = fuel_usd + elec_usd + depreciation_usd + battery_trip_usd
        df["doc_per_nmi"] = trip_doc_usd / df["design_range_nm"]

    df.loc[df["converged"].astype(str).str.lower() != "true",
           ["fuel_mileage_lb_per_nmi", "doc_per_nmi",
            "electric_percent", "MTOW_lb"]] = np.nan

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    specs = _PANEL_SPECS[figure_num]
    panels = [
        ("fuel_mileage_lb_per_nmi", axes[0, 0]),
        ("doc_per_nmi",             axes[0, 1]),
        ("electric_percent",        axes[1, 0]),
        ("MTOW_lb",                 axes[1, 1]),
    ]
    for col, ax in panels:
        x, y, z = _pivot_grid(df, col)
        _plot_panel(ax, x, y, z, specs[col], figure_num)

    objective_label = "Minimum fuel burn MDO results" if figure_num == 5 else "Minimum cost MDO results"
    fig.suptitle(
        f"Fig {figure_num} reproduction -- {objective_label} "
        f"({df['converged'].astype(str).str.lower().eq('true').sum()}/{len(df)} converged)",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    if out_path is None:
        out_path = OUT_DIR / f"fig{figure_num}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--figure", type=int, choices=[5, 6], default=5)
    p.add_argument("--csv", type=str, default=None)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    csv_path = Path(args.csv) if args.csv else None
    out_path = Path(args.out) if args.out else None
    path = plot_figure(args.figure, csv_path=csv_path, out_path=out_path)
    print(f"Wrote -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
