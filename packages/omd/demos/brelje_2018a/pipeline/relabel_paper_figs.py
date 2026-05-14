"""Overlay larger text on the Brelje 2018a paper screenshot figures.

The paper screenshots in ``figures/paper/{fig5,fig6}.png`` use small fonts
that become unreadable when two figures are placed side by side in a
publication-style layout. This script paints white rectangles over the
existing panel titles and axis labels, then redraws them at a larger
font size in the same positions.

Output: ``figures/paper/fig{5,6}_pub.png``.

Run:
    uv run python packages/omd/demos/brelje_2018a/pipeline/relabel_paper_figs.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEMO_DIR = Path(__file__).resolve().parent.parent
PAPER_DIR = DEMO_DIR / "figures" / "paper"

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
TITLE_FS = 24
XLABEL_FS = 20
YLABEL_FS = 18  # smaller so rotated label fits between panel and tick numbers

# Both fig5 (1070x920) and fig6 (1070x930) share the same matplotlib
# layout grid. Coordinates below are panel-center anchors for the
# (title, x-axis label, y-axis label) text elements in each panel.
# Per-figure anchor coordinates measured from the actual paper screenshots.
# fig5 and fig6 share an x layout but differ slightly in y (fig6 is 930 px
# tall vs fig5's 920 px) so the y anchors are figure-specific.
PANEL_CENTERS_BY_FIG = {
    5: {
        "top_left":     {"title": (275, 66),  "xlabel": (275, 438), "ylabel": (67, 241)},
        "top_right":    {"title": (735, 66),  "xlabel": (735, 438), "ylabel": (523, 241)},
        "bottom_left":  {"title": (275, 510), "xlabel": (275, 898), "ylabel": (67, 692)},
        "bottom_right": {"title": (735, 510), "xlabel": (735, 898), "ylabel": (523, 692)},
    },
    6: {
        "top_left":     {"title": (275, 71),  "xlabel": (275, 453), "ylabel": (67, 250)},
        "top_right":    {"title": (735, 71),  "xlabel": (735, 453), "ylabel": (523, 250)},
        "bottom_left":  {"title": (275, 520), "xlabel": (275, 907), "ylabel": (67, 702)},
        "bottom_right": {"title": (735, 520), "xlabel": (735, 907), "ylabel": (523, 702)},
    },
}

# White rectangles that cover the original text before redrawing.
# Sized to fully cover the original text without crashing into neighboring
# tick labels (especially the y-axis numbers at x~80 and x~565).
COVER_BOXES = {
    "title": (-220, -16, 220, 16),    # (dx_min, dy_min, dx_max, dy_max) around center
    "xlabel": (-160, -8, 160, 10),    # tight: avoid wiping out tick numbers above
    "ylabel": (-9, -100, 9, 100),     # narrow band so we keep tick numbers
}

FIG5_TITLES = {
    "top_left":     "Fuel mileage (lb/nmi)",
    "top_right":    "Trip DOC (USD) per nmi",
    "bottom_left":  "Degree of hybridization (%)",
    "bottom_right": "Maximum Takeoff Weight (lb)",
}
FIG6_TITLES = FIG5_TITLES  # identical panel set, identical labels
XLABEL = "Design range (nmi)"
YLABEL = "Specific energy (Whr/kg)"


def _draw_centered(draw: ImageDraw.ImageDraw, xy, text: str, font) -> None:
    draw.text(xy, text, fill="black", font=font, anchor="mm")


def _draw_rotated(base: Image.Image, xy, text: str, font, angle: float = 90.0) -> None:
    """Render text on a transparent canvas, rotate, and paste onto base."""
    dummy = Image.new("RGBA", (10, 10))
    db = ImageDraw.Draw(dummy)
    bbox = db.textbbox((0, 0), text, font=font, anchor="lt")
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    pad = 8
    txt = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (255, 255, 255, 0))
    ImageDraw.Draw(txt).text((txt.size[0] / 2, txt.size[1] / 2), text,
                             fill="black", font=font, anchor="mm")
    rot = txt.rotate(angle, expand=True, resample=Image.BICUBIC)
    cx, cy = xy
    px = int(cx - rot.size[0] / 2)
    py = int(cy - rot.size[1] / 2)
    base.alpha_composite(rot, (px, py))


def _cover(draw: ImageDraw.ImageDraw, anchor, kind: str) -> None:
    cx, cy = anchor
    dx_min, dy_min, dx_max, dy_max = COVER_BOXES[kind]
    draw.rectangle((cx + dx_min, cy + dy_min, cx + dx_max, cy + dy_max),
                   fill="white")


def relabel_figure(src: Path, dst: Path, titles: dict[str, str],
                   fig_num: int) -> Path:
    base = Image.open(src).convert("RGBA")
    draw = ImageDraw.Draw(base)
    title_font = ImageFont.truetype(FONT_PATH, TITLE_FS)
    xlabel_font = ImageFont.truetype(FONT_PATH, XLABEL_FS)
    ylabel_font = ImageFont.truetype(FONT_PATH, YLABEL_FS)

    centers = PANEL_CENTERS_BY_FIG[fig_num]

    # Pass 1: white out all existing text regions
    for panel, anchors in centers.items():
        _cover(draw, anchors["title"], "title")
        _cover(draw, anchors["xlabel"], "xlabel")
        _cover(draw, anchors["ylabel"], "ylabel")

    # Pass 2: draw new large labels
    for panel, anchors in centers.items():
        _draw_centered(draw, anchors["title"], titles[panel], title_font)
        _draw_centered(draw, anchors["xlabel"], XLABEL, xlabel_font)
        _draw_rotated(base, anchors["ylabel"], YLABEL, ylabel_font, angle=90.0)

    base.convert("RGB").save(dst, format="PNG", optimize=True)
    return dst


def main() -> int:
    out5 = relabel_figure(PAPER_DIR / "fig5.png", PAPER_DIR / "fig5_pub.png",
                          FIG5_TITLES, fig_num=5)
    out6 = relabel_figure(PAPER_DIR / "fig6.png", PAPER_DIR / "fig6_pub.png",
                          FIG6_TITLES, fig_num=6)
    print(f"Wrote -> {out5}")
    print(f"Wrote -> {out6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
