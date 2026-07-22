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


def test_cli_show_flag_is_accepted(monkeypatch, tmp_path):
    """--show must run end to end without blocking on a window."""
    from metal_strength import cli

    shown = []
    monkeypatch.setattr(viz, "interactive", lambda *a, **k: "FakeAgg")
    monkeypatch.setattr(viz, "show", lambda: shown.append(True))
    rc = cli.main(["beam", "--span", "6", "--section", "IPE200", "--udl", "5",
                   "--show", "--out", str(tmp_path)])
    assert rc == 0
    assert shown == [True], "show() should have been called"
    assert list(tmp_path.glob("*.png"))


def test_cli_without_show_does_not_open_windows(monkeypatch, tmp_path):
    from metal_strength import cli

    called = []
    monkeypatch.setattr(viz, "interactive", lambda *a, **k: called.append(True))
    monkeypatch.setattr(viz, "show", lambda: called.append("show"))
    cli.main(["beam", "--span", "6", "--udl", "5", "--out", str(tmp_path)])
    assert called == [], "no --show means no backend switch and no windows"
