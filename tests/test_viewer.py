"""The pygame viewer -- optional, so every test skips cleanly without pygame.

The font fallback exists because some pygame builds (2.6.1 on Python 3.14)
ship no compiled SDL_ttf module, leaving a circular import between the
pure-Python pygame.font and pygame.sysfont. These tests pin that workaround.
"""

import os

import pytest

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

pygame = pytest.importorskip("pygame", reason="viewer is an optional extra")

from metal_strength.viewer import _Text, _colour, _project  # noqa: E402


@pytest.fixture(scope="module")
def display():
    pygame.init()
    surface = pygame.display.set_mode((320, 240))
    yield surface
    pygame.quit()


def test_text_renders_on_this_install(display):
    """Whatever font API this build provides, text must come out."""
    t = _Text(15)
    assert t.available, "no usable font backend found at all"
    assert t._mode in ("font", "freetype")
    surface = t.render("utilisation 0.90 PASS", (255, 255, 255))
    assert surface is not None
    w, h = surface.get_size()
    assert w > 50 and h > 5
    assert t.height > 0


def test_bold_text_renders(display):
    b = _Text(19, bold=True)
    assert b.render("PASS", (0, 255, 0)) is not None


def test_text_degrades_instead_of_crashing(display, monkeypatch):
    """With every font backend broken, the viewer draws without labels."""
    import builtins

    real_import = builtins.__import__

    def deny(name, *args, **kwargs):
        if name in ("pygame.font", "pygame._freetype"):
            raise ImportError(f"simulated: {name} unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)
    t = _Text(15)
    assert not t.available
    assert t.render("anything", (255, 255, 255)) is None  # must not raise
    assert t.height > 0  # layout still advances


def test_colour_ramp_runs_green_to_red():
    safe, at_limit, over = _colour(0.0), _colour(1.0), _colour(1.5)
    assert safe[1] > safe[0]  # green dominant
    assert over[0] > over[1]  # red dominant
    for c in (safe, at_limit, over):
        assert all(0 <= v <= 255 for v in c)
    # Clamped beyond the top of the ramp rather than overflowing.
    assert _colour(99.0) == _colour(1.5)


def test_projection_is_sane():
    import numpy as np

    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    screen = _project(pts, yaw=0.0, pitch=0.0, zoom=100.0, size=(800, 600))
    assert screen.shape == (3, 2)
    # Origin lands at the centre of the window.
    assert screen[0] == pytest.approx([400.0, 300.0])
    # +x goes right, +z goes up (screen y decreases).
    assert screen[1][0] > screen[0][0]
    assert screen[2][1] < screen[0][1]


def test_viewer_loop_runs_and_exits(display):
    """Drive the real loop for a few frames, then quit."""
    import threading
    import time

    from metal_strength import viewer

    def quit_soon():
        time.sleep(8)
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    threading.Thread(target=quit_soon, daemon=True).start()
    rc = viewer.run(10.0, 10.0, 20.0, "IPE300", "HEB200", "SHS100x100x5",
                    0.5, "settled")
    assert rc == 0
