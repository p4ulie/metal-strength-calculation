"""Regenerate the images the README uses. Run after anything that changes a chart.

    uv run python docs/make_images.py

Kept as a script rather than committed screenshots alone, so the pictures can be
rebuilt when the charts move rather than quietly ageing.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from metal_strength import shapes, viz  # noqa: E402
from metal_strength.model import roof  # noqa: E402

OUT = Path(__file__).parent / "images"
SNOW = 0.8 * 4.0  # 1 m of wet snow at 20 degrees


def dashboard() -> None:
    """The window you get from `./ms`: four panels and the live controls."""
    fig = viz.dashboard(span=12.0, length=20.0, pitch_deg=20.0, rafter="IPE450",
                        column="HEB240", purlin="SHS140x140x5",
                        snow_depth=1.0, snow_state="wet")
    fig.savefig(OUT / "dashboard.png", dpi=72)
    plt.close(fig)


def shape_gallery() -> None:
    """Every preset profile, drawn to the same scale."""
    fig, axes = plt.subplots(2, 4, figsize=(13, 5))
    for ax, name in zip(axes.ravel(), shapes.SHAPES):
        span = 30.0 if name in ("sawtooth", "multispan") else 12.0
        frame = shapes.frame(name, span, 20.0, 3.0)
        xs = [x / span * 12 for x, _ in frame.points]
        ax.plot(xs, [z for _, z in frame.points], color="#1565c0", lw=2)
        for seg in frame.segments:
            if seg.role == "column":
                ax.plot([seg.x0 / span * 12] * 2, [seg.z0, seg.z1],
                        color="#90a4ae", lw=1.5)
        ax.set_title(f"{name}\n{len(frame.rafters)} slopes, "
                     f"{len(frame.segments) - len(frame.rafters)} columns",
                     fontsize=9)
        ax.set_xlim(-1, 13)
        ax.set_ylim(0, 10)
        ax.set_xticks([])
        ax.set_yticks([])
    # The eighth cell is a hand-drawn arch: what profile_points is for.
    ax = axes.ravel()[-1]
    import math

    pts = [(x, 3.0 + 3.0 * math.sin(math.pi * x / 12)) for x in
           [0, 1.5, 3, 4.5, 6, 7.5, 9, 10.5, 12]]
    arch = shapes.from_points(pts)
    ax.plot([x for x, _ in pts], [z for _, z in pts], color="#c62828", lw=2)
    for seg in arch.segments:
        if seg.role == "column":
            ax.plot([seg.x0] * 2, [seg.z0, seg.z1], color="#90a4ae", lw=1.5)
    ax.set_title("custom (profile_points)\ndrawn, or sent by a tool call", fontsize=9)
    ax.set_xlim(-1, 13)
    ax.set_ylim(0, 10)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(OUT / "shapes.png", dpi=90)
    plt.close(fig)


def snow_arrangements() -> None:
    """Valley accumulation on a multi-span roof, EN 1991-1-3 5.3.4."""
    viz.snow_cases(4.0, 15.0, OUT / "snow_multispan.png", shape="multispan")


def utilisation() -> None:
    """The 3D panel on its own -- where a member is, not just how loaded."""
    con = roof(span=30, length=25, pitch_deg=15, shape="multispan",
               rafter="IPE400", column="HEB240", purlin="SHS140x140x5",
               snow_kn_m2=SNOW)
    results = con.solve()
    viz.utilisation_3d(con, con.check(results), OUT / "utilisation_3d.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for build in (dashboard, shape_gallery, snow_arrangements, utilisation):
        build()
        print(f"  {build.__name__}")
    for image in sorted(OUT.glob("*.png")):
        print(f"{image.relative_to(OUT.parent)}  {image.stat().st_size / 1024:.0f} kB")
