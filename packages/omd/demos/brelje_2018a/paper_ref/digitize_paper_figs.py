"""Digitize Brelje 2018a Figs 5 & 6 into per-cell values.

The paper publishes its trade space only as figures, so "compare to the
paper" means reading the figures back into numbers. Each panel is a
viridis image with a colorbar; this script inverts the colormap per
grid cell using the panel's own colorbar as the lookup table, so no
colormap or norm assumptions are needed.

Two panel kinds appear in the crops under ``figures/paper/``:

* ``mesh`` -- ``pcolormesh`` panels (continuous colorbar). The mesh
  cells are 25 nmi x 50 Wh/kg: the paper's grid is **21 x 12** (ranges
  300..800 step 25, energies 250..800 step 50), read off the cell edges
  in the crops. Values are exact up to 8-bit colour quantisation.
* ``contour`` -- ``contourf`` panels (banded colorbar). A cell reads
  back only as the contour band it sits in, so the value is the band
  midpoint and ``*_halfwidth`` records the band half-width.

Output: ``paper_ref/fig{5,6}_paper_digitized.csv`` with one row per
(design_range_nm, spec_energy_whkg) and columns

    fuel_mileage_lb_per_nmi, doc_per_nmi, electric_percent, MTOW_lb
    (+ <col>_halfwidth: band half-width, or colour-quantisation bound)
    (+ <col>_colour_err: RGB distance to the colorbar match; large
     values flag a pixel that is not on the colorbar -- e.g. a label)

Usage:
    uv run python packages/omd/demos/brelje_2018a/paper_ref/digitize_paper_figs.py
    uv run python ... --check   # also print the Table-4-style 500 nmi row
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

PAPER_REF = Path(__file__).resolve().parent
DEMO_DIR = PAPER_REF.parent
FIG_DIR = DEMO_DIR / "figures" / "paper"

# Paper grid (read off the pcolormesh cell edges in both crops).
RANGES_NM = np.arange(300.0, 800.0 + 1e-9, 25.0)      # 21
ENERGIES_WHKG = np.arange(250.0, 800.0 + 1e-9, 50.0)  # 12


@dataclass(frozen=True)
class Panel:
    column: str
    kind: str                 # "mesh" | "contour"
    # data-area pixel bbox (inclusive) and its data extent
    x_px: tuple[int, int]
    y_px: tuple[int, int]     # top, bottom
    x_ext: tuple[float, float]
    y_ext: tuple[float, float]  # bottom, top
    # colorbar pixel bbox (inclusive) and tick labels bottom->top
    cb_x: tuple[int, int]
    cb_y: tuple[int, int]     # top, bottom
    ticks: tuple[float, ...]


# Mesh extents are the cell edges (half a step beyond the centres);
# contourf panels span the node centres exactly.
_MESH_X = (287.5, 812.5)
_MESH_Y = (225.0, 825.0)
_CONT_X = (300.0, 800.0)
_CONT_Y = (250.0, 800.0)

# Pixel boxes measured from the committed crops (see module docstring;
# ``--show-boxes`` re-derives them from the saturated-pixel runs).
PANELS: dict[str, list[Panel]] = {
    "5": [
        Panel("fuel_mileage_lb_per_nmi", "contour", (110, 420), (74, 407),
              _CONT_X, _CONT_Y, (441, 456), (74, 407),
              (0.0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8)),
        Panel("doc_per_nmi", "mesh", (567, 866), (69, 412),
              _MESH_X, _MESH_Y, (888, 905), (68, 411),
              (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)),
        Panel("electric_percent", "mesh", (112, 412), (522, 865),
              _MESH_X, _MESH_Y, (435, 452), (522, 865),
              (0, 20, 40, 60, 80, 100)),
        Panel("MTOW_lb", "mesh", (567, 866), (522, 865),
              _MESH_X, _MESH_Y, (888, 905), (522, 865),
              (8000, 9000, 10000, 11000, 12000)),
    ],
    "6": [
        Panel("fuel_mileage_lb_per_nmi", "mesh", (113, 412), (79, 422),
              _MESH_X, _MESH_Y, (435, 452), (78, 421),
              (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)),
        Panel("doc_per_nmi", "contour", (564, 874), (85, 416),
              _CONT_X, _CONT_Y, (895, 910), (85, 416),
              (0.2, 0.275, 0.35, 0.425, 0.5, 0.575, 0.65, 0.725, 0.8, 0.875)),
        Panel("electric_percent", "mesh", (112, 412), (533, 875),
              _MESH_X, _MESH_Y, (435, 452), (532, 875),
              (0, 20, 40, 60, 80, 100)),
        Panel("MTOW_lb", "mesh", (567, 866), (532, 875),
              _MESH_X, _MESH_Y, (888, 905), (532, 875),
              (8000, 9000, 10000, 11000, 12000)),
    ],
}


def _tick_rows(img: np.ndarray, p: Panel) -> np.ndarray:
    """Pixel rows of the colorbar tick marks (short dark dashes right of
    the bar). Adjacent anti-aliased rows are merged to their centre."""
    x0 = p.cb_x[1] + 2
    strip = img[p.cb_y[0] - 3:p.cb_y[1] + 4, x0:x0 + 3].max(axis=2)
    ink = (255.0 - strip).mean(axis=1)          # 0 = white, 255 = black
    rows = np.where(ink > 60)[0]
    groups: list[list[int]] = []
    for r in rows:
        if groups and r - groups[-1][-1] <= 1:
            groups[-1].append(int(r))
        else:
            groups.append([int(r)])
    # ink-weighted centre, so a dash split over two anti-aliased rows
    # lands between them
    return np.array([np.average(g, weights=ink[g]) for g in groups]) + p.cb_y[0] - 3


def _colorbar_lut(img: np.ndarray, p: Panel):
    """(colours[N,3], values[N]) down the colorbar's centre column."""
    ticks = _tick_rows(img, p)
    if len(ticks) != len(p.ticks):
        raise RuntimeError(
            f"{p.column}: found {len(ticks)} colorbar ticks at rows "
            f"{ticks.round(1).tolist()}, expected {len(p.ticks)}")
    # ticks are listed bottom->top; pixel rows increase downward
    slope, icpt = np.polyfit(ticks[::-1], np.asarray(p.ticks, float), 1)
    resid = np.polyval([slope, icpt], ticks[::-1]) - np.asarray(p.ticks)
    if np.abs(resid).max() > 0.02 * (p.ticks[-1] - p.ticks[0]):
        raise RuntimeError(f"{p.column}: colorbar ticks are not linear")
    xc = (p.cb_x[0] + p.cb_x[1]) // 2
    rows = np.arange(p.cb_y[0] + 1, p.cb_y[1])
    colours = img[rows, xc - 2:xc + 3].mean(axis=1)
    values = np.polyval([slope, icpt], rows)
    return colours, values, abs(slope)


def _bands(colours: np.ndarray, values: np.ndarray):
    """Split a contourf colorbar into (colour, lo, hi) bands."""
    edges = [0]
    for i in range(1, len(colours)):
        if np.abs(colours[i] - colours[i - 1]).sum() > 12:
            edges.append(i)
    edges.append(len(colours))
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a < 2:
            continue
        out.append((colours[a:b].mean(axis=0),
                    float(min(values[a], values[b - 1])),
                    float(max(values[a], values[b - 1]))))
    return out


def _px(val: float, ext: tuple[float, float], px: tuple[int, int],
        flip: bool) -> float:
    f = (val - ext[0]) / (ext[1] - ext[0])
    if flip:
        f = 1.0 - f
    return px[0] + f * (px[1] - px[0])


def digitize_panel(img: np.ndarray, p: Panel) -> dict[tuple[float, float], tuple]:
    colours, values, px_step = _colorbar_lut(img, p)
    bands = _bands(colours, values) if p.kind == "contour" else None
    out = {}
    for r in RANGES_NM:
        for e in ENERGIES_WHKG:
            cx = _px(r, p.x_ext, p.x_px, flip=False)
            cy = _px(e, p.y_ext, p.y_px, flip=True)
            # keep the sample window inside the data area
            cx = min(max(cx, p.x_px[0] + 3), p.x_px[1] - 3)
            cy = min(max(cy, p.y_px[0] + 3), p.y_px[1] - 3)
            ix, iy = int(round(cx)), int(round(cy))
            win = 2 if p.kind == "mesh" else 1
            patch = img[iy - win:iy + win + 1, ix - win:ix + win + 1].reshape(-1, 3)
            c = np.median(patch, axis=0)
            if bands is None:
                d = np.linalg.norm(colours - c, axis=1)
                i = int(np.argmin(d))
                out[(r, e)] = (float(values[i]), px_step, float(d[i]))
            else:
                d = [np.linalg.norm(bc - c) for bc, _, _ in bands]
                i = int(np.argmin(d))
                _, lo, hi = bands[i]
                out[(r, e)] = ((lo + hi) / 2, (hi - lo) / 2, float(d[i]))
    return out


def digitize_figure(fig: str) -> list[dict]:
    img = np.asarray(Image.open(FIG_DIR / f"fig{fig}.png").convert("RGB")).astype(float)
    per_panel = {p.column: digitize_panel(img, p) for p in PANELS[fig]}
    rows = []
    for r in RANGES_NM:
        for e in ENERGIES_WHKG:
            row = {"design_range_nm": r, "spec_energy_whkg": e}
            for col, vals in per_panel.items():
                v, hw, err = vals[(r, e)]
                row[col] = round(v, 6)
                row[f"{col}_halfwidth"] = round(hw, 6)
                row[f"{col}_colour_err"] = round(err, 2)
            rows.append(row)
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--figure", choices=["5", "6", "all"], default="all")
    ap.add_argument("--check", action="store_true",
                    help="print the 500 nmi column for a quick eyeball")
    args = ap.parse_args()
    figs = ["5", "6"] if args.figure == "all" else [args.figure]
    for fig in figs:
        rows = digitize_figure(fig)
        out = PAPER_REF / f"fig{fig}_paper_digitized.csv"
        write_csv(rows, out)
        bad = [r for r in rows
               if any(r[k] > 40 for k in r if k.endswith("_colour_err"))]
        print(f"fig{fig}: {len(rows)} cells -> {out.relative_to(DEMO_DIR)}"
              f"  ({len(bad)} cells with a poor colour match)")
        if args.check:
            print(f"  {'e':>5} {'mileage':>8} {'doc':>7} {'elec%':>6} {'MTOW':>7}")
            for r in rows:
                if r["design_range_nm"] == 500.0:
                    print(f"  {r['spec_energy_whkg']:5.0f} "
                          f"{r['fuel_mileage_lb_per_nmi']:8.3f} "
                          f"{r['doc_per_nmi']:7.3f} "
                          f"{r['electric_percent']:6.1f} {r['MTOW_lb']:7.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
