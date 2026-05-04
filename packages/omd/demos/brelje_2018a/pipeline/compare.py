"""Side-by-side paper vs. reproduced PNG generator.

Pastes the paper's Fig 5 or 6 crop on the left and our reproduced
figure on the right.  Defaults to the paper-style pcolormesh render
(figures/reproduced/fig{5,6}_paper.png) so the two sides use the same
visual encoding.  Pass --style contour for the contourf render.

Expects:
    figures/paper/fig{5,6}.png
    figures/reproduced/fig{5,6}_paper.png   (or fig{5,6}.png with --style contour)

Usage:
    uv run python packages/omd/demos/brelje_2018a/compare.py --figure 5
    uv run python packages/omd/demos/brelje_2018a/compare.py --figure 5 --style contour
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

DEMO_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = DEMO_DIR / "figures"


def compare(figure_num: int, style: str = "paper") -> Path:
    paper_path = OUT_DIR / "paper" / f"fig{figure_num}.png"
    repro_name = f"fig{figure_num}_paper.png" if style == "paper" else f"fig{figure_num}.png"
    repro_path = OUT_DIR / "reproduced" / repro_name
    out_path = OUT_DIR / f"comparison_fig{figure_num}.png"

    if not repro_path.exists():
        raise FileNotFoundError(
            f"Missing reproduced figure {repro_path}. Run plotting.py "
            f"--figure {figure_num} --style {style} first."
        )

    fig, axes = plt.subplots(1, 2, figsize=(18, 9))
    if paper_path.exists():
        axes[0].imshow(mpimg.imread(paper_path))
        axes[0].set_title(f"Brelje 2018a Fig {figure_num} (paper)")
    else:
        axes[0].set_facecolor("#eeeeee")
        axes[0].text(
            0.5, 0.5,
            f"Paper crop not found:\n{paper_path.relative_to(DEMO_DIR)}\n\n"
            "Generate via:\n  pdftocairo -r 200 -f <page> -l <page> -png \\\n"
            f"    Brelje2018a_OCPpareto.pdf figures/paper/fig{figure_num}",
            ha="center", va="center", transform=axes[0].transAxes,
            color="#555555", family="monospace",
        )
        axes[0].set_title(f"Brelje 2018a Fig {figure_num} (paper, MISSING)")

    axes[1].imshow(mpimg.imread(repro_path))
    axes[1].set_title(f"Fig {figure_num} reproduced from omd sweep")

    for ax in axes:
        ax.axis("off")

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--figure", type=int, choices=[5, 6], default=5)
    p.add_argument("--style", choices=["paper", "contour"], default="paper",
                   help="Which reproduced render to paste alongside the paper "
                        "crop (default: paper-style pcolormesh).")
    args = p.parse_args()
    path = compare(args.figure, style=args.style)
    print(f"Wrote -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
