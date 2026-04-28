"""Build side-by-side paper-vs-reproduced comparison PNGs.

Usage:
    uv run python packages/omd/demos/adler_2022a/compare.py --figures all
    uv run python packages/omd/demos/adler_2022a/compare.py --figures 7,12
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

DEMO_DIR = Path(__file__).resolve().parent
PAPER_DIR = DEMO_DIR / "figures" / "paper"
REPRODUCED_DIR = DEMO_DIR / "figures" / "reproduced"
COMPARISON_DIR = DEMO_DIR / "figures"

PAPER_DIR.mkdir(parents=True, exist_ok=True)
REPRODUCED_DIR.mkdir(parents=True, exist_ok=True)


def compare(fig_num: int) -> Path | None:
    paper = PAPER_DIR / f"fig{fig_num}.png"
    repro = REPRODUCED_DIR / f"fig{fig_num}.png"
    if not paper.exists():
        print(f"  Missing paper crop: {paper}; skipping")
        return None
    if not repro.exists():
        print(f"  Missing reproduced PNG: {repro}; run plotting.py first")
        return None
    a = Image.open(paper).convert("RGB")
    b = Image.open(repro).convert("RGB")
    h = max(a.height, b.height)
    aa = a.resize((int(a.width * h / a.height), h))
    bb = b.resize((int(b.width * h / b.height), h))
    canvas = Image.new("RGB", (aa.width + bb.width + 8, h), "white")
    canvas.paste(aa, (0, 0))
    canvas.paste(bb, (aa.width + 8, 0))
    out = COMPARISON_DIR / f"comparison_fig{fig_num}.png"
    canvas.save(out)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--figures", default="all",
                   help="Comma-separated subset or 'all'")
    args = p.parse_args()
    figs = args.figures.split(",")
    if figs == ["all"]:
        figs = ["7", "9", "10", "11", "12", "13"]
    for n in figs:
        out = compare(int(n))
        if out:
            print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
