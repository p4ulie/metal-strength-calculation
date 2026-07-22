"""MCP server exposing the calculator to an LLM. stdio transport.

Run with ``python -m metal_strength.mcp_server``. Every tool carries an explicit
``description`` rather than relying on docstring parsing, and returns typed
pydantic models so results arrive structured rather than as prose.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

import matplotlib.pyplot as plt
from mcp.server.fastmcp import FastMCP, Image
from pydantic import BaseModel, Field

from . import bom, design, ec3, loads, shapes, viz
from .model import StructureSpec, build, single_beam
from .model import roof as build_roof
from .sections import get_section, list_sections

mcp = FastMCP("metal-strength")

CHARTS = Path(tempfile.gettempdir()) / "metal-strength-charts"

DISCLAIMER = (
    "Indicative Eurocode check, not a substitute for a licensed structural "
    "engineer. Second-order effects, connections, base plates and wind load "
    "(EN 1991-1-4) are not covered."
)


# --- response models --------------------------------------------------------


class SnowResult(BaseModel):
    sk_kn_m2: float = Field(description="characteristic ground snow load")
    explanation: str
    cases: list[dict] = Field(default_factory=list,
                              description="roof arrangements, kN/m2 per slope")


class SectionResult(BaseModel):
    name: str
    family: str
    mass_kg_per_m: float
    area_cm2: float
    depth_mm: float
    width_mm: float
    Iy_cm4: float
    Iz_cm4: float
    Wel_y_cm3: float
    Wpl_y_cm3: float
    It_cm4: float
    Iw_1e3cm6: float
    iy_mm: float
    iz_mm: float


class CheckLine(BaseModel):
    name: str
    clause: str
    utilisation: float
    demand: float
    capacity: float
    unit: str
    ok: bool
    note: str = ""


class MemberVerdict(BaseModel):
    member: str
    section_class: int
    utilisation: float
    governing: str
    ok: bool
    checks: list[CheckLine]
    warnings: list[str]


class StructureVerdict(BaseModel):
    ok: bool
    worst_utilisation: float
    governing_member: str
    governing_check: str
    deflection_mm: float
    deflection_limit_mm: float
    members_checked: int
    worst_members: list[MemberVerdict]
    charts: list[str] = Field(default_factory=list)
    shape: str = ""
    mu_approximate: bool = False
    disclaimer: str = DISCLAIMER


def _lines(result: ec3.MemberResult) -> list[CheckLine]:
    return [
        CheckLine(name=c.name, clause=c.clause, utilisation=round(c.utilisation, 4),
                  demand=c.demand, capacity=c.capacity, unit=c.unit, ok=c.ok, note=c.note)
        for c in sorted(result.checks, key=lambda c: -c.utilisation)
    ]


def _verdict(result: ec3.MemberResult) -> MemberVerdict:
    return MemberVerdict(
        member=result.section, section_class=result.section_class,
        utilisation=round(result.utilisation, 4),
        governing=result.governing.name if result.governing else "none",
        ok=result.ok, checks=_lines(result), warnings=result.warnings,
    )


# --- tools ------------------------------------------------------------------


@mcp.tool(
    name="snow_load_from_depth",
    description=(
        "Convert a measured snow depth into a ground snow load in kN/m2 using the "
        "EN 1991-1-3 bulk densities. Use this for questions like 'how much does 1 "
        "metre of snow weigh on a roof'. The snow state matters enormously: 1 m of "
        "fresh snow is 1.0 kN/m2 but 1 m of wet snow is 4.0 kN/m2."
    ),
)
def snow_load_from_depth(
    depth_m: float,
    state: Literal["fresh", "settled", "old", "wet"] = "settled",
    pitch_deg: float = 0.0,
    exposure: Literal["windswept", "normal", "sheltered"] = "normal",
) -> SnowResult:
    sk = loads.snow_from_depth(depth_m, state)
    cases = loads.roof_snow_load(sk, pitch_deg, exposure=exposure)
    return SnowResult(
        sk_kn_m2=round(sk, 3),
        explanation=(
            f"{depth_m:.2f} m of {state} snow at {loads.SNOW_DENSITY[state]:.1f} kN/m3 "
            f"= {sk:.2f} kN/m2 on the ground. On a {pitch_deg:.0f} degree roof with "
            f"{exposure} exposure, mu1={loads.mu1(pitch_deg):.2f} and "
            f"Ce={loads.EXPOSURE[exposure]:.1f}."
        ),
        cases=[{"case": c.name, "left_kn_m2": round(c.left, 3),
                "right_kn_m2": round(c.right, 3)} for c in cases],
    )


@mcp.tool(
    name="snow_load_eurocode",
    description=(
        "Characteristic ground snow load from a national snow-map zone number and "
        "site altitude, via EN 1991-1-3 Annex C, then the design roof loads for all "
        "required arrangements. Use when the user gives a location zone rather than a "
        "snow depth. Slovakia, Czechia, Poland, Hungary use region 'central_east'."
    ),
)
def snow_load_eurocode(
    zone: float,
    altitude_m: float = 0.0,
    region: Literal["alpine", "central_east", "central_west", "greece", "iberian",
                    "mediterranean", "sub_atlantic"] = "central_east",
    pitch_deg: float = 0.0,
    roof_type: Literal["monopitch", "duopitch"] = "duopitch",
    exposure: Literal["windswept", "normal", "sheltered"] = "normal",
    snow_guards: bool = False,
) -> SnowResult:
    sk = loads.sk_from_zone(zone, altitude_m, region)
    cases = loads.roof_snow_load(sk, pitch_deg, roof_type, exposure,
                                 snow_guards=snow_guards)
    return SnowResult(
        sk_kn_m2=round(sk, 3),
        explanation=(
            f"EN 1991-1-3 Annex C, {region}: zone {zone} at {altitude_m:.0f} m gives "
            f"sk = {sk:.2f} kN/m2. The national annex takes precedence if you have it."
        ),
        cases=[{"case": c.name, "left_kn_m2": round(c.left, 3),
                "right_kn_m2": round(c.right, 3)} for c in cases],
    )


@mcp.tool(
    name="list_sections",
    description=(
        "List available steel profile names, optionally filtered by family "
        "(IPE, HEA, HEB, HEM, CHS, SHS, RHS). Call this before section_properties "
        "if unsure how a profile is spelled."
    ),
)
def list_sections_tool(family: str | None = None, limit: int = 60) -> dict:
    names = list_sections(family)
    return {"count": len(names), "families": ["IPE", "HEA", "HEB", "HEM", "CHS", "SHS", "RHS"],
            "names": names[:limit], "truncated": len(names) > limit}


@mcp.tool(
    name="section_properties",
    description=(
        "Geometric and section properties of a steel profile: area, second moments "
        "of area, elastic and plastic section moduli, torsion and warping constants, "
        "radii of gyration and mass per metre. Accepts catalogue names like IPE300, "
        "HEB200, CHS114.3x5, SHS100x100x5, RHS200x100x8."
    ),
)
def section_properties(name: str) -> SectionResult:
    s = get_section(name)
    return SectionResult(
        name=s.name, family=s.family, mass_kg_per_m=round(s.mass_per_m, 2),
        area_cm2=round(s.A / 1e2, 2), depth_mm=s.h, width_mm=s.b,
        Iy_cm4=round(s.Iy / 1e4, 1), Iz_cm4=round(s.Iz / 1e4, 1),
        Wel_y_cm3=round(s.Wel_y / 1e3, 1), Wpl_y_cm3=round(s.Wpl_y / 1e3, 1),
        It_cm4=round(s.It / 1e4, 2), Iw_1e3cm6=round(s.Iw / 1e9, 1),
        iy_mm=round(s.iy, 1), iz_mm=round(s.iz, 1),
    )


@mcp.tool(
    name="check_beam",
    description=(
        "Check a single steel beam or rod against EN 1993-1-1: bending, shear, "
        "lateral-torsional buckling and deflection. This is the tool for 'will this "
        "beam hold', 'what is the safe load', 'is this rod strong enough'. Loads are "
        "DESIGN (already factored) values: multiply characteristic snow by 1.5 and "
        "self weight by 1.35, or use check_roof which does it for you. Set restrained "
        "to true when a deck or purlins hold the compression flange sideways."
    ),
)
def check_beam(
    span_m: float,
    section: str = "IPE200",
    grade: Literal["S235", "S275", "S355", "S420", "S460"] = "S235",
    udl_kn_per_m: float = 0.0,
    point_load_kn: float = 0.0,
    fixity: Literal["simple", "cantilever", "fixed", "propped"] = "simple",
    restrained: bool = False,
    deflection_limit: Literal["roof_general", "roof_brittle_finish", "floor"] = "roof_general",
    charts: bool = False,
) -> StructureVerdict:
    beam = single_beam(span_m, section, grade, udl_kn_per_m, point_load_kn,
                       fixity, restrained)
    results = beam.solve()
    checks = beam.check(results)
    defl = beam.deflection(results, deflection_limit)
    ranked = sorted(checks, key=lambda c: -c.utilisation)
    worst = ranked[0]

    paths: list[str] = []
    if charts:
        CHARTS.mkdir(parents=True, exist_ok=True)
        stem = f"beam_{section}_{span_m:g}m"
        paths = [
            str(viz.force_diagrams(results, checks.index(worst),
                                   CHARTS / f"{stem}_forces.png", worst.section)),
            str(viz.deflected_shape(beam, results, CHARTS / f"{stem}_deflection.png")),
        ]

    return StructureVerdict(
        ok=all(c.ok for c in checks) and defl.ok,
        worst_utilisation=round(worst.utilisation, 3),
        governing_member=worst.section,
        governing_check=worst.governing.name if worst.governing else "none",
        deflection_mm=round(defl.demand, 2),
        deflection_limit_mm=round(defl.capacity, 2),
        members_checked=len(checks),
        worst_members=[_verdict(worst)],
        charts=paths,
    )


@mcp.tool(
    name="check_rod_buckling",
    description=(
        "Compression (Euler / EN 1993-1-1 6.3.1) buckling capacity of a strut or rod. "
        "Returns the design buckling resistance about both axes, the reduction factor "
        "chi and the slenderness. Effective length factor: 0.5 both ends fixed, 0.7 "
        "one fixed one pinned, 1.0 both pinned, 2.0 cantilever."
    ),
)
def check_rod_buckling(
    length_m: float,
    section: str = "CHS60.3x3.2",
    grade: Literal["S235", "S275", "S355", "S420", "S460"] = "S235",
    effective_length_factor: float = 1.0,
    axial_load_kn: float = 0.0,
) -> dict:
    s = get_section(section)
    fy, _ = ec3.yield_strength(grade, max(s.tf, s.tw))
    Lcr = length_m * 1000.0 * effective_length_factor
    out: dict = {"section": s.name, "grade": grade, "fy_mpa": fy,
                 "effective_length_m": round(Lcr / 1000.0, 3),
                 "squash_load_kn": round(s.A * fy / 1e3, 1)}
    for axis in ("y", "z"):
        Nb, chi, lam = ec3.flexural_buckling(s, fy, Lcr, axis)
        out[f"buckling_{axis}{axis}"] = {
            "curve": ec3.buckling_curve(s, fy, axis),
            "slenderness": round(lam, 3), "chi": round(chi, 4),
            "N_b_Rd_kn": round(Nb / 1e3, 1),
        }
    governing = min(out["buckling_yy"]["N_b_Rd_kn"], out["buckling_zz"]["N_b_Rd_kn"])
    out["capacity_kn"] = governing
    if axial_load_kn:
        out["utilisation"] = round(abs(axial_load_kn) / governing, 3)
        out["ok"] = abs(axial_load_kn) <= governing
    out["disclaimer"] = DISCLAIMER
    return out


@mcp.tool(
    name="check_roof",
    description=(
        "Build and check a complete 3D steel roof under snow, in any of the shapes "
        "list_shapes reports: portal frames "
        "at spacing with purlins between them, solved by 3D frame FEM and verified "
        "member by member against EN 1993-1-1. This is the tool for 'will my roof "
        "hold 1 metre of snow'. Give the snow either as a depth plus state, or "
        "directly in kN/m2. Load factors (1.35 permanent, 1.5 snow) are applied "
        "internally, so give characteristic values."
    ),
)
def check_roof(
    span_m: float,
    length_m: float,
    pitch_deg: float = 20.0,
    snow_depth_m: float | None = None,
    snow_state: Literal["fresh", "settled", "old", "wet"] = "settled",
    snow_kn_m2: float | None = None,
    eaves_height_m: float = 3.0,
    frame_spacing_m: float = 5.0,
    purlin_spacing_m: float = 1.5,
    rafter: str = "IPE300",
    column: str = "HEB200",
    purlin: str = "SHS100x100x5",
    grade: Literal["S235", "S275", "S355", "S420", "S460"] = "S235",
    shape: Literal["flat", "monopitch", "duopitch", "mansard", "gambrel",
                   "sawtooth", "multispan"] = "duopitch",
    case: Literal["balanced", "drift_left", "drift_right",
                  "valley_drift"] = "balanced",
    charts: bool = False,
) -> StructureVerdict:
    if snow_kn_m2 is None:
        if snow_depth_m is None:
            raise ValueError("give either snow_depth_m or snow_kn_m2")
        sk = loads.snow_from_depth(snow_depth_m, snow_state)
        snow_kn_m2 = loads.roof_snow_load(sk, pitch_deg)[0].left

    roof = build_roof(
        span=span_m, length=length_m, pitch_deg=pitch_deg, shape=shape,
        eaves_height=eaves_height_m, frame_spacing=frame_spacing_m,
        purlin_spacing=purlin_spacing_m, rafter=rafter, column=column,
        purlin=purlin, grade=grade, snow_kn_m2=snow_kn_m2, snow_case=case,
    )
    results = roof.solve()
    checks = roof.check(results)
    defl = roof.deflection(results)
    ranked = sorted(checks, key=lambda c: -c.utilisation)
    worst = ranked[0]

    paths: list[str] = []
    if charts:
        CHARTS.mkdir(parents=True, exist_ok=True)
        stem = f"roof_{shape}_{span_m:g}x{length_m:g}_{case}"
        paths = [
            str(viz.utilisation_3d(roof, checks, CHARTS / f"{stem}_utilisation.png")),
            str(viz.utilisation_bars(checks, CHARTS / f"{stem}_ranking.png")),
            str(viz.deflected_shape(roof, results, CHARTS / f"{stem}_deflection.png")),
            str(viz.force_diagrams(results, checks.index(worst),
                                   CHARTS / f"{stem}_forces.png", worst.section)),
        ]

    return StructureVerdict(
        ok=all(c.ok for c in checks) and defl.ok,
        worst_utilisation=round(worst.utilisation, 3),
        governing_member=worst.section,
        governing_check=worst.governing.name if worst.governing else "none",
        deflection_mm=round(defl.demand, 2),
        deflection_limit_mm=round(defl.capacity, 2),
        members_checked=len(checks),
        worst_members=[_verdict(c) for c in ranked[:5]],
        charts=paths,
        shape=shape,
        mu_approximate=roof.profile.mu_is_approximate if roof.profile else False,
    )


@mcp.tool(
    name="list_shapes",
    description=(
        "List the roof profile shapes check_roof can build, with the EN 1991-1-3 "
        "snow arrangements that apply to each and whether its shape coefficients "
        "are approximate. Call this before check_roof when the roof is not a "
        "plain duopitch."
    ),
)
def list_shapes_tool() -> dict:
    return {
        "shapes": [
            {
                "shape": name,
                "description": shapes.DESCRIPTIONS[name],
                "snow_cases": list(loads.ARRANGEMENTS[name]),
                "mu_approximate": name in shapes.APPROXIMATE_MU,
            }
            for name in shapes.SHAPES
        ],
        "note": ("Hipped, pyramidal and conical roofs are not supported -- they are "
                 "not a constant profile extruded along the length."),
    }


# --- a tunable session ------------------------------------------------------
# One mutable parameter set, so a client can nudge a single value instead of
# restating the whole roof on every call.
# ponytail: one session shared by every client of this process. That is right
# for a tool one person drives; add a session id if it ever serves two at once.

TUNE_DEFAULTS: dict = {
    "span_m": 12.0, "length_m": 20.0, "pitch_deg": 20.0, "shape": "duopitch",
    "eaves_height_m": 3.0, "frame_spacing_m": 5.0, "purlin_spacing_m": 1.5,
    "rafter": "IPE450", "column": "HEB240", "purlin": "SHS140x140x5",
    "grade": "S235", "snow_depth_m": 1.0, "snow_state": "wet",
    "snow_kn_m2": None, "case": "balanced",
}
_session: dict = dict(TUNE_DEFAULTS)

# When a window is open in this process it registers an applier here. tune_roof
# then sets the parameters *through the window*, so the sliders move and there
# is one set of values rather than two. The applier is called from the server's
# thread and is responsible for getting the work onto the GUI thread.
_apply_through_window = None


def attach_window(applier) -> None:
    """Route tune_roof through an open window. ``None`` detaches it."""
    global _apply_through_window, _session
    _apply_through_window = applier
    if applier is not None:
        _session = applier.session


def _session_roof(params: dict):
    snow = params["snow_kn_m2"]
    if snow is None:
        sk = loads.snow_from_depth(params["snow_depth_m"], params["snow_state"])
        snow = loads.roof_snow_load(sk, params["pitch_deg"])[0].left
    return build_roof(
        span=params["span_m"], length=params["length_m"],
        pitch_deg=params["pitch_deg"], shape=params["shape"],
        eaves_height=params["eaves_height_m"],
        frame_spacing=params["frame_spacing_m"],
        purlin_spacing=params["purlin_spacing_m"],
        rafter=params["rafter"], column=params["column"], purlin=params["purlin"],
        grade=params["grade"], snow_kn_m2=snow, snow_case=params["case"],
    ), snow


@mcp.tool(
    name="tune_roof",
    description=(
        "Adjust one or more parameters of a roof that persists between calls, "
        "re-solve it, and get back the verdict plus a four-panel chart image. "
        "This is the tool for iterating: 'now try a multispan', 'raise the rafter "
        "to IPE500', 'what about 1.5 m of wet snow' -- omitted arguments keep "
        "their current value, so you only state what changes. Pass reset=true to "
        "go back to the defaults, or no arguments at all to re-read the current "
        "state. Prefer check_roof for a single one-off check."
    ),
)
def tune_roof(
    span_m: float | None = None,
    length_m: float | None = None,
    pitch_deg: float | None = None,
    shape: Literal["flat", "monopitch", "duopitch", "mansard", "gambrel",
                   "sawtooth", "multispan"] | None = None,
    eaves_height_m: float | None = None,
    frame_spacing_m: float | None = None,
    purlin_spacing_m: float | None = None,
    rafter: str | None = None,
    column: str | None = None,
    purlin: str | None = None,
    grade: Literal["S235", "S275", "S355", "S420", "S460"] | None = None,
    snow_depth_m: float | None = None,
    snow_state: Literal["fresh", "settled", "old", "wet"] | None = None,
    snow_kn_m2: float | None = None,
    case: Literal["balanced", "drift_left", "drift_right",
                  "valley_drift"] | None = None,
    reset: bool = False,
    chart: bool = True,
) -> list:
    global _session
    if reset:
        _session = dict(TUNE_DEFAULTS)

    given = {k: v for k, v in locals().items()
             if k in TUNE_DEFAULTS and v is not None}
    # A depth given after a direct load means the depth is what you now mean.
    if ("snow_depth_m" in given or "snow_state" in given) and "snow_kn_m2" not in given:
        given["snow_kn_m2"] = None
    changed = {k: v for k, v in given.items() if _session.get(k) != v}
    _session.update(given)

    if _apply_through_window is not None:
        # The window owns the widgets; it applies the change, re-solves and
        # hands the result back. _session is the same dict it reads.
        roof, results, checks = _apply_through_window(given)
        snow = roof.snow_kn_m2
    else:
        roof, snow = _session_roof(_session)
        results = roof.solve()
        checks = roof.check(results)
    defl = roof.deflection(results)
    worst = max(checks, key=lambda c: c.utilisation)

    state = {
        "parameters": dict(_session),
        "changed": changed,
        "snow_kn_m2_applied": round(float(snow), 3),
        "ok": all(c.ok for c in checks) and defl.ok,
        "worst_utilisation": round(float(worst.utilisation), 3),
        "governing_member": worst.section,
        "governing_check": worst.governing.name if worst.governing else "none",
        "deflection_utilisation": round(float(defl.utilisation), 3),
        "total_mass_kg": round(float(roof.total_mass_kg), 1),
        "members": len(checks),
        "mu_approximate": roof.profile.mu_is_approximate if roof.profile else False,
        "snow_cases_available": list(loads.ARRANGEMENTS[_session["shape"]]),
        "disclaimer": DISCLAIMER,
    }
    state["window"] = _apply_through_window is not None

    if not chart:
        return [state]

    CHARTS.mkdir(parents=True, exist_ok=True)
    path = CHARTS / "tune_roof.png"
    fig = viz.panel(roof, results, checks, title=f"{_session['shape']} roof")
    fig.savefig(path, dpi=80)  # dpi 80 keeps the inline image around 300 kB
    plt.close(fig)
    return [state, Image(path=path)]


@mcp.tool(
    name="solve_frame",
    description=(
        "Solve an arbitrary 3D frame given explicitly as nodes, members, supports and "
        "loads, and check every member to EN 1993-1-1. Use when the structure is not "
        "a standard pitched roof. Nodes are in metres, loads in kN and kN/m, global Z "
        "is up. Supports are 'fixed', 'pinned', 'roller' or 'free'."
    ),
)
def solve_frame(spec: StructureSpec, charts: bool = False) -> StructureVerdict:
    from .model import Roof

    structure, sections, grades = build(spec)
    span = max(n.x for n in spec.nodes) - min(n.x for n in spec.nodes)
    roof = Roof(spec, structure, sections, grades, 0.0, max(span, 1e-6), 0.0)
    results = roof.solve()
    checks = roof.check(results)
    defl = roof.deflection(results)
    ranked = sorted(checks, key=lambda c: -c.utilisation)
    worst = ranked[0]

    paths: list[str] = []
    if charts:
        CHARTS.mkdir(parents=True, exist_ok=True)
        paths = [
            str(viz.utilisation_3d(roof, checks, CHARTS / "frame_utilisation.png")),
            str(viz.deflected_shape(roof, results, CHARTS / "frame_deflection.png")),
        ]

    return StructureVerdict(
        ok=all(c.ok for c in checks) and defl.ok,
        worst_utilisation=round(worst.utilisation, 3),
        governing_member=worst.section,
        governing_check=worst.governing.name if worst.governing else "none",
        deflection_mm=round(defl.demand, 2),
        deflection_limit_mm=round(defl.capacity, 2),
        members_checked=len(checks),
        worst_members=[_verdict(c) for c in ranked[:5]],
        charts=paths,
    )


class BomLine(BaseModel):
    role: str
    profile: str
    grade: str
    qty: int
    length_each_m: float
    total_length_m: float
    total_mass_kg: float
    rate_per_kg: float | None = None
    cost: float | None = None


class MaterialList(BaseModel):
    lines: list[BomLine]
    total_mass_kg: float
    currency: str | None = None
    subtotal: float | None = None
    vat_rate: float | None = None
    total_incl_vat: float | None = None
    price_note: str | None = None
    estimated_rate_families: list[str] = Field(default_factory=list)


class Proposal(BaseModel):
    ok: bool
    sections: dict[str, str]
    utilisation: float
    deflection_utilisation: float
    governing_check: str
    total_mass_kg: float
    combinations_tried: int
    message: str = ""
    materials: MaterialList | None = None
    disclaimer: str = DISCLAIMER


def _material_list(construction, prices) -> MaterialList:
    b = bom.bill_of_materials(construction, prices)
    lines = [
        BomLine(role=line.role, profile=line.section, grade=line.grade,
                qty=line.count, length_each_m=round(line.length_each_m, 3),
                total_length_m=round(line.total_length_m, 2),
                total_mass_kg=round(line.total_mass_kg, 1),
                rate_per_kg=prices.rate(line.family) if prices else None,
                cost=round(b.line_cost(line), 0) if prices else None)
        for line in b.lines
    ]
    out = MaterialList(lines=lines, total_mass_kg=round(b.total_mass_kg, 1))
    if prices:
        out.currency = prices.display_currency
        out.subtotal = round(prices.display(b.subtotal), 2)
        out.vat_rate = prices.vat_rate
        out.total_incl_vat = round(prices.display(b.total), 2)
        out.estimated_rate_families = b.uses_assumed_rates
        out.price_note = (
            f"INDICATIVE ONLY. Published {prices.origin} list rates read "
            f"{prices.retrieved}, not a quote. Material only - no fabrication, "
            f"coating, connections, transport or erection. "
            + (f"Converted from {prices.currency} for {prices.country}. "
               if prices.converted else "")
            + ("Rates for " + ", ".join(b.uses_assumed_rates) + " are estimates "
               "with no published list behind them. " if b.uses_assumed_rates else "")
            + "Confirm with a supplier before ordering."
        )
    return out


@mcp.tool(
    name="propose_construction",
    description=(
        "Design a steel roof structure for a given span, length and snow load: "
        "searches the profile catalogue for the lightest rafter/column/purlin "
        "combination that satisfies every EN 1993-1-1 check and the deflection "
        "limit. This is the tool for 'what do I need to build' as opposed to "
        "check_roof's 'will this work'. Returns the proposed sections plus an "
        "optional priced material list. Says so plainly if nothing in the "
        "catalogue carries the load."
    ),
)
def propose_construction(
    span_m: float,
    length_m: float,
    pitch_deg: float = 20.0,
    snow_depth_m: float | None = None,
    snow_state: Literal["fresh", "settled", "old", "wet"] = "settled",
    snow_kn_m2: float | None = None,
    grade: Literal["S235", "S275", "S355", "S420", "S460"] = "S235",
    eaves_height_m: float = 3.0,
    frame_spacing_m: float = 5.0,
    purlin_spacing_m: float = 1.5,
    target_utilisation: float = 1.0,
    include_prices: bool = False,
    country: Literal["SK", "CZ"] = "SK",
) -> Proposal:
    if snow_kn_m2 is None:
        if snow_depth_m is None:
            raise ValueError("give either snow_depth_m or snow_kn_m2")
        sk = loads.snow_from_depth(snow_depth_m, snow_state)
        snow_kn_m2 = loads.roof_snow_load(sk, pitch_deg)[0].left

    prices = bom.Prices.load(country=country) if include_prices else None
    p = design.propose(
        span=span_m, length=length_m, pitch_deg=pitch_deg, snow_kn_m2=snow_kn_m2,
        grade=grade, target=target_utilisation, prices=prices,
        eaves_height=eaves_height_m, frame_spacing=frame_spacing_m,
        purlin_spacing=purlin_spacing_m,
    )
    out = Proposal(
        ok=p.feasible, sections=p.sections,
        utilisation=round(p.utilisation, 3),
        deflection_utilisation=round(p.deflection_utilisation, 3),
        governing_check=p.governing, total_mass_kg=round(p.mass_kg, 1),
        combinations_tried=p.iterations,
    )
    if not p.feasible:
        out.message = ("No combination in the catalogue carries this load. "
                       "Reduce the span, add frames, or lower the load.")
        return out
    if include_prices:
        out.materials = _material_list(p.construction, prices)
    return out


@mcp.tool(
    name="material_list",
    description=(
        "Bill of materials for a roof: every member grouped by role, profile and "
        "cut length, with quantities and mass. Set include_prices to add an "
        "INDICATIVE cost - published Czech list rates, material only, not a "
        "quote. Always repeat the price_note to the user; never present the "
        "total as a firm price."
    ),
)
def material_list(
    span_m: float,
    length_m: float,
    pitch_deg: float = 20.0,
    rafter: str = "IPE300",
    column: str = "HEB200",
    purlin: str = "SHS100x100x5",
    grade: Literal["S235", "S275", "S355", "S420", "S460"] = "S235",
    eaves_height_m: float = 3.0,
    frame_spacing_m: float = 5.0,
    purlin_spacing_m: float = 1.5,
    snow_kn_m2: float = 2.0,
    include_prices: bool = True,
    country: Literal["SK", "CZ"] = "SK",
    waste_percent: float = 0.0,
) -> MaterialList:
    con = build_roof(
        span=span_m, length=length_m, pitch_deg=pitch_deg,
        eaves_height=eaves_height_m, frame_spacing=frame_spacing_m,
        purlin_spacing=purlin_spacing_m, rafter=rafter, column=column,
        purlin=purlin, grade=grade, snow_kn_m2=snow_kn_m2,
    )
    prices = bom.Prices.load(country=country) if include_prices else None
    b = bom.bill_of_materials(con, prices, waste=waste_percent / 100.0)
    out = _material_list(con, prices)
    out.total_mass_kg = round(b.total_mass_kg, 1)
    return out


@mcp.tool(
    name="render_snow_cases",
    description=(
        "Draw the EN 1991-1-3 snow load arrangements on a roof profile and return the "
        "image path. Useful for explaining why an unbalanced drift case can govern."
    ),
)
def render_snow_cases(
    sk_kn_m2: float,
    pitch_deg: float,
    shape: Literal["flat", "monopitch", "duopitch", "mansard", "gambrel",
                   "sawtooth", "multispan"] = "duopitch",
) -> dict:
    CHARTS.mkdir(parents=True, exist_ok=True)
    p = viz.snow_cases(sk_kn_m2, pitch_deg,
                       CHARTS / f"snow_{shape}_{sk_kn_m2:g}_{pitch_deg:g}.png",
                       shape=shape)
    return {"path": str(p), "mu_approximate": shape in shapes.APPROXIMATE_MU}


def main() -> None:
    """``python -m metal_strength.mcp_server`` -- the same thing as ``serve``.

    Kept because MCP clients are configured with a module path and stdio; the
    server itself lives in the one CLI now.
    """
    from .cli import main as cli_main

    raise SystemExit(cli_main(["serve"]))


if __name__ == "__main__":
    main()
