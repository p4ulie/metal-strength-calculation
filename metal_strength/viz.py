"""Charts, and the interactive dashboard.

Headless by default -- every ``*_png`` function writes a file and returns its
path, so the MCP server and the CLI can hand results back without a display.

Call :func:`interactive` first (the CLI's ``--show`` flag does) to switch to a
GUI backend, then :func:`panel` for one window of subplots, or
:func:`dashboard` for the same window with live sliders that re-solve the
structure as you move them.

Every panel is drawn by a ``_draw_*`` helper that takes an axes, so the saved
PNGs and the on-screen dashboard cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402

from . import ec3, frame3d, i18n  # noqa: E402
from .model import Roof  # noqa: E402

# GUI backends worth trying, best first. Whichever imports wins.
_GUI_BACKENDS = ("QtAgg", "TkAgg", "GTK4Agg", "GTK3Agg", "WXAgg", "MacOSX")
_INTERACTIVE = False

# Language for chart text. The CLI sets it from --lang before drawing.
# ponytail: module global, not a parameter on nine drawing functions -- one
# process draws in one language. Thread it through if that stops being true.
LANG = "en"

# How many members the ranking chart lists. 0 means all of them; the CLI's
# --top sets it, exactly as --lang sets LANG above.
RANKING_TOP = 12


def _L(key: str) -> str:
    return i18n.t(key, LANG)


def _label(check: ec3.MemberResult) -> str:
    return i18n.member_label(check.section, LANG)


# Green through amber to red: utilisation 0 -> 1 -> beyond.
UTIL_CMAP = LinearSegmentedColormap.from_list(
    "utilisation", ["#2e7d32", "#9ccc65", "#fdd835", "#fb8c00", "#c62828"]
)
# Fixed so a colour means the same thing however the sliders are set.
UTIL_NORM = Normalize(0.0, 1.5)


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
        # Unhinted text renders ~20% faster and only matters on screen, where a
        # redraw is in the interaction loop. Saved PNGs keep the crisp default.
        matplotlib.rcParams["text.hinting"] = "none"
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


def _out(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# --- panel painters ---------------------------------------------------------
# Each takes an axes and draws into it. Used by both the PNG functions and the
# dashboard, so there is only ever one version of each chart.


def _draw_forces(axes, results: frame3d.Results, member: int, title: str = "") -> None:
    d = results.diagram(member, 201)
    x = d["x"] / 1000.0
    for ax, (key, label, scale, unit) in zip(
        axes,
        [("N", "N", 1e-3, "kN"), ("Vz", "V", 1e-3, "kN"),
         ("My", "M", 1e-6, "kNm")],
    ):
        ax.clear()
        y = np.asarray(d[key]) * scale
        ax.fill_between(x, 0, y, alpha=0.3, color="#1565c0")
        ax.plot(x, y, color="#0d47a1", lw=1.6)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_ylabel(f"{label} [{unit}]", fontsize=9)
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=8)
        peak = y[np.argmax(np.abs(y))]
        ax.annotate(f"{_L('max')} {peak:.1f} {unit}", xy=(0.99, 0.86),
                    xycoords="axes fraction", ha="right", fontsize=8)
    axes[0].set_title(title or f"{member}: {_L('internal_actions')}", fontsize=10)
    axes[-1].set_xlabel(_L("along_member"), fontsize=9)


def _draw_deflected(ax, roof: Roof, results: frame3d.Results,
                    scale: float | None = None) -> None:
    ax.clear()
    nodes = np.array([[n.x, n.y, n.z] for n in roof.structure.nodes])
    u = results.displacements[:, :3]
    if scale is None:
        extent = max(nodes.max(0) - nodes.min(0))
        peak = max(np.abs(u).max(), 1e-9)
        scale = 0.08 * extent / peak
    moved = nodes + u * scale
    # One collection per state rather than a line artist per member: a few
    # hundred separate artists cost far more to build and to render.
    ij = np.array([(m.i, m.j) for m in roof.structure.members])
    for pts, color, lw, z in ((nodes, "#b0bec5", 1.0, 1), (moved, "#c62828", 1.8, 2)):
        xz = pts[:, [0, 2]] / 1e3
        ax.add_collection(LineCollection(xz[ij], colors=color, linewidths=lw, zorder=z))
    worst = float(np.abs(results.displacements[:, 2]).max())
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]", fontsize=9)
    ax.set_ylabel("z [m]", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.set_title(f"{_L('deflected_shape')} (x{scale:.0f}) -- "
                 f"{_L('peak')} {worst:.1f} mm", fontsize=10)
    ax.grid(alpha=0.3)


def _draw_utilisation_3d(ax, roof: Roof, checks: list[ec3.MemberResult],
                         title: str | None = None) -> None:
    from mpl_toolkits.mplot3d.art3d import Line3DCollection

    # Preserve the viewing angle across redraws so scrubbing a slider does not
    # snap the camera back.
    elev, azim = ax.elev, ax.azim
    ax.clear()
    nodes = np.array([[n.x, n.y, n.z] for n in roof.structure.nodes]) / 1000.0
    utils = np.array([c.utilisation for c in checks])
    ij = np.array([(m.i, m.j) for m in roof.structure.members])
    ax.add_collection3d(Line3DCollection(
        nodes[ij], colors=UTIL_CMAP(UTIL_NORM(utils)),
        linewidths=np.where(utils > 1, 3.0, 1.8)))
    ax.set_xlabel("x [m]", fontsize=9)
    ax.set_ylabel("y [m]", fontsize=9)
    ax.set_zlabel("z [m]", fontsize=9)
    ax.tick_params(labelsize=7)
    lo, hi = nodes.min(0), nodes.max(0)
    # A straight beam is flat in y and z, which would make those axes singular.
    pad = np.where(hi - lo < 1e-6, max((hi - lo).max(), 1.0) * 0.05, 0.0)
    lo, hi = lo - pad, hi + pad
    extent = np.maximum(hi - lo, 1e-6)
    for setter, a, b in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), lo, hi):
        setter(a, b)
    # Scale the box to the real proportions rather than forcing a cube -- a
    # 12 x 20 x 5 m roof squeezed into a cube wastes most of the panel.
    ax.set_box_aspect(tuple(extent / extent.max()))
    ax.view_init(elev=elev, azim=azim)
    if title is None:
        worst = checks[int(np.argmax(utils))]
        title = (f"{_L('worst')} {utils.max():.2f} {_L('in')} {_label(worst)} "
                 f"({worst.governing.name})")
    if title:
        ax.set_title(title, fontsize=10)


def _draw_ranking(ax, checks: list[ec3.MemberResult], top: int | None = None) -> None:
    """Members ranked by utilisation. ``top=None`` uses RANKING_TOP; 0 means all.

    A whole roof is hundreds of members, so the labelling thins out as the list
    grows: names go small, then every other one, then none at all -- the shape of
    the distribution stays readable even when the names cannot be.
    """
    ax.clear()
    limit = RANKING_TOP if top is None else top
    ranked = sorted(checks, key=lambda c: -c.utilisation)
    if limit:
        ranked = ranked[:limit]
    n = len(ranked)
    utils = [c.utilisation for c in ranked]
    ax.barh(range(n), utils, color=[UTIL_CMAP(UTIL_NORM(u)) for u in utils],
            height=1.0 if n > 60 else 0.8)

    # Size the names to the space each row actually has, which depends on how
    # tall the axes is, not just on how many bars there are: the same 86 members
    # are cramped in a dashboard panel and roomy on a 30-inch PNG.
    row_pts = 72.0 * ax.get_figure().get_size_inches()[1] * ax.get_position().height
    row_pts = row_pts / max(n, 1)
    step = 1
    while row_pts * step < 5.5 and step < 12:  # thin out until they can be read
        step += 1
    if row_pts * step >= 5.5:
        # Size to the gap between the labels actually shown, not to every row.
        ax.set_yticks(range(0, n, step),
                      [_label(c) for c in ranked[::step]],
                      fontsize=min(7.0, max(4.5, row_pts * step * 0.8)))
    else:
        # Past this many, names are unreadable at any size; the axis becomes a
        # position instead. The 3D panel is where you identify a member anyway.
        ax.set_yticks([0, n - 1], ["1", str(n)], fontsize=7)
        ax.set_ylabel(f"{_L('members')}, {_L('worst')} 1", fontsize=8)
    ax.invert_yaxis()
    ax.axvline(1.0, color="#c62828", ls="--", lw=1.5)
    ax.set_xlabel(_L("utilisation"), fontsize=9)
    failing = sum(1 for c in ranked if not c.ok)
    title = f"{_L('worst_members')} ({n}"
    title += f", {failing} !!)" if failing else ")"
    ax.set_title(title, fontsize=10)
    ax.tick_params(axis="x", labelsize=8)
    if n <= 30:
        for i, (u, c) in enumerate(zip(utils, ranked)):
            ax.text(u + 0.02, i, f"{u:.2f} {c.governing.name}",
                    va="center", fontsize=6)
    ax.set_xlim(0, max(1.25, max(utils) * 1.35))
    ax.set_ylim(n - 0.5, -0.5)
    ax.grid(axis="x", alpha=0.3)


# --- single-figure chart files ---------------------------------------------


def force_diagrams(results: frame3d.Results, member: int, path: str | Path,
                   title: str = "") -> Path:
    """Axial, shear and bending moment along one member."""
    fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    _draw_forces(axes, results, member, title)
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def deflected_shape(roof: Roof, results: frame3d.Results, path: str | Path,
                    scale: float | None = None) -> Path:
    """Undeformed vs deformed geometry, projected onto the X-Z plane."""
    fig, ax = plt.subplots(figsize=(9, 5))
    _draw_deflected(ax, roof, results, scale)
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def utilisation_3d(roof: Roof, checks: list[ec3.MemberResult],
                   path: str | Path) -> Path:
    """The whole structure in 3D, each member coloured by its utilisation."""
    fig = plt.figure(figsize=(11, 7))
    ax = fig.add_subplot(111, projection="3d")
    utils = np.array([c.utilisation for c in checks])
    worst = checks[int(np.argmax(utils))]
    _draw_utilisation_3d(
        ax, roof, checks,
        f"{roof.span:.0f} x {roof.length:.0f} m roof, {roof.pitch_deg:.0f}deg, "
        f"snow {roof.snow_kn_m2:.1f} kN/m2 ({roof.snow_case})\n"
        f"worst {utils.max():.2f} in {worst.section} ({worst.governing.name})",
    )
    cb = fig.colorbar(plt.cm.ScalarMappable(cmap=UTIL_CMAP, norm=UTIL_NORM),
                      ax=ax, shrink=0.65, pad=0.1)
    cb.set_label("utilisation (1.0 = at capacity)")
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def utilisation_bars(checks: list[ec3.MemberResult], path: str | Path,
                     top: int | None = None) -> Path:
    """The worst members as a ranked bar chart -- what to resize first.

    ``top=0`` draws every member, and the figure grows to fit.
    """
    limit = RANKING_TOP if top is None else top
    n = min(limit, len(checks)) if limit else len(checks)
    fig, ax = plt.subplots(figsize=(9, min(0.35 * n + 2, 60)))
    _draw_ranking(ax, checks, limit)
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


def snow_cases(sk: float, pitch_deg: float, path: str | Path,
               shape: str = "duopitch") -> Path:
    """The EN 1991-1-3 load arrangements, drawn on the roof profile."""
    from . import loads, shapes

    fr = shapes.frame(shape, span=1.0, pitch_deg=abs(pitch_deg), eaves_height=1.0)
    cases = loads.snow_arrangements(fr, sk)
    outline = [(x, z - 1.0) for x, z in fr.points]  # z from the eaves up
    rafters = [(s.x0, s.z0 - 1.0, s.x1, s.z1 - 1.0) for s in fr.rafters]

    fig, axes = plt.subplots(1, len(cases), figsize=(4 * len(cases), 3.2), sharey=True)
    axes = np.atleast_1d(axes)
    peak = max((c.governing for c in cases), default=0.0) or 1.0
    top = max(z for _, z in outline)

    for ax, case in zip(axes, cases):
        ax.plot([x for x, _ in outline], [z for _, z in outline],
                color="#37474f", lw=2.5)
        for (x0, z0, x1, z1), s in zip(rafters, case.values):
            h = 0.35 * s / peak
            ax.fill_between([x0, x1], [z0, z1], [z0 + h, z1 + h],
                            color="#90caf9", edgecolor="#1565c0")
            if s > 0:
                ax.text((x0 + x1) / 2, max(z0, z1) + h + 0.03, f"{s:.2f}",
                        ha="center", fontsize=8)
        ax.set_title(i18n.snow_term(case.name, LANG), fontsize=10)
        ax.set_xticks([])
        ax.set_ylim(-0.05, top + 0.55)
    axes[0].set_ylabel(f"kN/m$^2$ ({_L('to_scale')})")
    title = (f"{_L('snow_arrangements')} -- {i18n.shape_term(shape, LANG)}, "
             f"sk={sk:.2f} kN/m2, {_L('pitch')} {pitch_deg:.0f}deg")
    if fr.mu_is_approximate:
        title += f"\n{_L('mu_approximate')}"
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    p = _out(path)
    fig.savefig(p, dpi=130)
    _finish(fig)
    return p


# --- one window, four panels ------------------------------------------------


def _layout(fig, controls: bool):
    """Build the shared 2x2-ish panel layout. Returns (ax3d, axdef, axforce, axbar)."""
    bottom = 0.20 if controls else 0.06
    gs = fig.add_gridspec(2, 2, left=0.05, right=0.97, top=0.88, bottom=bottom,
                          hspace=0.32, wspace=0.22)
    ax3d = fig.add_subplot(gs[0, 0], projection="3d")
    axbar = fig.add_subplot(gs[0, 1])
    axdef = fig.add_subplot(gs[1, 0])
    inner = gs[1, 1].subgridspec(3, 1, hspace=0.12)
    axforce = [fig.add_subplot(inner[k]) for k in range(3)]
    for a in axforce[:-1]:
        a.tick_params(labelbottom=False)
    return ax3d, axdef, axforce, axbar


def _paint(axes, roof: Roof, results: frame3d.Results,
           checks: list[ec3.MemberResult]) -> ec3.MemberResult:
    """Draw all four panels. Returns the governing member."""
    ax3d, axdef, axforce, axbar = axes
    worst = max(checks, key=lambda c: c.utilisation)
    _draw_utilisation_3d(ax3d, roof, checks, title="")
    _draw_ranking(axbar, checks)
    _draw_deflected(axdef, roof, results)
    _draw_forces(axforce, results, checks.index(worst), _label(worst))
    return worst


def _headline(roof: Roof, checks: list[ec3.MemberResult],
              defl: ec3.Check, worst: ec3.MemberResult) -> str:
    ok = all(c.ok for c in checks) and defl.ok
    return (f"{i18n.verdict(ok, LANG)}   {_L('strength')} {worst.utilisation:.2f} "
            f"({worst.governing.name})   {_L('deflection')} {defl.utilisation:.2f}"
            f"   |   {_L('snow')} {roof.snow_kn_m2:.2f} kN/m$^2$")


def panel(roof: Roof, results: frame3d.Results, checks: list[ec3.MemberResult],
          title: str = ""):
    """All four charts in a single window. Static -- see :func:`dashboard` for live."""
    fig = plt.figure(figsize=(15, 9))
    axes = _layout(fig, controls=False)
    worst = _paint(axes, roof, results, checks)
    defl = roof.deflection(results)
    fig.colorbar(plt.cm.ScalarMappable(cmap=UTIL_CMAP, norm=UTIL_NORM),
                 ax=axes[0], shrink=0.6, pad=0.12, label=_L("utilisation"))
    fig.suptitle(f"{title}\n{_headline(roof, checks, defl, worst)}"
                 if title else _headline(roof, checks, defl, worst), fontsize=12)
    return fig


def _text_page(fig, lines: list[tuple[str, float, str]]) -> None:
    """Lay out (text, size, style) rows down an otherwise empty page.

    ``style`` is "normal", "bold", or "mono" for anything that is a table and
    has to keep its columns.
    """
    y = 0.94
    for text, size, style in lines:
        fig.text(0.06, y, text, fontsize=size, va="top",
                 weight="bold" if style == "bold" else "normal",
                 family="monospace" if style == "mono" else "sans-serif")
        y -= 0.022 * (size / 9.0) * (text.count("\n") + 1) + 0.012


def report_pdf(roof: Roof, results: frame3d.Results, checks: list[ec3.MemberResult],
               path: str | Path, title: str = "", material_list: str = "",
               sk: float | None = None) -> Path:
    """A multi-page PDF: summary, the four panels, snow cases, material list.

    Vector output through matplotlib's own PDF backend -- no new dependency, and
    the charts stay sharp at any zoom.
    """
    from matplotlib.backends.backend_pdf import PdfPages

    from . import loads

    defl = roof.deflection(results)
    ranked = sorted(checks, key=lambda c: -c.utilisation)
    worst = ranked[0]
    ok = all(c.ok for c in checks) and defl.ok
    fr = roof.profile

    p = _out(path)
    with PdfPages(p) as pdf:
        # -- page 1: the verdict, and what it was a verdict on ----------------
        fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
        rows = [
            (title or "metal-strength", 20, "bold"),
            (f"{_L('utilisation')}: {worst.utilisation:.2f}   "
             f"{_L('deflection')}: {defl.utilisation:.2f}", 12, "normal"),
            (f"=> {i18n.verdict(ok, LANG)}", 22, "bold"),
            ("", 9, "normal"),
        ]
        params = [
            f"{_L('shape')}: {i18n.shape_term(fr.shape, LANG) if fr else '-'}",
            f"span x length: {roof.span:.1f} x {roof.length:.1f} m",
            f"{_L('snow')}: {roof.snow_kn_m2:.2f} kN/m2   case: "
            f"{i18n.snow_term(roof.snow_case, LANG)}",
            f"{_L('members')}: {len(checks)}   {roof.total_mass_kg:,.0f} kg",
        ]
        rows.append(("\n".join(params), 10, "mono"))
        rows.append((f"{_L('worst_members')}:", 12, "bold"))
        table = [f"{'':2s}{i18n.t('utilisation', LANG):>12s}  "
                 f"{'member':<26s}{i18n.t('governing', LANG)}"]
        table += [f"{'OK' if c.ok else '!!':2s}{c.utilisation:12.2f}  "
                  f"{i18n.member_label(c.section, LANG):<26s}{c.governing.name}"
                  for c in ranked[:12]]
        rows.append(("\n".join(table), 8, "mono"))
        rows.append((f"{'OK' if defl.ok else '!!':2s}{defl.utilisation:12.2f}  "
                     f"{defl.name:<26s}{defl.demand:.1f} / {defl.capacity:.1f} mm",
                     8, "mono"))
        if fr is not None and fr.mu_is_approximate:
            rows.append((_L("mu_approximate"), 8, "bold"))
        _text_page(fig, rows)
        fig.text(0.06, 0.05, i18n.t("disclaimer", LANG), fontsize=8, wrap=True,
                 va="bottom", color="#555555")
        pdf.savefig(fig)
        _finish(fig)

        # -- page 2: the charts -----------------------------------------------
        panels = panel(roof, results, checks, title=title)
        panels.set_size_inches(11.69, 8.27)  # A4 landscape
        pdf.savefig(panels)
        _finish(panels)

        # -- page 3: the snow arrangements this shape allows -------------------
        if fr is not None and sk is not None:
            fig = plt.figure(figsize=(11.69, 8.27))
            cases = loads.snow_arrangements(fr, sk)
            axes = fig.subplots(1, len(cases), sharey=True, squeeze=False)[0]
            peak = max((c.governing for c in cases), default=1.0) or 1.0
            xs = [x for x, _ in fr.points]
            zs = [z for _, z in fr.points]
            for ax, case in zip(axes, cases):
                ax.plot(xs, zs, color="#37474f", lw=2)
                for seg, value in zip(fr.rafters, case.values):
                    h = 0.25 * (max(zs) - min(zs) + 1.0) * value / peak
                    ax.fill_between([seg.x0, seg.x1], [seg.z0, seg.z1],
                                    [seg.z0 + h, seg.z1 + h],
                                    color="#90caf9", edgecolor="#1565c0")
                ax.set_title(i18n.snow_term(case.name, LANG), fontsize=10)
                ax.set_xticks([])
            axes[0].set_ylabel("m")
            fig.suptitle(f"{_L('snow_arrangements')} -- sk={sk:.2f} kN/m2")
            pdf.savefig(fig)
            _finish(fig)

        # -- page 4: what to order --------------------------------------------
        if material_list:
            fig = plt.figure(figsize=(11.69, 8.27))
            _text_page(fig, [(i18n.t("material_list", LANG), 14, "bold"),
                             (material_list, 8, "mono")])
            pdf.savefig(fig)
            _finish(fig)

        pdf.infodict()["Title"] = title or "metal-strength report"
    return p


# --- the live dashboard -----------------------------------------------------


def _ladder(name: str) -> tuple[list[str], int]:
    """Profiles in the same family as ``name``, ordered by size, and its index."""
    from .sections import get_section, list_sections

    family = re.match(r"^[A-Za-z]+", name.upper())
    prefix = family.group(0) if family else "IPE"
    names = list_sections(prefix)
    names.sort(key=lambda n: (get_section(n).h, get_section(n).A))
    canonical = get_section(name).name
    return names, names.index(canonical) if canonical in names else 0


# The parameter set a dashboard reads and writes. The MCP session uses exactly
# these keys, so when a window is served the two are the same dict -- not two
# stores kept in step.
SESSION_KEYS = ("span_m", "length_m", "pitch_deg", "shape", "eaves_height_m",
                "frame_spacing_m", "purlin_spacing_m", "rafter", "column",
                "purlin", "grade", "snow_depth_m", "snow_state", "snow_kn_m2",
                "case", "points")


def dashboard(
    span: float = 12.0,
    length: float = 20.0,
    pitch_deg: float = 20.0,
    rafter: str = "IPE450",
    column: str = "HEB240",
    purlin: str = "SHS140x140x5",
    grade: str = "S235",
    snow_depth: float = 1.0,
    snow_state: str = "wet",
    shape: str = "duopitch",
    session: dict | None = None,
    **roof_kwargs,
):
    """One window with live controls: scrub the snow, step the sections, re-solve.

    Sliders move within the same profile family as the section they start from,
    ordered by depth, so ``rafter="IPE450"`` steps through the IPE range. Drag
    the 3D panel to orbit it -- mplot3d handles that natively.

    The shape radio switches the profile; ticking "edit profile" hands the
    deflected-shape panel over to a vertex editor, and dragging a corner rebuilds
    the frame as a custom shape.

    ``session`` is the parameter dict, mutated in place. Every widget writes into
    it and every redraw reads out of it, so passing the MCP server's session here
    means a tool call and a slider are moving the same values -- the returned
    ``apply`` callable sets them from outside and moves the handles to match.

    Every distinct combination is solved once and cached, so going back to a
    setting you have already tried is instant.
    """
    from matplotlib.widgets import CheckButtons, PolygonSelector, RadioButtons, Slider

    from . import loads, shapes
    from .model import roof as build_roof

    S = session if session is not None else {}
    case = roof_kwargs.pop("snow_case", "balanced")
    for key, value in (
        ("span_m", span), ("length_m", length), ("pitch_deg", pitch_deg),
        ("shape", shape), ("rafter", rafter), ("column", column),
        ("purlin", purlin), ("grade", grade), ("snow_depth_m", snow_depth),
        ("snow_state", snow_state), ("snow_kn_m2", None), ("case", case),
        ("eaves_height_m", roof_kwargs.pop("eaves_height", 3.0)),
        ("frame_spacing_m", roof_kwargs.pop("frame_spacing", 5.0)),
        ("purlin_spacing_m", roof_kwargs.pop("purlin_spacing", 1.5)),
        ("points", None),
    ):
        S.setdefault(key, value)

    states = list(loads.SNOW_DENSITY)

    def profile() -> "shapes.Frame":
        if S["points"] is not None:
            return shapes.from_points(S["points"])
        return shapes.frame(S["shape"], S["span_m"], S["pitch_deg"],
                            S["eaves_height_m"])

    ladders = {role: _ladder(S[role]) for role in ("rafter", "column", "purlin")}

    fig = plt.figure(figsize=(15, 9.5))
    axes = _layout(fig, controls=True)
    fig.colorbar(plt.cm.ScalarMappable(cmap=UTIL_CMAP, norm=UTIL_NORM),
                 ax=axes[0], shrink=0.6, pad=0.12, label=_L("utilisation"))

    cache: dict[tuple, tuple] = {}

    def solve():
        """Solve whatever the session currently says. Cached on the parameters."""
        fr = profile()
        key = (fr.shape, fr.points, S["case"], S["grade"],
               round(S["snow_depth_m"], 3), S["snow_state"], S["snow_kn_m2"],
               S["rafter"], S["column"], S["purlin"],
               S["span_m"], S["length_m"], S["frame_spacing_m"],
               S["purlin_spacing_m"])
        if key not in cache:
            snow = S["snow_kn_m2"]
            if snow is None:
                # The reference load at the profile's nominal pitch; each slope's
                # own mu is applied inside the model.
                snow = loads.mu1(fr.pitch_deg) * loads.snow_from_depth(
                    S["snow_depth_m"], S["snow_state"])
            case = S["case"]
            if case not in loads.ARRANGEMENTS.get(fr.shape, ()):
                case = "balanced"  # the shape changed under it
                S["case"] = case
            roof = build_roof(span=S["span_m"], length=S["length_m"],
                              pitch_deg=S["pitch_deg"], profile=fr,
                              rafter=S["rafter"], column=S["column"],
                              purlin=S["purlin"], grade=S["grade"],
                              snow_kn_m2=snow, snow_case=case,
                              frame_spacing=S["frame_spacing_m"],
                              purlin_spacing=S["purlin_spacing_m"],
                              eaves_height=S["eaves_height_m"], **roof_kwargs)
            results = roof.solve()
            cache[key] = (roof, results, roof.check(results))
        return cache[key]

    # -- controls -------------------------------------------------------------
    ax_depth = fig.add_axes([0.13, 0.115, 0.28, 0.025])
    s_depth = Slider(ax_depth, _L("snow_depth"), 0.0, 3.0,
                     valinit=S["snow_depth_m"], valstep=0.05, color="#90caf9")

    ax_state = fig.add_axes([0.46, 0.02, 0.10, 0.13])
    ax_state.set_title(_L("snow_state"), fontsize=9)
    # Radio labels are translated; map the label back to the identifier the
    # load model expects.
    state_labels = {i18n.snow_term(st, LANG): st for st in states}
    r_state = RadioButtons(ax_state, list(state_labels),
                           active=states.index(S["snow_state"]))

    ax_shape = fig.add_axes([0.005, 0.01, 0.11, 0.16])
    ax_shape.set_title(_L("shape"), fontsize=9)
    shape_labels = {i18n.shape_term(sh, LANG): sh for sh in shapes.SHAPES}
    r_shape = RadioButtons(ax_shape, list(shape_labels),
                           active=list(shapes.SHAPES).index(S["shape"]))
    for label in r_shape.labels:
        label.set_fontsize(8)

    ax_edit = fig.add_axes([0.125, 0.055, 0.10, 0.055])
    c_edit = CheckButtons(ax_edit, [_L("edit_profile")], [False])

    sliders = {}
    for i, role in enumerate(("rafter", "column", "purlin")):
        names, idx = ladders[role]
        ax = fig.add_axes([0.66, 0.115 - i * 0.042, 0.28, 0.022])
        sliders[role] = Slider(ax, i18n.role(role, LANG), 0, len(names) - 1,
                               valinit=idx, valstep=1, color="#a5d6a7")
        sliders[role].valtext.set_text(names[idx])

    # While a value is being echoed into a widget, that widget's own callback
    # must not write it back -- set_val and set_active both fire them.
    echoing = {"flag": False}

    # -- the profile editor ---------------------------------------------------
    # ponytail: the editor borrows the deflected-shape panel rather than adding
    # a fifth one. _paint() clears its axes, so the two cannot share a redraw.
    editor = {"selector": None}
    SNAP = 0.25  # metres

    def editing() -> bool:
        return bool(c_edit.get_status()[0])

    def on_edit(verts) -> None:
        """A vertex moved: rebuild the profile, or refuse if it is not a roof."""
        pts = sorted(((round(x / SNAP) * SNAP, z) for x, z in verts
                      if z > 1e-6), key=lambda pt: pt[0])
        try:
            shapes.validate(pts)
        except ValueError as exc:
            fig.suptitle(f"{_L('invalid_profile')}: {exc}", fontsize=11,
                         color="#c62828")
            fig.canvas.draw_idle()
            return
        S["points"] = pts
        S["shape"] = "custom"
        draw_editor()
        redraw(keep_editor=True)

    def draw_editor() -> None:
        ax = axes[1]
        ax.clear()
        fr = profile()
        pts = fr.points
        ax.plot([x for x, _ in pts], [z for _, z in pts], color="#37474f", lw=2)
        for seg in fr.segments:
            if seg.role == "column":
                ax.plot([seg.x0, seg.x1], [seg.z0, seg.z1], color="#90a4ae", lw=1.5)
        ax.set_xlim(-1.0, S["span_m"] + 1.0)
        ax.set_ylim(0.0, fr.apex_height * 1.35)
        ax.set_aspect("equal")
        ax.set_title(f"{_L('edit_profile')} -- {i18n.shape_term(fr.shape, LANG)}",
                     fontsize=10)
        ax.grid(alpha=0.3)
        sel = PolygonSelector(ax, on_edit, useblit=False,
                              props=dict(color="#1565c0", lw=1.5))
        sel.verts = [(pts[0][0], 0.0), *pts, (pts[-1][0], 0.0)]
        editor["selector"] = sel

    def redraw(_=None, keep_editor: bool = False):
        roof, results, checks = solve()
        worst = _paint(axes, roof, results, checks)
        if keep_editor or editing():
            draw_editor()
        defl = roof.deflection(results)
        fr = profile()
        warning = f"   |   {_L('mu_approximate')}" if fr.mu_is_approximate else ""
        snow_note = (f"{S['snow_kn_m2']:.2f} kN/m$^2$" if S["snow_kn_m2"] is not None
                     else f"{S['snow_depth_m']:.2f} m, "
                          f"{i18n.snow_term(S['snow_state'], LANG)}")
        fig.suptitle(
            f"{i18n.shape_term(fr.shape, LANG)} {S['span_m']:.0f} x "
            f"{S['length_m']:.0f} {_L('roof_at')} {S['pitch_deg']:.0f}deg, "
            f"{S['grade']}   |   {_L('snow')} {snow_note}\n"
            f"{_headline(roof, checks, defl, worst)}{warning}", fontsize=11)
        fig.canvas.draw_idle()
        return roof, results, checks

    # -- widgets write into the session, never the other way round ------------
    def on_depth(val) -> None:
        if echoing["flag"]:
            return
        S["snow_depth_m"] = float(val)
        S["snow_kn_m2"] = None  # a depth means the depth is what you now mean
        deferred()

    def on_state(label) -> None:
        if echoing["flag"]:
            return
        S["snow_state"] = state_labels[label]
        S["snow_kn_m2"] = None
        redraw()

    def on_shape(label) -> None:
        if echoing["flag"]:
            return
        S["shape"] = shape_labels[label]
        S["points"] = None  # a preset replaces whatever was drawn
        redraw()

    def on_section(_=None) -> None:
        for role, slider in sliders.items():
            names, _idx = ladders[role]
            name = names[int(slider.val)]
            slider.valtext.set_text(name)
            if not echoing["flag"]:
                S[role] = name
        if not echoing["flag"]:
            deferred()

    def on_edit_toggled(_label) -> None:
        if not editing():
            editor["selector"] = None
        redraw()

    # Re-solving on every step of a drag would stutter, so while the mouse is
    # down just update the labels and defer the solve to the release. A click
    # on the track, or a programmatic set_val, redraws straight away.
    all_sliders = [s_depth, *sliders.values()]
    dirty = {"flag": False}

    def deferred() -> None:
        if any(s.drag_active for s in all_sliders):
            dirty["flag"] = True
            fig.canvas.draw_idle()
        else:
            redraw()

    def on_release(event) -> None:
        if dirty["flag"]:
            dirty["flag"] = False
            redraw()

    def set_section(role: str, name: str) -> None:
        """Move a section slider, rebuilding its ladder if the family changed."""
        from .sections import get_section

        names, idx = ladders[role]
        canonical = get_section(name).name
        if canonical not in names:
            names, idx = _ladder(canonical)
            ladders[role] = (names, idx)
            slider = sliders[role]
            slider.valmax = len(names) - 1
            slider.ax.set_xlim(slider.valmin, slider.valmax)
        else:
            idx = names.index(canonical)
        sliders[role].set_val(idx)
        sliders[role].valtext.set_text(names[idx])

    def apply(params: dict):
        """Set parameters from outside and move the handles to match.

        Returns the solved (roof, results, checks). Must be called on the thread
        running the GUI event loop -- everything here touches widgets.
        """
        echoing["flag"] = True
        try:
            # points last: a shape change clears them, and an explicit polyline
            # must win over that.
            ordered = sorted(params.items(), key=lambda kv: kv[0] == "points")
            for key, value in ordered:
                if key not in SESSION_KEYS or (value is None and key != "points"):
                    continue
                S[key] = value
                if key == "snow_depth_m":
                    s_depth.set_val(value)
                elif key == "snow_state":
                    r_state.set_active(states.index(value))
                elif key == "shape":
                    if value in shapes.SHAPES:
                        r_shape.set_active(list(shapes.SHAPES).index(value))
                        S["points"] = None
                    # "custom" has no radio entry: the radio keeps naming the
                    # preset whose mu a hand-drawn profile borrows.
                elif key in ("rafter", "column", "purlin"):
                    set_section(key, value)
            if "snow_kn_m2" in params and params["snow_kn_m2"] is not None:
                S["snow_kn_m2"] = params["snow_kn_m2"]
        finally:
            echoing["flag"] = False
        return redraw()

    s_depth.on_changed(on_depth)
    for role in sliders:
        sliders[role].on_changed(on_section)
    r_state.on_clicked(on_state)
    r_shape.on_clicked(on_shape)
    c_edit.on_clicked(on_edit_toggled)
    fig.canvas.mpl_connect("button_release_event", on_release)

    # Keep references alive; matplotlib drops widgets that are only local.
    fig._ms_widgets = {"depth": s_depth, "state": r_state, "shape": r_shape,
                       "edit": c_edit, "sections": sliders, "editor": editor,
                       "profile": profile, "session": S, "apply": apply}
    redraw()
    return fig
