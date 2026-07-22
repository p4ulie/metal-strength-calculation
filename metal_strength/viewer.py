"""Interactive 3D roof viewer (pygame). Optional -- everything else works headless.

    python -m metal_strength.viewer --span 12 --length 20 --pitch 20

Drag to orbit, scroll to zoom, left/right arrows change the snow depth and the
model is re-solved and re-coloured live. Holds no engineering logic of its own:
it calls the same solver and the same Eurocode checks as everything else.
"""

from __future__ import annotations

import argparse
import math
import sys

import numpy as np

from .model import pitched_roof


def _colour(utilisation: float) -> tuple[int, int, int]:
    """Green -> amber -> red, matching viz.UTIL_CMAP closely enough."""
    u = min(max(utilisation, 0.0), 1.5) / 1.5
    if u < 0.5:
        t = u / 0.5
        return (int(46 + t * (253 - 46)), int(125 + t * (216 - 125)), int(50 + t * (53 - 50)))
    t = (u - 0.5) / 0.5
    return (int(253 - t * (253 - 198)), int(216 - t * 216), int(53 - t * (53 - 40)))


def _project(pts: np.ndarray, yaw: float, pitch: float, zoom: float,
             size: tuple[int, int]) -> np.ndarray:
    """Rotate about Z then X, drop to screen coordinates."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    rot_z = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    rot_x = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    p = pts @ rot_z.T @ rot_x.T
    w, h = size
    return np.column_stack([w / 2 + p[:, 0] * zoom, h / 2 - p[:, 2] * zoom])


def run(span: float, length: float, pitch_deg: float, rafter: str, column: str,
        purlin: str, snow_depth: float, snow_state: str) -> int:
    try:
        import pygame
    except ImportError:
        print("pygame is not installed. Install the optional extra:\n"
              "    uv pip install 'metal-strength[viewer]'\n"
              "Everything else (CLI, MCP, charts) works without it.", file=sys.stderr)
        return 1

    from . import loads

    pygame.init()
    size = (1100, 720)
    screen = pygame.display.set_mode(size, pygame.RESIZABLE)
    pygame.display.set_caption("metal-strength roof viewer")
    font = pygame.font.SysFont("monospace", 15)
    big = pygame.font.SysFont("monospace", 19, bold=True)
    clock = pygame.time.Clock()

    yaw, pitch_cam, zoom = math.radians(-55), math.radians(22), 34.0
    dragging = False
    depth = snow_depth
    cache: dict[float, tuple] = {}

    def model_for(d: float):
        key = round(d, 2)
        if key not in cache:
            sk = loads.snow_from_depth(key, snow_state)
            s = loads.roof_snow_load(sk, pitch_deg)[0].left
            roof = pitched_roof(span=span, length=length, pitch_deg=pitch_deg,
                                rafter=rafter, column=column, purlin=purlin,
                                snow_kn_m2=s)
            results = roof.solve()
            checks = roof.check(results)
            cache[key] = (roof, results, checks, s)
        return cache[key]

    running = True
    while running:
        roof, results, checks, snow = model_for(depth)
        nodes = np.array([[n.x, n.y, n.z] for n in roof.structure.nodes]) / 1000.0
        nodes = nodes - nodes.mean(0)
        utils = [c.utilisation for c in checks]
        worst_i = int(np.argmax(utils))

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.VIDEORESIZE:
                size = (ev.w, ev.h)
                screen = pygame.display.set_mode(size, pygame.RESIZABLE)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                dragging = True
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                dragging = False
            elif ev.type == pygame.MOUSEMOTION and dragging:
                yaw -= ev.rel[0] * 0.01
                pitch_cam = min(max(pitch_cam + ev.rel[1] * 0.01, -1.5), 1.5)
            elif ev.type == pygame.MOUSEWHEEL:
                zoom = min(max(zoom * (1.1 if ev.y > 0 else 0.9), 4.0), 400.0)
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_RIGHT:
                    depth = min(depth + 0.1, 4.0)
                elif ev.key == pygame.K_LEFT:
                    depth = max(depth - 0.1, 0.0)
                elif ev.key == pygame.K_d:
                    cache.clear()

        screen.fill((22, 26, 32))
        pts = _project(nodes, yaw, pitch_cam, zoom, size)
        order = np.argsort([-(nodes[m.i, 1] + nodes[m.j, 1])
                            for m in roof.structure.members])
        for e in order:
            m = roof.structure.members[e]
            width = 5 if e == worst_i else (3 if utils[e] > 1 else 2)
            pygame.draw.line(screen, _colour(utils[e]),
                             pts[m.i], pts[m.j], width)

        ok = all(c.ok for c in checks)
        lines = [
            (big, f"{depth:.1f} m of {snow_state} snow  ->  {snow:.2f} kN/m2 on roof",
             (235, 235, 235)),
            (font, f"{span:.0f} x {length:.0f} m, {pitch_deg:.0f} deg", (170, 178, 190)),
            (font, f"rafter {rafter}   column {column}   purlin {purlin}",
             (170, 178, 190)),
            (big, f"worst utilisation {max(utils):.2f}  {'PASS' if ok else 'FAIL'}",
             (120, 220, 120) if ok else (240, 90, 90)),
            (font, f"{checks[worst_i].section}: {checks[worst_i].governing.name}",
             (200, 200, 200)),
            (font, f"peak deflection {abs(results.displacements[:, 2]).max():.0f} mm",
             (170, 178, 190)),
            (font, "drag orbit | wheel zoom | left/right arrows snow depth | esc quit",
             (120, 128, 140)),
        ]
        y = 12
        for f, text, colour in lines:
            screen.blit(f.render(text, True, colour), (14, y))
            y += f.get_height() + 4

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--span", type=float, default=12.0)
    p.add_argument("--length", type=float, default=20.0)
    p.add_argument("--pitch", type=float, default=20.0)
    p.add_argument("--rafter", default="IPE450")
    p.add_argument("--column", default="HEB240")
    p.add_argument("--purlin", default="SHS140x140x5")
    p.add_argument("--snow-depth", type=float, default=1.0)
    p.add_argument("--snow-state", default="wet",
                   choices=["fresh", "settled", "old", "wet"])
    a = p.parse_args(argv)
    return run(a.span, a.length, a.pitch, a.rafter, a.column, a.purlin,
               a.snow_depth, a.snow_state)


if __name__ == "__main__":
    raise SystemExit(main())
