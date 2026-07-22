"""Charts. Headless by default -- every function writes a file and returns its
path, so the MCP server and the CLI can hand results back without a display.

Call :func:`interactive` first (the CLI's ``--show`` flag does) to switch to a
GUI backend and have the figures open in windows as well as being saved.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402

from . import ec3, frame3d  # noqa: E402
from .model import Roof  # noqa: E402

# GUI backends worth trying, best first. Whichever imports wins.
_GUI_BACKENDS = ("QtAgg", "TkAgg", "GTK4Agg", "GTK3Agg", "WXAgg", "MacOSX")
_INTERACTIVE = False


def interactive(enable: bool = True) -> str | None:
    """Switch to a GUI backend so charts open in windows. Returns its name.

    Must be called *before* any figure is created -- matplotlib binds the
    backend at figure-creation time. Returns None if no GUI toolkit is
    installed, in which case charts are still written to disk as usual.
    """
    global _INTERACTIVE
    if not enable:
        return None
    for backend in _GUI_BACKENDS:
        try:
            matplotlib.use(backend, force=True)
        except Exception:  # noqa: BLE001 - missing toolkit, try the next
            continue
        _INTERACTIVE = True
        return backend
    return None


def _finish(fig) -> None:
    """Close the figure, unless we are keeping it around to display."""
    if not _INTERACTIVE:
        plt.close(fig)


def show() -> None:
    """Block on the open chart windows. No-op when running headless."""
    if _INTERACTIVE:
        plt.show()

# Green through amber to red: utilisation 0 -> 1 -> beyond.
UTIL_CMAP = LinearSegmentedColormap.from_list(
    "utilisation", ["#2e7d32", "#9ccc65", "#fdd835", "#fb8c00", "#c62828"]
)


def _out(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def force_diagrams(results: frame3d.Results, member: int, path: str | Path,
                   title: str = "") -> Path:
    """Axial, shear and bending moment along one member."""
    d = results.diagram(member, 201)
    x = d["x"] / 1000.0  # m

    fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    for ax, (key, label, scale, unit) in zip(
        axes,
        [("N", "Axial N", 1e-3, "kN"), ("Vz", "Shear V", 1e-3, "kN"),
         ("My", "Moment M", 1e-6, "kNm")],
    ):
        y = np.asarray(d[key]) * scale
        ax.fill_between(x, 0, y, alpha=0.3, color="#1565c0")
        ax.plot(x, y, color="#0d47a1", lw=1.6)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylabel(f"{label} [{unit}]")
        ax.grid(alpha=0.3)
        peak = y[np.argmax(np.abs(y))]
        ax.annotate(f"max {peak:.1f} {unit}", xy=(0.99, 0.9), xycoords="axes fraction",
                    ha="right", fontsize=9)
    axes[-1].set_xlabel("distance along member [m]")
    fig.suptitle(title or f"Member {member} internal actions")
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def deflected_shape(roof: Roof, results: frame3d.Results, path: str | Path,
                    scale: float | None = None) -> Path:
    """Undeformed vs deformed geometry, projected onto the X-Z plane."""
    nodes = np.array([[n.x, n.y, n.z] for n in roof.structure.nodes])
    u = results.displacements[:, :3]
    if scale is None:
        span = max(nodes.max(0) - nodes.min(0))
        peak = max(np.abs(u).max(), 1e-9)
        scale = 0.08 * span / peak
    moved = nodes + u * scale

    fig, ax = plt.subplots(figsize=(9, 5))
    for m in roof.structure.members:
        a, b = nodes[m.i], nodes[m.j]
        ax.plot([a[0] / 1e3, b[0] / 1e3], [a[2] / 1e3, b[2] / 1e3],
                color="#b0bec5", lw=1, zorder=1)
        a, b = moved[m.i], moved[m.j]
        ax.plot([a[0] / 1e3, b[0] / 1e3], [a[2] / 1e3, b[2] / 1e3],
                color="#c62828", lw=1.8, zorder=2)
    worst = float(np.abs(results.displacements[:, 2]).max())
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("z [m]")
    ax.set_title(f"Deflected shape (x{scale:.0f}) -- peak vertical {worst:.1f} mm")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def utilisation_3d(roof: Roof, checks: list[ec3.MemberResult], path: str | Path) -> Path:
    """The whole structure in 3D, each member coloured by its utilisation."""
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers the projection)

    nodes = np.array([[n.x, n.y, n.z] for n in roof.structure.nodes]) / 1000.0
    utils = np.array([c.utilisation for c in checks])
    norm = Normalize(0.0, max(1.0, float(utils.max())))

    fig = plt.figure(figsize=(11, 7))
    ax = fig.add_subplot(111, projection="3d")
    for m, u in zip(roof.structure.members, utils):
        a, b = nodes[m.i], nodes[m.j]
        ax.plot(*zip(a, b), color=UTIL_CMAP(norm(u)), lw=3 if u > 1 else 1.8)

    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_zlabel("z [m]")
    lo, hi = nodes.min(0), nodes.max(0)
    mid, rng = (lo + hi) / 2, (hi - lo).max() / 2
    for setter, c in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), mid):
        setter(c - rng, c + rng)

    sm = plt.cm.ScalarMappable(cmap=UTIL_CMAP, norm=norm)
    cb = fig.colorbar(sm, ax=ax, shrink=0.65, pad=0.1)
    cb.set_label("utilisation (1.0 = at capacity)")
    worst = checks[int(np.argmax(utils))]
    ax.set_title(
        f"{roof.span:.0f} x {roof.length:.0f} m roof, {roof.pitch_deg:.0f}deg, "
        f"snow {roof.snow_kn_m2:.1f} kN/m2 ({roof.snow_case})\n"
        f"worst {utils.max():.2f} in {worst.section} ({worst.governing.name})"
    )
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def utilisation_bars(checks: list[ec3.MemberResult], path: str | Path,
                     top: int = 20) -> Path:
    """The worst members as a ranked bar chart -- what to resize first."""
    ranked = sorted(checks, key=lambda c: -c.utilisation)[:top]
    labels = [c.section for c in ranked]
    utils = [c.utilisation for c in ranked]
    colors = [UTIL_CMAP(min(u, 1.5) / 1.5) for u in utils]

    fig, ax = plt.subplots(figsize=(9, 0.35 * len(ranked) + 2))
    ax.barh(range(len(ranked)), utils, color=colors)
    ax.set_yticks(range(len(ranked)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.axvline(1.0, color="#c62828", ls="--", lw=1.5)
    ax.set_xlabel("utilisation")
    ax.set_title(f"Worst {len(ranked)} members (dashed line = capacity)")
    for i, (u, c) in enumerate(zip(utils, ranked)):
        ax.text(u + 0.02, i, f"{u:.2f} {c.governing.name}", va="center", fontsize=7)
    ax.set_xlim(0, max(1.2, max(utils) * 1.35))
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def snow_cases(sk: float, pitch_deg: float, path: str | Path) -> Path:
    """The EN 1991-1-3 load arrangements, drawn on the roof profile."""
    from .loads import roof_snow_load

    cases = roof_snow_load(sk, pitch_deg)
    fig, axes = plt.subplots(1, len(cases), figsize=(4 * len(cases), 3.2), sharey=True)
    axes = np.atleast_1d(axes)
    rise = 0.5 * np.tan(np.radians(pitch_deg))
    peak = max(c.governing for c in cases) or 1.0

    for ax, case in zip(axes, cases):
        ax.plot([0, 0.5, 1.0], [0, rise, 0], color="#37474f", lw=2.5)
        for x0, x1, s in ((0.0, 0.5, case.left), (0.5, 1.0, case.right)):
            h = 0.35 * s / peak
            zs = [rise * (x0 * 2 if x0 < 0.5 else 2 - 2 * x0),
                  rise * (x1 * 2 if x1 < 0.5 else 2 - 2 * x1)]
            ax.fill_between([x0, x1], zs, [z + h for z in zs],
                            color="#90caf9", edgecolor="#1565c0")
            ax.text((x0 + x1) / 2, max(zs) + h + 0.03, f"{s:.2f}",
                    ha="center", fontsize=9)
        ax.set_title(case.name, fontsize=10)
        ax.set_xticks([])
        ax.set_ylim(-0.05, rise + 0.55)
    axes[0].set_ylabel("kN/m$^2$ (to scale)")
    fig.suptitle(f"EN 1991-1-3 snow arrangements -- sk={sk:.2f} kN/m2, "
                 f"pitch {pitch_deg:.0f}deg")
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p
