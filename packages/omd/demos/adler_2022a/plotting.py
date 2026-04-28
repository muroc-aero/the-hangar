"""Render Adler 2022a Figs 7, 9, 10, 11, 12, 13 from sweep CSV +
per-design JSON.

Usage:
    uv run python packages/omd/demos/adler_2022a/plotting.py --figures all
    uv run python packages/omd/demos/adler_2022a/plotting.py --figures 7,12,13
    uv run python packages/omd/demos/adler_2022a/plotting.py \
        --csv results/sweep_full.csv --figures 7
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hangar.omd.plotting._common import mirror_spanwise

DEMO_DIR = Path(__file__).resolve().parent
RESULTS_DIR = DEMO_DIR / "results"
PER_DESIGN_DIR = RESULTS_DIR / "per_design"
FIG_DIR = DEMO_DIR / "figures" / "reproduced"
FIG_DIR.mkdir(parents=True, exist_ok=True)

METHOD_LABELS = {
    "single_point":            "single point",
    "multipoint":              "multipoint",
    "mission_based":           "mission-based",
    "single_point_plus_climb": "single point + climb",
}
METHOD_COLORS = {
    "single_point":            "tab:blue",
    "multipoint":              "tab:orange",
    "mission_based":           "tab:green",
    "single_point_plus_climb": "tab:red",
}


def _ok(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["converged"].astype(str).str.lower() == "true"].copy()


def _relative_pct(df: pd.DataFrame, baseline: str, value_col: str) -> pd.DataFrame:
    """Compute (value - baseline) / baseline * 100 by mission_range."""
    base = (
        df[df["method"] == baseline]
        .set_index("mission_range_nmi")[value_col]
        .to_dict()
    )
    df = df.copy()
    df["pct_vs_baseline"] = df.apply(
        lambda r: (r[value_col] - base.get(r["mission_range_nmi"], np.nan))
        / base.get(r["mission_range_nmi"], np.nan)
        * 100.0,
        axis=1,
    )
    return df


def fig7(df: pd.DataFrame, methods: list[str]) -> Path:
    """Fuel burn relative to single point vs mission range."""
    rel = _relative_pct(df, baseline="single_point", value_col="fuel_burn_kg")
    fig, ax = plt.subplots(figsize=(8, 4))
    for m in methods:
        sub = rel[rel["method"] == m].sort_values("mission_range_nmi")
        if sub.empty:
            continue
        ax.plot(
            sub["mission_range_nmi"], sub["pct_vs_baseline"],
            "o-", label=METHOD_LABELS.get(m, m), color=METHOD_COLORS.get(m),
        )
    ax.set_xlabel("Mission range (nmi)")
    ax.set_ylabel("Fuel burn relative to single point (%)")
    ax.set_title("Fig 7: Fuel-burn comparison across mission ranges")
    ax.grid(alpha=0.3)
    ax.legend()
    out = FIG_DIR / "fig7.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig9(df: pd.DataFrame) -> Path:
    """Stacked bar of climb / cruise / descent fuel fractions for the
    mission-based designs at each range. Requires the per-phase fuel
    breakdown to have been recorded; if not available, falls back to a
    placeholder figure with a note."""
    sub = df[df["method"] == "mission_based"].sort_values("mission_range_nmi")
    fig, ax = plt.subplots(figsize=(8, 4))
    if "climb_fuel_kg" not in sub.columns or sub["climb_fuel_kg"].isna().all():
        ax.text(
            0.5, 0.5,
            "Per-phase fuel breakdown not available in sweep CSV.\n"
            "Re-run sweep after extending _OUTPUT_KEYS in sweep.py to\n"
            "capture climb/cruise/descent fuel_used_final.",
            ha="center", va="center", transform=ax.transAxes,
        )
    else:
        ranges = sub["mission_range_nmi"]
        c, cr, d = sub["climb_fuel_kg"], sub["cruise_fuel_kg"], sub["descent_fuel_kg"]
        total = c + cr + d
        ax.bar(ranges, c / total * 100.0, label="climb", color="tab:blue")
        ax.bar(ranges, cr / total * 100.0, bottom=c / total * 100.0,
               label="cruise", color="tab:orange")
        ax.bar(ranges, d / total * 100.0,
               bottom=(c + cr) / total * 100.0,
               label="descent", color="tab:green")
        ax.legend()
    ax.set_xlabel("Mission range (nmi)")
    ax.set_ylabel("Fuel burn (% of total)")
    ax.set_title("Fig 9: Mission-based fuel-burn fraction by phase")
    out = FIG_DIR / "fig9.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _spanwise_eta(n_cp: int, symmetry: bool = True) -> np.ndarray:
    """Normalised spanwise station for control points.

    OAS uses 0 at the wing root and 1 at the tip with symmetry; spline
    cps span the half-wing from root to tip. The paper plots the
    full-span normalised position (-0.5 to 0.5).
    """
    if symmetry:
        return np.linspace(0.0, 0.5, n_cp)
    return np.linspace(-0.5, 0.5, n_cp)


def fig10(rng: float = 300.0) -> Path:
    """Spanwise wingbox parameters for the three main methods at the
    given mission range. Reads results/per_design/{rng}/{method}.json.
    """
    fig, axes = plt.subplots(3, 1, figsize=(7, 8), sharex=True)
    methods = ("single_point", "multipoint", "mission_based")
    for m in methods:
        path = PER_DESIGN_DIR / f"{int(rng)}" / f"{m}.json"
        if not path.exists():
            continue
        with open(path) as f:
            d = json.load(f)
        twist = np.array(d.get("twist_cp_deg") or [])
        toverc = np.array(d.get("toverc_cp") or [])
        skin = np.array(d.get("skin_cp_m") or []) * 1000.0  # mm
        spar = np.array(d.get("spar_cp_m") or []) * 1000.0  # mm
        eta_t = _spanwise_eta(len(twist))
        eta_tc = _spanwise_eta(len(toverc))
        eta_s = _spanwise_eta(len(skin))
        c = METHOD_COLORS.get(m, "k")
        if len(twist):
            axes[0].plot(eta_t, twist, "o-", label=METHOD_LABELS[m], color=c)
        if len(toverc):
            axes[1].plot(eta_tc, toverc * 100.0, "o-", color=c)
        if len(skin):
            axes[2].plot(eta_s, skin, "o-", color=c, label=f"{METHOD_LABELS[m]} skin")
            axes[2].plot(eta_s, spar, "x--", color=c, label=f"{METHOD_LABELS[m]} spar")

    axes[0].set_ylabel("Twist (deg)")
    axes[0].grid(alpha=0.3)
    axes[0].legend(loc="best", fontsize=8)
    axes[1].set_ylabel("Thickness-to-chord (%)")
    axes[1].grid(alpha=0.3)
    axes[2].set_ylabel("Structural thickness (mm)")
    axes[2].grid(alpha=0.3)
    axes[2].legend(loc="best", fontsize=7)
    axes[2].set_xlabel("Normalised spanwise station (root=0, tip=0.5)")
    fig.suptitle(f"Fig 10: Spanwise wingbox parameters at {int(rng)} nmi")
    out = FIG_DIR / "fig10.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig11(rng: float = 300.0) -> Path:
    """2.5 g maneuver spanwise lift distribution, all available methods overlaid.

    Cruise lift distribution is unavailable in the Bréguet variants because
    cruise drag is computed via a Kriging surrogate (AerostructDragPolar)
    which does not expose per-panel forces. Only the maneuver group's direct
    VLM+struct coupling emits wing_sec_forces. The paper's fig11 overlays
    cruise + maneuver; we ship maneuver-only as the cheapest path that still
    captures the structural-sizing trend across methods.

    Each curve is normalised so the integral over full span = 1, mirrored
    from half-span via _common.mirror_spanwise.
    """
    fig, ax = plt.subplots(figsize=(7, 4))
    rng_dir = PER_DESIGN_DIR / f"{int(rng)}"
    methods_plotted = []
    for m in ("single_point", "multipoint", "mission_based",
              "single_point_plus_climb"):
        path = rng_dir / f"{m}.json"
        if not path.exists():
            continue
        with open(path) as f:
            d = json.load(f)
        forces = d.get("lift_dist_maneuver_N")
        if forces is None:
            continue
        arr = np.asarray(forces)  # shape (nx-1, ny-1, 3)
        if arr.ndim != 3 or arr.shape[2] != 3:
            continue
        spanwise_L = arr[:, :, 2].sum(axis=0)  # length ny-1
        n_half = len(spanwise_L)
        eta_half = (np.arange(n_half) + 0.5) / n_half * 0.5  # 0..0.5
        full_eta, full_L = mirror_spanwise(eta_half, spanwise_L)
        # Normalise so integral over the full span = 1
        area = np.trapz(np.abs(full_L), full_eta)
        if area > 0:
            full_L = full_L / area
        ax.plot(full_eta, full_L, "o-",
                label=METHOD_LABELS.get(m, m),
                color=METHOD_COLORS.get(m), markersize=4)
        methods_plotted.append(m)

    if not methods_plotted:
        ax.text(
            0.5, 0.5,
            "No per-design lift_dist_maneuver_N arrays found.\n"
            "Re-run sweep.py after extending _OUTPUT_KEYS with the\n"
            "maneuver wing_sec_forces path.",
            ha="center", va="center", transform=ax.transAxes,
        )
    else:
        ax.legend(loc="best", fontsize=8)
        ax.grid(alpha=0.3)
    ax.set_xlabel("Normalised span (-0.5 = port tip, 0 = root, 0.5 = stbd tip)")
    ax.set_ylabel("Normalised spanwise lift (1/span)")
    ax.set_title(f"Fig 11: 2.5 g maneuver lift distribution at {int(rng)} nmi")
    out = FIG_DIR / "fig11.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig12(df: pd.DataFrame, methods: list[str]) -> Path:
    """Wing weight relative to single point vs mission range."""
    rel = _relative_pct(df, baseline="single_point", value_col="W_wing_maneuver_kg")
    fig, ax = plt.subplots(figsize=(8, 4))
    for m in methods:
        sub = rel[rel["method"] == m].sort_values("mission_range_nmi")
        if sub.empty:
            continue
        ax.plot(
            sub["mission_range_nmi"], sub["pct_vs_baseline"],
            "o-", label=METHOD_LABELS.get(m, m), color=METHOD_COLORS.get(m),
        )
    ax.set_xlabel("Mission range (nmi)")
    ax.set_ylabel("Wing weight relative to single point (%)")
    ax.set_title("Fig 12: Wing-weight comparison across mission ranges")
    ax.grid(alpha=0.3)
    ax.legend()
    out = FIG_DIR / "fig12.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _render_fig7_with_methods(df: pd.DataFrame, name: str) -> Path:
    rel = _relative_pct(df, baseline="single_point", value_col="fuel_burn_kg")
    fig, ax = plt.subplots(figsize=(8, 4))
    for m in ("single_point", "multipoint", "mission_based",
              "single_point_plus_climb"):
        sub = rel[rel["method"] == m].sort_values("mission_range_nmi")
        if sub.empty:
            continue
        ax.plot(
            sub["mission_range_nmi"], sub["pct_vs_baseline"],
            "o-", label=METHOD_LABELS.get(m, m), color=METHOD_COLORS.get(m),
        )
    ax.set_xlabel("Mission range (nmi)")
    ax.set_ylabel("Fuel burn relative to single point (%)")
    ax.set_title(
        "Fig 13: Including the single point + climb objective"
        if name == "fig13"
        else "Fuel burn relative to single point"
    )
    ax.grid(alpha=0.3)
    ax.legend()
    out = FIG_DIR / f"{name}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default=None,
                   help="Path to sweep CSV (default: pick newest sweep_*.csv in results/)")
    p.add_argument("--figures", default="all",
                   help="Comma-separated subset of {7, 9, 10, 11, 12, 13} or 'all'")
    p.add_argument("--design-range", type=float, default=300.0,
                   help="Mission range used for per-design figures (10, 11)")
    args = p.parse_args()

    if args.csv:
        csv_path = Path(args.csv)
    else:
        candidates = sorted(RESULTS_DIR.glob("sweep_*.csv"))
        if not candidates:
            print("No sweep CSV found. Run sweep.py first.")
            return 2
        csv_path = candidates[-1]
    print(f"Reading {csv_path}")
    df = _ok(pd.read_csv(csv_path))

    figs = args.figures.split(",")
    if figs == ["all"]:
        figs = ["7", "9", "10", "11", "12", "13"]

    if "7" in figs:
        out = fig7(df, methods=["single_point", "multipoint", "mission_based"])
        print(f"  -> {out}")
    if "9" in figs:
        out = fig9(df)
        print(f"  -> {out}")
    if "10" in figs:
        out = fig10(args.design_range)
        print(f"  -> {out}")
    if "11" in figs:
        out = fig11(args.design_range)
        print(f"  -> {out}")
    if "12" in figs:
        out = fig12(df, methods=["single_point", "multipoint", "mission_based"])
        print(f"  -> {out}")
    if "13" in figs:
        out = _render_fig7_with_methods(df, "fig13")
        print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
