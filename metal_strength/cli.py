"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import loads, viz
from .model import pitched_roof, single_beam
from .sections import get_section, list_sections


def _report(roof, out: Path | None, prefix: str, show: bool = False) -> None:
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

    print(f"\n{len(roof.spec.members)} members, {len(roof.spec.nodes)} nodes")
    print(f"\nworst 5 members:")
    for c in ranked[:5]:
        flag = "OK  " if c.ok else "FAIL"
        print(f"  {flag} {c.utilisation:5.2f}  {c.section:<24s} {c.governing.name}")

    print()
    print(worst.report())
    print(f"\nserviceability:\n{defl}")

    ok = all(c.ok for c in checks) and defl.ok
    verdict = "PASSES" if ok else "FAILS"
    print(f"\n=> the structure {verdict} "
          f"(strength {worst.utilisation:.2f}, deflection {defl.utilisation:.2f})")

    if out or show:
        # Charts are always written; --show additionally opens them in windows.
        target = out or Path(tempfile.mkdtemp(prefix="metal-strength-"))
        paths = [
            viz.utilisation_3d(roof, checks, target / f"{prefix}_utilisation.png"),
            viz.utilisation_bars(checks, target / f"{prefix}_ranking.png"),
            viz.deflected_shape(roof, results, target / f"{prefix}_deflection.png"),
            viz.force_diagrams(results, worst_index, target / f"{prefix}_forces.png",
                               f"Governing member: {worst.section}"),
        ]
        print("\ncharts:")
        for p in paths:
            print(f"  {p}")
        if backend:
            print(f"\nopening {len(paths)} windows ({backend}); close them to exit.")
            viz.show()


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

    roof = sub.add_parser("roof", help="generate and check a whole 3D pitched roof")
    roof.add_argument("--span", type=float, required=True, help="metres")
    roof.add_argument("--length", type=float, required=True, help="metres")
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
                      choices=["balanced", "drift_left", "drift_right"])
    roof.add_argument("--out", type=Path)
    roof.add_argument("--show", action="store_true",
                      help="open the charts in windows as well as saving them")

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
        _report(roof_obj, a.out, "beam", a.show)
        return 0

    if a.snow is not None:
        snow_load = a.snow
        origin = f"{a.snow:.2f} kN/m2 given directly"
    elif a.snow_depth is not None:
        sk = loads.snow_from_depth(a.snow_depth, a.snow_state)
        snow_load = loads.roof_snow_load(sk, a.pitch)[0].left
        origin = (f"{a.snow_depth:.2f} m {a.snow_state} snow -> sk {sk:.2f} -> "
                  f"roof {snow_load:.2f} kN/m2")
    else:
        p.error("give either --snow or --snow-depth")

    print(f"roof {a.span} x {a.length} m at {a.pitch}deg; {origin}; case {a.case}")
    roof_obj = pitched_roof(
        span=a.span, length=a.length, pitch_deg=a.pitch, eaves_height=a.eaves_height,
        frame_spacing=a.frame_spacing, purlin_spacing=a.purlin_spacing,
        rafter=a.rafter, column=a.column, purlin=a.purlin, grade=a.grade,
        snow_kn_m2=snow_load, snow_case=a.case,
    )
    _report(roof_obj, a.out, "roof", a.show)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
