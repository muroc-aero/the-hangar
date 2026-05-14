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

DEMO_DIR = Path(__file__).resolve().parent.parent
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


def _cell_edges(centers: np.ndarray) -> np.ndarray:
    """Convert N cell-center coordinates to N+1 cell-edge coordinates so
    pcolormesh draws each grid cell as a rectangle centered on its (x, y).
    Edges are placed at midpoints with end-cell extrapolation."""
    if len(centers) < 2:
        d = 1.0
        return np.array([centers[0] - d / 2, centers[0] + d / 2])
    mids = 0.5 * (centers[:-1] + centers[1:])
    first = centers[0] - (mids[0] - centers[0])
    last = centers[-1] + (centers[-1] - mids[-1])
    return np.concatenate([[first], mids, [last]])


def _plot_panel(ax, x, y, z, spec: dict, paper_fig: int,
                style: str = "contour", overlay_contours: bool = False,
                label_fontsize: float | None = None) -> None:
    """Render one of the four panels.

    style="contour": filled contourf (legacy/smooth look).
    style="paper":   pcolormesh per-cell rectangles, matching the paper
                     figures.  When overlay_contours=True, draw thin
                     contour lines on top (top-left fuel-mileage panel
                     in the paper has this).
    """
    vmin = spec["vmin"]
    vmax = spec["vmax"]
    zmasked = np.ma.masked_invalid(z)
    if zmasked.count() == 0:
        ax.set_facecolor("#eeeeee")
        ax.text(0.5, 0.5, "no converged cells", ha="center", va="center",
                transform=ax.transAxes, color="#888888")
    elif style == "paper":
        xe = _cell_edges(np.asarray(x, dtype=float))
        ye = _cell_edges(np.asarray(y, dtype=float))
        pm = ax.pcolormesh(xe, ye, zmasked, cmap="viridis",
                           vmin=vmin, vmax=vmax, shading="flat")
        cbar = plt.colorbar(pm, ax=ax, pad=0.02)
        if label_fontsize is not None:
            cbar.set_label(spec["label"], fontsize=label_fontsize)
            cbar.ax.tick_params(labelsize=label_fontsize)
        else:
            cbar.set_label(spec["label"])
        if overlay_contours:
            n_lines = 18
            levels = np.linspace(vmin, vmax, n_lines)
            ax.contour(x, y, zmasked, levels=levels, colors="white",
                       linewidths=0.4, alpha=0.85)
    else:
        levels = np.linspace(vmin, vmax, 11)
        cf = ax.contourf(x, y, zmasked, levels=levels, cmap="viridis",
                         extend="both")
        cbar = plt.colorbar(cf, ax=ax, pad=0.02)
        cbar.set_label(spec["label"])
    if label_fontsize is not None:
        ax.set_xlabel("Design range (nmi)", fontsize=label_fontsize)
        ax.set_ylabel("Specific energy (Whr/kg)", fontsize=label_fontsize)
        ax.tick_params(axis="both", labelsize=label_fontsize)
    else:
        ax.set_xlabel("Design range (nmi)")
        ax.set_ylabel("Specific energy (Whr/kg)")
    if style == "paper":
        # Tight axis limits matching the cell-edge grid (no whitespace
        # around the painted cells, like the paper figures).
        xe = _cell_edges(np.asarray(x, dtype=float))
        ye = _cell_edges(np.asarray(y, dtype=float))
        ax.set_xlim(xe[0], xe[-1])
        ax.set_ylim(ye[0], ye[-1])
    else:
        ax.set_xlim(300, 800)
        ax.set_ylim(300, 800)


def plot_figure(figure_num: int, csv_path: Path | None = None,
                out_path: Path | None = None,
                style: str = "contour",
                pub: bool = False) -> Path:
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

    # figsize chosen to match the Brelje 2018a paper crop aspect (~1.16:1).
    # Publication preset: keep paper-style aspect but bump fonts so when
    # two figures are placed side by side and reduced ~2x for printing,
    # axis text renders near 8pt.
    if pub:
        fig, axes = plt.subplots(2, 2, figsize=(11.0, 9.0),
                                 constrained_layout=True)
        label_fs = 18.0
        suptitle_fs = 20.0
    else:
        fig, axes = plt.subplots(2, 2, figsize=(10.5, 9))
        label_fs = None
        suptitle_fs = 12.0
    specs = _PANEL_SPECS[figure_num]
    if pub:
        # Shorter colorbar labels avoid overflow into the neighboring panel.
        _SHORT = {
            "fuel_mileage_lb_per_nmi": "Fuel mileage (lb/nmi)",
            "doc_per_nmi":             "Trip DOC (USD/nmi)",
            "electric_percent":        "Hybridization (% electric)",
            "MTOW_lb":                 "MTOW (lb)",
        }
        specs = {k: {**v, "label": _SHORT[k]} for k, v in specs.items()}
    panels = [
        ("fuel_mileage_lb_per_nmi", axes[0, 0], True),   # overlay contours
        ("doc_per_nmi",             axes[0, 1], False),
        ("electric_percent",        axes[1, 0], False),
        ("MTOW_lb",                 axes[1, 1], False),
    ]
    for col, ax, overlay in panels:
        x, y, z = _pivot_grid(df, col)
        _plot_panel(ax, x, y, z, specs[col], figure_num,
                    style=style, overlay_contours=overlay,
                    label_fontsize=label_fs)

    objective_label = "Minimum fuel burn MDO results" if figure_num == 5 else "Minimum cost MDO results"
    if pub:
        fig.suptitle(
            f"Fig {figure_num}: {objective_label}",
            fontsize=suptitle_fs,
        )
    else:
        style_tag = " (paper style)" if style == "paper" else ""
        fig.suptitle(
            f"Fig {figure_num} reproduction{style_tag} -- {objective_label} "
            f"({df['converged'].astype(str).str.lower().eq('true').sum()}/{len(df)} converged)",
            fontsize=suptitle_fs,
        )
    if not pub:
        fig.tight_layout(rect=(0, 0, 1, 0.96))

    if out_path is None:
        if pub:
            suffix = "_paper_pub" if style == "paper" else "_pub"
        else:
            suffix = "_paper" if style == "paper" else ""
        out_path = OUT_DIR / f"fig{figure_num}{suffix}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--figure", type=int, choices=[5, 6], default=5)
    p.add_argument("--csv", type=str, default=None)
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--style", choices=["contour", "paper"], default="contour",
                   help="contour: smooth contourf (default); paper: pcolormesh "
                        "per-cell rectangles + overlaid contour lines on the "
                        "fuel-mileage panel, matching the Brelje 2018a figures.")
    p.add_argument("--pub", action="store_true",
                   help="Publication preset: smaller figure size with larger "
                        "axis/colorbar/title fonts so two figures side by side "
                        "print at ~8pt text.")
    args = p.parse_args()

    csv_path = Path(args.csv) if args.csv else None
    out_path = Path(args.out) if args.out else None
    path = plot_figure(args.figure, csv_path=csv_path, out_path=out_path,
                       style=args.style, pub=args.pub)
    print(f"Wrote -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
