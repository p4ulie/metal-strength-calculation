"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import bom as bom_mod
from . import design as design_mod
from . import i18n, loads, shapes, viz
from .model import roof as build_roof, single_beam
from .sections import get_section, list_sections


def _materials(construction, a) -> None:
    """Print the material list, and the cost when a price list is in play."""
    prices = None
    if getattr(a, "prices", None) or getattr(a, "cost", False):
        prices = bom_mod.Prices.load(getattr(a, "prices", None),
                                     country=a.country, fx=getattr(a, "fx", None))
    b = bom_mod.bill_of_materials(construction, prices, waste=a.waste / 100.0)
    print(f"\n{i18n.t('material_list', a.lang)}")
    print(bom_mod.format_bom(b, a.lang))


def _snow_for(a, parser) -> float:
    """Roof snow load in kN/m2 from either --snow or --snow-depth."""
    if a.snow is not None:
        return a.snow
    if a.snow_depth is None:
        parser.error("give either --snow or --snow-depth")
    sk = loads.snow_from_depth(a.snow_depth, a.snow_state)
    return loads.roof_snow_load(sk, a.pitch)[0].left


def _report(roof, out: Path | None, prefix: str, show: bool = False,
            live: dict | None = None, mcp_port: int | None = 8000,
            mcp_host: str = "127.0.0.1") -> None:
    """Print the verdict; optionally write PNGs and open one interactive window.

    ``live``, when given, is the set of roof parameters the dashboard needs to
    rebuild the structure as its sliders move.
    """
    viz.LANG = getattr(roof, "_lang", "en")
    backend = viz.interactive() if show else None
    if show and backend is None:
        print("note: no GUI toolkit found, charts will only be written to disk.\n"
              "      install one, e.g.  uv pip install pyqt6", file=sys.stderr)

    results = roof.solve()
    checks = roof.check(results)
    ranked = sorted(checks, key=lambda c: -c.utilisation)
    worst = ranked[0]

    defl = roof.deflection(results)
    worst_index = checks.index(worst)

    lang = getattr(roof, "_lang", "en")
    print(f"\n{len(roof.spec.members)} {i18n.t('members', lang)}, "
          f"{len(roof.spec.nodes)} nodes")
    print(f"\n{i18n.t('worst_members', lang)}:")
    for c in ranked[:5]:
        flag = "OK  " if c.ok else "FAIL"
        label = i18n.member_label(c.section, lang)
        print(f"  {flag} {c.utilisation:5.2f}  {label:<24s} {c.governing.name}")

    print()
    print(worst.report())
    print(f"\nserviceability:\n{defl}")

    if getattr(roof.profile, "mu_is_approximate", False):
        print(f"\n! {i18n.t('mu_approximate', lang)}")

    ok = all(c.ok for c in checks) and defl.ok
    print(f"\n=> {i18n.verdict(ok, lang)} "
          f"({i18n.t('utilisation', lang)} {worst.utilisation:.2f}, "
          f"{i18n.t('deflection', lang)} {defl.utilisation:.2f})")

    if out:
        # Separate PNGs, which is what you want for a report.
        paths = [
            viz.utilisation_3d(roof, checks, out / f"{prefix}_utilisation.png"),
            viz.utilisation_bars(checks, out / f"{prefix}_ranking.png"),
            viz.deflected_shape(roof, results, out / f"{prefix}_deflection.png"),
            viz.force_diagrams(results, worst_index, out / f"{prefix}_forces.png",
                               f"Governing member: {worst.section}"),
        ]
        print("\ncharts:")
        for p in paths:
            print(f"  {p}")

    if backend:
        # One window with all four panels. For a roof it also gets live
        # sliders; drag the 3D panel to orbit it.
        if live:
            from . import mcp_server as srv

            # One session: the window's widgets and the MCP tools move the same
            # values. The server is not opt-in -- if there is a window to drive,
            # it is worth being able to drive it.
            srv._session.update(_session_from_live(live))
            fig = viz.dashboard(session=srv._session, **live)
            print(f"\ndashboard open ({backend}). Drag the sliders to re-solve, "
                  "drag the 3D panel to orbit. Close the window to exit.")
            if mcp_port is not None:
                url = _serve_dashboard(fig, mcp_host, mcp_port)
                print(f"MCP on {url} -- tune_roof drives this window.")
        else:
            viz.panel(roof, results, checks, title=prefix)
            print(f"\nchart window open ({backend}); close it to exit.")
        viz.show()


def _free_port(preferred: int, host: str) -> int:
    """``preferred`` if it is free, otherwise whatever the OS hands out.

    ponytail: the socket closes before uvicorn binds, so a racing process could
    still take it. Serving one person on a loopback address, that is fine.
    """
    import socket

    with socket.socket() as sock:
        try:
            sock.bind((host, preferred))
        except OSError:
            sock.bind((host, 0))
        return sock.getsockname()[1]


def _serve_dashboard(fig, host: str, port: int) -> str:
    """Run MCP beside an open dashboard, both driving its session. Returns the URL.

    matplotlib owns the main thread because its GUI must, so a tool call posts
    its change to a queue and waits; a canvas timer applies it on the main
    thread and replies. Nothing touches a widget off the GUI thread.
    """
    import queue
    import threading

    from . import mcp_server as srv

    apply_on_gui = fig._ms_widgets["apply"]
    pending: queue.Queue = queue.Queue()

    class _Applier:
        session = fig._ms_widgets["session"]

        def __call__(self, params: dict):
            reply: queue.Queue = queue.Queue(maxsize=1)
            pending.put((params, reply))
            try:
                ok, payload = reply.get(timeout=30)
            except queue.Empty:
                raise TimeoutError("the window did not respond; is it still open?")
            if not ok:
                raise payload
            return payload

    def pump() -> None:
        while True:
            try:
                params, reply = pending.get_nowait()
            except queue.Empty:
                return
            try:
                reply.put((True, apply_on_gui(params)))
            except Exception as exc:  # noqa: BLE001 - hand it to the caller
                reply.put((False, exc))

    srv.attach_window(_Applier())
    timer = fig.canvas.new_timer(150)
    timer.add_callback(pump)
    timer.start()
    fig._ms_timer = timer  # a dropped timer stops firing

    port = _free_port(port, host)
    srv.mcp.settings.host, srv.mcp.settings.port = host, port
    threading.Thread(target=lambda: srv.mcp.run(transport="streamable-http"),
                     daemon=True).start()
    return f"http://{host}:{port}/mcp"


def _serve(a) -> int:
    """Headless MCP over stdio, which is how an MCP client launches this."""
    from . import mcp_server as srv

    srv.mcp.run()
    return 0


# The dashboard's argument names and the MCP session's differ (one is a CLI,
# the other a tool schema). One map, in one place.
_LIVE_TO_SESSION = {
    "span": "span_m", "length": "length_m", "pitch_deg": "pitch_deg",
    "eaves_height": "eaves_height_m", "frame_spacing": "frame_spacing_m",
    "purlin_spacing": "purlin_spacing_m", "rafter": "rafter", "column": "column",
    "purlin": "purlin", "grade": "grade", "snow_depth": "snow_depth_m",
    "snow_state": "snow_state", "snow_case": "case", "shape": "shape",
}


def _session_from_live(live: dict) -> dict:
    """What the command line asked for, in the session's key names."""
    return {_LIVE_TO_SESSION[k]: v for k, v in live.items() if k in _LIVE_TO_SESSION}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="metal-strength",
        description="Eurocode steel strength checks, from a single rod to a whole roof.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    snow = sub.add_parser("snow", help="snow load from a depth or a zone map")
    snow.add_argument("--depth", type=float, help="snow depth in metres")
    snow.add_argument("--state", default="settled", choices=sorted(loads.SNOW_DENSITY))
    snow.add_argument("--zone", type=float, help="zone number from the national map")
    snow.add_argument("--altitude", type=float, default=0.0)
    snow.add_argument("--region", default="central_east", choices=sorted(loads.REGIONS))
    snow.add_argument("--pitch", type=float, default=0.0)
    snow.add_argument("--exposure", default="normal", choices=sorted(loads.EXPOSURE))

    beam = sub.add_parser("beam", help="check a single beam or rod")
    beam.add_argument("--span", type=float, required=True, help="metres")
    beam.add_argument("--section", default="IPE200")
    beam.add_argument("--grade", default="S235")
    beam.add_argument("--udl", type=float, default=0.0, help="kN/m")
    beam.add_argument("--point", type=float, default=0.0, help="kN at midspan")
    beam.add_argument("--fixity", default="simple",
                      choices=["simple", "cantilever", "fixed", "propped"])
    beam.add_argument("--restrained", action="store_true",
                      help="compression flange held laterally (no LTB)")
    beam.add_argument("--out", type=Path)
    beam.add_argument("--show", action="store_true",
                      help="open the charts in windows as well as saving them")

    roof = sub.add_parser("roof", help="generate and check a whole 3D roof")
    roof.add_argument("--span", type=float, required=True, help="metres")
    roof.add_argument("--length", type=float, required=True, help="metres")
    roof.add_argument("--shape", default="duopitch", choices=list(shapes.SHAPES),
                      help="; ".join(f"{k}: {v}" for k, v in shapes.DESCRIPTIONS.items()
                                     if k in shapes.SHAPES))
    roof.add_argument("--pitch", type=float, default=20.0, help="degrees")
    roof.add_argument("--eaves-height", type=float, default=3.0)
    roof.add_argument("--frame-spacing", type=float, default=5.0)
    roof.add_argument("--purlin-spacing", type=float, default=1.5)
    roof.add_argument("--rafter", default="IPE300")
    roof.add_argument("--column", default="HEB200")
    roof.add_argument("--purlin", default="SHS100x100x5")
    roof.add_argument("--grade", default="S235")
    roof.add_argument("--snow-depth", type=float, help="metres of snow")
    roof.add_argument("--snow-state", default="settled", choices=sorted(loads.SNOW_DENSITY))
    roof.add_argument("--snow", type=float, help="roof snow load in kN/m2 directly")
    roof.add_argument("--case", default="balanced",
                      choices=sorted({c for cs in loads.ARRANGEMENTS.values() for c in cs}),
                      help="snow arrangement; which ones apply depends on --shape")
    roof.add_argument("--out", type=Path)
    roof.add_argument("--show", action="store_true",
                      help="open the charts in windows as well as saving them")

    design = sub.add_parser(
        "design", help="propose a construction that carries a given load")
    design.add_argument("--span", type=float, required=True, help="metres")
    design.add_argument("--length", type=float, required=True, help="metres")
    design.add_argument("--shape", default="duopitch", choices=list(shapes.SHAPES),
                        help="; ".join(f"{k}: {v}" for k, v in shapes.DESCRIPTIONS.items()
                                       if k in shapes.SHAPES))
    design.add_argument("--pitch", type=float, default=20.0, help="degrees")
    design.add_argument("--eaves-height", type=float, default=3.0)
    design.add_argument("--frame-spacing", type=float, default=5.0)
    design.add_argument("--purlin-spacing", type=float, default=1.5)
    design.add_argument("--grade", default="S235")
    design.add_argument("--snow-depth", type=float, help="metres of snow")
    design.add_argument("--snow-state", default="settled",
                        choices=sorted(loads.SNOW_DENSITY))
    design.add_argument("--snow", type=float, help="roof snow load in kN/m2 directly")
    design.add_argument("--target", type=float, default=1.0,
                        help="utilisation to design to; 0.85 leaves headroom")
    design.add_argument("--objective", default="mass", choices=["mass", "cost"])
    design.add_argument("--rafter-family", default="IPE",
                        choices=["IPE", "HEA", "HEB"])
    design.add_argument("--column-family", default="HEB",
                        choices=["HEB", "HEA", "IPE"])
    design.add_argument("--purlin-family", default="SHS",
                        choices=["SHS", "RHS", "IPE"])
    design.add_argument("--out", type=Path)
    design.add_argument("--show", action="store_true",
                        help="open the proposal in the interactive dashboard")

    for sub_p in (roof, design):
        sub_p.add_argument("--port", type=int, default=8000,
                           help="MCP port for the dashboard; taken automatically "
                                "when --show opens a window, next free port if busy")
        sub_p.add_argument("--host", default="127.0.0.1")
        sub_p.add_argument("--no-mcp", action="store_true",
                           help="open the window without serving it")

    for sub_p in (beam, roof, design):
        sub_p.add_argument("--lang", default="en", choices=list(i18n.LANGUAGES),
                           help="language for the material list and verdict")
        sub_p.add_argument("--bom", action="store_true", help="print the material list")
        sub_p.add_argument("--cost", action="store_true",
                           help="price the material list (implies --bom)")
        sub_p.add_argument("--prices", type=Path,
                           help="JSON price list to use instead of the shipped rates")
        sub_p.add_argument("--country", default="SK", choices=["SK", "CZ"],
                           help="sets the VAT rate and the display currency")
        sub_p.add_argument("--fx", type=float,
                           help="EUR per unit of the price list currency")
        sub_p.add_argument("--waste", type=float, default=0.0,
                           help="off-cut allowance in percent")

    sub.add_parser("serve", help="MCP over stdio, no window -- for an MCP client "
                                 "that launches this process itself")

    sect = sub.add_parser("sections", help="catalogue lookup")
    sect.add_argument("name", nargs="?", help="profile name; omit to list a family")
    sect.add_argument("--family", default=None)

    a = p.parse_args(argv)

    if a.cmd == "snow":
        if a.depth is not None:
            sk = loads.snow_from_depth(a.depth, a.state)
            print(f"{a.depth:.2f} m of {a.state} snow -> sk = {sk:.2f} kN/m2 "
                  f"(density {loads.SNOW_DENSITY[a.state]:.1f} kN/m3)")
        elif a.zone is not None:
            sk = loads.sk_from_zone(a.zone, a.altitude, a.region)
            print(f"zone {a.zone} at {a.altitude:.0f} m ({a.region}) -> "
                  f"sk = {sk:.2f} kN/m2   [EN 1991-1-3 Annex C]")
        else:
            p.error("give either --depth or --zone")
        print(f"\nroof loads, pitch {a.pitch:.0f}deg, {a.exposure} exposure "
              f"(mu1={loads.mu1(a.pitch):.2f}, Ce={loads.EXPOSURE[a.exposure]:.1f}):")
        for c in loads.roof_snow_load(sk, a.pitch, exposure=a.exposure):
            print(f"  {c.name:<14s} left {c.left:5.2f}  right {c.right:5.2f} kN/m2")
        return 0

    if a.cmd == "serve":
        return _serve(a)

    if a.cmd == "sections":
        if a.name:
            s = get_section(a.name)
            print(f"{s.name}  ({s.family})")
            for k, v, u in [
                ("A", s.A / 1e2, "cm2"), ("h", s.h, "mm"), ("b", s.b, "mm"),
                ("Iy", s.Iy / 1e4, "cm4"), ("Iz", s.Iz / 1e4, "cm4"),
                ("Wel,y", s.Wel_y / 1e3, "cm3"), ("Wpl,y", s.Wpl_y / 1e3, "cm3"),
                ("It", s.It / 1e4, "cm4"), ("Iw", s.Iw / 1e9, "1e3 cm6"),
                ("iy", s.iy, "mm"), ("iz", s.iz, "mm"),
                ("mass", s.mass_per_m, "kg/m"),
            ]:
                print(f"  {k:<7s} {v:10.4g} {u}")
        else:
            names = list_sections(a.family)
            print(f"{len(names)} profiles" + (f" in {a.family}" if a.family else ""))
            for i in range(0, len(names), 6):
                print("  " + "  ".join(f"{n:<16s}" for n in names[i : i + 6]))
        return 0

    if a.cmd == "beam":
        roof_obj = single_beam(a.span, a.section, a.grade, a.udl, a.point,
                               a.fixity, a.restrained)
        print(f"{a.section} {a.grade}, {a.span:.2f} m, {a.fixity}"
              + (f", UDL {a.udl} kN/m" if a.udl else "")
              + (f", point {a.point} kN" if a.point else "")
              + (", laterally restrained" if a.restrained else ""))
        roof_obj._lang = a.lang
        _report(roof_obj, a.out, "beam", a.show)
        if a.bom or a.cost:
            _materials(roof_obj, a)
        return 0

    if a.cmd == "design":
        snow = _snow_for(a, p)
        print(f"designing a {a.shape} {a.span} x {a.length} m roof at {a.pitch}deg, "
              f"{a.grade}, snow {snow:.2f} kN/m2, target utilisation {a.target}")
        prices = None
        if a.objective == "cost" or a.cost or a.prices:
            prices = bom_mod.Prices.load(a.prices, country=a.country, fx=a.fx)
        proposal = design_mod.propose(
            span=a.span, length=a.length, pitch_deg=a.pitch, snow_kn_m2=snow,
            grade=a.grade, target=a.target, objective=a.objective, prices=prices,
            families={"rafter": a.rafter_family, "column": a.column_family,
                      "purlin": a.purlin_family},
            eaves_height=a.eaves_height, frame_spacing=a.frame_spacing,
            purlin_spacing=a.purlin_spacing, shape=a.shape,
        )
        print()
        print(design_mod.format_proposal(proposal, a.lang))
        if not proposal.feasible:
            return 1
        if a.bom or a.cost or a.prices:
            _materials(proposal.construction, a)
        if a.out or a.show:
            proposal.construction._lang = a.lang
            _report(proposal.construction, a.out, "design", a.show,
                    mcp_port=None if a.no_mcp else a.port, mcp_host=a.host,
                    live=dict(
                span=a.span, length=a.length, pitch_deg=a.pitch,
                eaves_height=a.eaves_height, frame_spacing=a.frame_spacing,
                purlin_spacing=a.purlin_spacing, grade=a.grade,
                snow_depth=a.snow_depth if a.snow_depth is not None else 1.0,
                snow_state=a.snow_state, shape=a.shape, **proposal.sections))
        print(f"\n{i18n.t('disclaimer', a.lang)}")
        return 0

    snow_load = _snow_for(a, p)
    origin = (f"{a.snow:.2f} kN/m2 given directly" if a.snow is not None
              else f"{a.snow_depth:.2f} m {a.snow_state} snow -> {snow_load:.2f} kN/m2")

    print(f"{a.shape} roof {a.span} x {a.length} m at {a.pitch}deg; {origin}; "
          f"case {a.case}")
    roof_obj = build_roof(
        span=a.span, length=a.length, pitch_deg=a.pitch, shape=a.shape,
        eaves_height=a.eaves_height,
        frame_spacing=a.frame_spacing, purlin_spacing=a.purlin_spacing,
        rafter=a.rafter, column=a.column, purlin=a.purlin, grade=a.grade,
        snow_kn_m2=snow_load, snow_case=a.case,
    )
    roof_obj._lang = a.lang
    _report(roof_obj, a.out, "roof", a.show,
            mcp_port=None if a.no_mcp else a.port, mcp_host=a.host, live=dict(
        span=a.span, length=a.length, pitch_deg=a.pitch, eaves_height=a.eaves_height,
        frame_spacing=a.frame_spacing, purlin_spacing=a.purlin_spacing,
        rafter=a.rafter, column=a.column, purlin=a.purlin, grade=a.grade,
        snow_depth=a.snow_depth if a.snow_depth is not None else 1.0,
        snow_state=a.snow_state, snow_case=a.case, shape=a.shape,
    ))
    if a.bom or a.cost:
        _materials(roof_obj, a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
