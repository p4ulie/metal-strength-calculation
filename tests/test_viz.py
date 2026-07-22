"""Charts: headless by default, windows on request.

The default must stay Agg -- the MCP server and CI have no display, and a
backend switch leaking out of a test would break every later one, so the
fixture below always restores it.
"""

import matplotlib
import pytest

from metal_strength import viz
from metal_strength.model import pitched_roof, single_beam


@pytest.fixture
def restore_backend():
    """Undo any backend switch and close stray figures."""
    before = matplotlib.get_backend()
    was = viz._INTERACTIVE
    yield
    import matplotlib.pyplot as plt

    plt.close("all")
    matplotlib.use(before, force=True)
    viz._INTERACTIVE = was


@pytest.fixture(scope="module")
def beam():
    b = single_beam(6.0, "IPE200", udl_kn_m=5.0)
    r = b.solve()
    return b, r, b.check(r)


def test_default_backend_is_headless():
    assert matplotlib.get_backend().lower() == "agg"
    assert viz._INTERACTIVE is False


def test_interactive_disabled_is_a_noop(restore_backend):
    assert viz.interactive(False) is None
    assert viz._INTERACTIVE is False


def test_interactive_switches_backend_or_reports_none(restore_backend):
    backend = viz.interactive()
    if backend is None:
        pytest.skip("no GUI toolkit installed on this machine")
    assert backend in viz._GUI_BACKENDS
    assert matplotlib.get_backend().lower() == backend.lower()
    assert viz._INTERACTIVE is True


def test_show_is_a_noop_when_headless():
    viz.show()  # must not raise or block


def test_figures_are_closed_when_headless(beam, tmp_path):
    import matplotlib.pyplot as plt

    plt.close("all")
    b, r, checks = beam
    viz.force_diagrams(r, 4, tmp_path / "f.png")
    viz.deflected_shape(b, r, tmp_path / "d.png")
    assert plt.get_fignums() == [], "headless runs must not leak figures"


def test_figures_are_kept_open_for_display(beam, tmp_path, restore_backend):
    import matplotlib.pyplot as plt

    if viz.interactive() is None:
        pytest.skip("no GUI toolkit installed on this machine")
    plt.close("all")
    b, r, checks = beam
    viz.force_diagrams(r, 4, tmp_path / "f.png")
    viz.deflected_shape(b, r, tmp_path / "d.png")
    assert len(plt.get_fignums()) == 2, "show() needs the figures still open"


def test_charts_are_written_either_way(beam, tmp_path, restore_backend):
    """Switching to a window backend must not stop the PNGs being saved."""
    b, r, checks = beam
    headless = viz.force_diagrams(r, 4, tmp_path / "headless.png")
    if viz.interactive() is None:
        pytest.skip("no GUI toolkit installed on this machine")
    windowed = viz.force_diagrams(r, 4, tmp_path / "windowed.png")
    for p in (headless, windowed):
        assert p.exists() and p.stat().st_size > 10_000


def test_every_chart_type_renders(tmp_path):
    roof = pitched_roof(span=12.0, length=15.0, pitch_deg=20.0, snow_kn_m2=2.0,
                        rafter="IPE450", column="HEB240", purlin="SHS140x140x5")
    r = roof.solve()
    checks = roof.check(r)
    paths = [
        viz.utilisation_3d(roof, checks, tmp_path / "u3d.png"),
        viz.utilisation_bars(checks, tmp_path / "bars.png"),
        viz.deflected_shape(roof, r, tmp_path / "defl.png"),
        viz.force_diagrams(r, 0, tmp_path / "forces.png"),
        viz.snow_cases(2.0, 20.0, tmp_path / "snow.png"),
    ]
    for p in paths:
        assert p.exists() and p.stat().st_size > 10_000, p


def test_chart_directories_are_created(tmp_path, beam):
    b, r, checks = beam
    nested = tmp_path / "a" / "b" / "c" / "chart.png"
    assert viz.force_diagrams(r, 0, nested).exists()


def test_cli_show_opens_one_window_for_a_beam(monkeypatch, tmp_path):
    """--show must run end to end without blocking, and open exactly one figure."""
    from metal_strength import cli

    opened, shown = [], []
    monkeypatch.setattr(viz, "interactive", lambda *a, **k: "FakeAgg")
    monkeypatch.setattr(viz, "show", lambda: shown.append(True))
    monkeypatch.setattr(viz, "panel", lambda *a, **k: opened.append("panel"))
    monkeypatch.setattr(viz, "dashboard", lambda **k: opened.append("dashboard"))

    rc = cli.main(["beam", "--span", "6", "--section", "IPE200", "--udl", "5",
                   "--show", "--out", str(tmp_path)])
    assert rc == 0
    assert opened == ["panel"], "a beam gets the static panel, not the dashboard"
    assert shown == [True]
    assert len(list(tmp_path.glob("*.png"))) == 4  # --out still writes them


def test_cli_show_opens_the_dashboard_for_a_roof(monkeypatch):
    """A roof is parametric, so --show gets the live dashboard."""
    from metal_strength import cli

    opened = {}
    monkeypatch.setattr(viz, "interactive", lambda *a, **k: "FakeAgg")
    monkeypatch.setattr(viz, "show", lambda: None)
    monkeypatch.setattr(viz, "panel", lambda *a, **k: opened.setdefault("panel", True))
    monkeypatch.setattr(viz, "dashboard", lambda **k: opened.update(dash=k))

    rc = cli.main(["roof", "--span", "12", "--length", "20", "--pitch", "20",
                   "--snow-depth", "1.0", "--snow-state", "wet",
                   "--rafter", "IPE450", "--show"])
    assert rc == 0
    assert "panel" not in opened
    # The dashboard must receive the parameters it needs to rebuild the roof.
    assert opened["dash"]["span"] == 12.0
    assert opened["dash"]["rafter"] == "IPE450"
    assert opened["dash"]["snow_depth"] == 1.0
    assert opened["dash"]["snow_state"] == "wet"


def test_cli_without_show_does_not_open_windows(monkeypatch, tmp_path):
    from metal_strength import cli

    called = []
    monkeypatch.setattr(viz, "interactive", lambda *a, **k: called.append(True))
    monkeypatch.setattr(viz, "show", lambda: called.append("show"))
    cli.main(["beam", "--span", "6", "--udl", "5", "--out", str(tmp_path)])
    assert called == [], "no --show means no backend switch and no windows"


# --- one window, four panels ------------------------------------------------


def test_panel_is_a_single_figure_with_all_four_charts(beam):
    import matplotlib.pyplot as plt

    plt.close("all")
    b, r, checks = beam
    fig = viz.panel(b, r, checks, "test")
    try:
        assert len(plt.get_fignums()) == 1, "must be one window, not four"
        # 3D + ranking + deflected + three stacked force panels, plus a colourbar.
        assert len(fig.axes) >= 6
        assert any(hasattr(ax, "get_zlim") for ax in fig.axes), "no 3D panel"
        assert "PASSES" in fig._suptitle.get_text()
    finally:
        plt.close(fig)


def test_dashboard_builds_with_live_controls():
    import matplotlib.pyplot as plt

    plt.close("all")
    fig = viz.dashboard(span=10.0, length=10.0, pitch_deg=20.0, rafter="IPE300",
                        column="HEB200", purlin="SHS100x100x5",
                        snow_depth=1.0, snow_state="settled")
    try:
        w = fig._ms_widgets
        depth, state, sliders = w["depth"], w["state"], w["sections"]
        assert set(sliders) == {"rafter", "column", "purlin"}
        assert sliders["rafter"].valtext.get_text() == "IPE300"
        assert state.value_selected == "settled"
        assert depth.val == 1.0
    finally:
        plt.close(fig)


def test_dashboard_resolves_when_a_slider_moves():
    """The whole point: change an input, the structure is re-solved."""
    import matplotlib.pyplot as plt

    plt.close("all")
    fig = viz.dashboard(span=12.0, length=15.0, pitch_deg=20.0, rafter="IPE450",
                        column="HEB240", purlin="SHS140x140x5",
                        snow_depth=0.5, snow_state="settled")
    try:
        w = fig._ms_widgets
        depth, state, sliders = w["depth"], w["state"], w["sections"]
        headline = lambda: fig._suptitle.get_text()

        light = headline()
        depth.set_val(3.0)
        assert headline() != light, "more snow must change the result"
        assert "3.00 m" in headline()

        # A smaller rafter must make it worse, a larger one better.
        def utilisation() -> float:
            import re as _re
            return float(_re.search(r"strength (\d+\.\d+)", headline()).group(1))

        heavy = utilisation()
        sliders["rafter"].set_val(sliders["rafter"].val - 3)
        assert utilisation() > heavy
        assert sliders["rafter"].valtext.get_text() != "IPE450"
        sliders["rafter"].set_val(sliders["rafter"].val + 6)
        assert utilisation() < heavy

        # Snow state is the 4x lever.
        depth.set_val(1.0)
        state.set_active(list(__import__("metal_strength.loads",
                                         fromlist=["x"]).SNOW_DENSITY).index("fresh"))
        fresh = utilisation()
        state.set_active(list(__import__("metal_strength.loads",
                                         fromlist=["x"]).SNOW_DENSITY).index("wet"))
        assert utilisation() > fresh
    finally:
        plt.close(fig)


def test_dashboard_caches_solved_models():
    """Returning to a setting already tried must not re-solve."""
    import time

    import matplotlib.pyplot as plt

    plt.close("all")
    fig = viz.dashboard(span=12.0, length=15.0, pitch_deg=20.0,
                        snow_depth=1.0, snow_state="settled")
    try:
        depth = fig._ms_widgets["depth"]
        depth.set_val(2.0)  # cold
        t0 = time.perf_counter()
        depth.set_val(1.0)  # already solved at construction
        cached = time.perf_counter() - t0
        t0 = time.perf_counter()
        depth.set_val(2.55)  # never seen
        cold = time.perf_counter() - t0
        assert cached < cold, f"cached {cached:.3f}s should beat cold {cold:.3f}s"
    finally:
        plt.close(fig)


def test_section_ladder_is_ordered_and_finds_the_start():
    names, idx = viz._ladder("IPE450")
    assert names[idx] == "IPE450"
    assert all(n.startswith("IPE") for n in names)
    from metal_strength.sections import get_section
    depths = [get_section(n).h for n in names]
    assert depths == sorted(depths), "ladder must run small to large"

    # Hollow sections keep their own family.
    names, idx = viz._ladder("SHS140x140x5")
    assert names[idx] == "SHS140x5"
    assert all(n.startswith("SHS") for n in names)


def test_dashboard_shape_radio_reprofiles_the_roof():
    import matplotlib.pyplot as plt

    plt.close("all")
    fig = viz.dashboard(span=20.0, length=10.0, pitch_deg=20.0, rafter="IPE300",
                        column="HEB200", purlin="SHS100x100x5",
                        snow_depth=1.0, snow_state="settled")
    try:
        w = fig._ms_widgets
        assert w["profile"]().shape == "duopitch"
        from metal_strength import i18n
        w["shape"].set_active(list(__import__(
            "metal_strength.shapes", fromlist=["SHAPES"]).SHAPES).index("multispan"))
        assert w["profile"]().shape == "multispan"
        assert i18n.shape_term("multispan", "sk") == "viacloďová"
    finally:
        plt.close(fig)


def test_dashboard_editor_accepts_a_drag_and_refuses_nonsense():
    import matplotlib.pyplot as plt

    plt.close("all")
    fig = viz.dashboard(span=12.0, length=10.0, pitch_deg=20.0, rafter="IPE300",
                        column="HEB200", purlin="SHS100x100x5",
                        snow_depth=1.0, snow_state="settled")
    try:
        w = fig._ms_widgets
        w["edit"].set_active(0)  # tick "edit profile"
        selector = w["editor"]["selector"]
        assert selector is not None, "ticking the box must arm the vertex editor"

        # Drag the apex up: the polygon includes the two ground points.
        verts = list(selector.verts)
        moved = [(x, z + 1.0) if z == max(v[1] for v in verts) else (x, z)
                 for x, z in verts]
        selector.onselect(moved)
        assert w["profile"]().shape == "custom"
        assert w["profile"]().apex_height > 3.0

        # Dragging a vertex past its neighbour just reorders it -- the editor
        # sorts by x rather than complaining.
        selector.onselect([(0.0, 3.0), (8.0, 5.0), (2.0, 3.0), (12.0, 3.0)])
        assert [x for x, _ in w["profile"]().points] == [0.0, 2.0, 8.0, 12.0]

        # Two vertices landing on the same x cannot be a roof: refused, and the
        # profile that was there survives.
        before = w["profile"]().points
        selector.onselect([(0.0, 3.0), (6.0, 5.0), (6.1, 4.0), (12.0, 3.0)])
        assert w["profile"]().points == before
    finally:
        plt.close(fig)


def test_frames_are_drawn_as_collections_not_one_artist_per_member():
    """A few hundred separate line artists is what made the dashboard sluggish."""
    import matplotlib.pyplot as plt

    from metal_strength.model import roof

    con = roof(span=12.0, length=20.0, pitch_deg=20.0, rafter="IPE450",
               column="HEB240", purlin="SHS140x140x5", snow_kn_m2=1.92)
    results = con.solve()
    checks = con.check(results)
    assert len(con.spec.members) > 50, "need a frame big enough for this to matter"

    fig = plt.figure()
    try:
        ax = fig.add_subplot()
        viz._draw_deflected(ax, con, results)
        assert not ax.lines, "deflected shape should draw no individual lines"
        assert len(ax.collections) == 2  # undeformed and deformed

        ax3d = fig.add_subplot(projection="3d")
        viz._draw_utilisation_3d(ax3d, con, checks)
        assert not ax3d.lines
        assert len(ax3d.collections) == 1
    finally:
        plt.close(fig)
