"""Structural models in engineering units, and the pitched-roof generator.

The rest of the package works in N and mm; this module is the boundary where
kN and metres are converted, so nobody downstream has to think about it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from . import ec3, frame3d, loads
from .sections import Section, get_section

M_TO_MM = 1000.0
KN_TO_N = 1000.0
KNM_TO_NMM = 1e6


# --- A serialisable model, so the same input works from CLI, MCP and tests ---


class NodeSpec(BaseModel):
    x: float
    y: float = 0.0
    z: float = 0.0


class MemberSpec(BaseModel):
    i: int
    j: int
    section: str = "IPE200"
    grade: str = "S235"
    roll_deg: float = 0.0
    pinned: bool = False
    tag: str = ""


class LoadSpec(BaseModel):
    """A load in kN / kN per metre. ``member`` set means a UDL, else nodal."""

    node: int | None = None
    member: int | None = None
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
    udl_z: float = 0.0  # kN/m along global -Z


class StructureSpec(BaseModel):
    """A whole structure in metres and kN. This is the MCP wire format."""

    nodes: list[NodeSpec]
    members: list[MemberSpec]
    supports: dict[int, str] = Field(default_factory=dict)  # "fixed"|"pinned"|"roller"
    point_loads: list[LoadSpec] = Field(default_factory=list)
    member_loads: list[LoadSpec] = Field(default_factory=list)


FIXITY = {
    "fixed": (True,) * 6,
    "pinned": (True, True, True, True, False, False),
    "roller": (False, True, True, True, False, False),
    "free": (False,) * 6,
}

_PINNED_ENDS = (("i", "ry"), ("i", "rz"), ("j", "ry"), ("j", "rz"))


def build(spec: StructureSpec) -> tuple[frame3d.Structure, list[Section], list[str]]:
    """Convert a metres/kN spec into the mm/N structure the solver wants."""
    nodes = [frame3d.Node(n.x * M_TO_MM, n.y * M_TO_MM, n.z * M_TO_MM) for n in spec.nodes]
    sections = [get_section(m.section) for m in spec.members]
    grades = [m.grade for m in spec.members]
    members = [
        frame3d.Member(
            m.i, m.j, ec3.E, ec3.G, s.A, s.Iy, s.Iz, s.It,
            roll=math.radians(m.roll_deg),
            releases=_PINNED_ENDS if m.pinned else (),
            tag=m.tag or m.section,
        )
        for m, s in zip(spec.members, sections)
    ]

    supports = {}
    for idx, kind in spec.supports.items():
        if kind not in FIXITY:
            raise ValueError(f"support must be one of {sorted(FIXITY)}, got {kind!r}")
        supports[int(idx)] = FIXITY[kind]

    nodal: dict[int, tuple[float, ...]] = {}
    for load in spec.point_loads:
        if load.node is None:
            raise ValueError("a point load needs a node index")
        f = (load.fx * KN_TO_N, load.fy * KN_TO_N, load.fz * KN_TO_N, 0.0, 0.0, 0.0)
        prev = nodal.get(load.node, (0.0,) * 6)
        nodal[load.node] = tuple(a + b for a, b in zip(prev, f))

    member_loads = [
        frame3d.MemberLoad(load.member, globalz=load.udl_z * KN_TO_N / M_TO_MM)
        for load in spec.member_loads
        if load.member is not None
    ]

    return (
        frame3d.Structure(nodes, members, supports, nodal, member_loads),
        sections,
        grades,
    )


# --- Roof generation --------------------------------------------------------


@dataclass
class Roof:
    """A generated 3D roof plus the bookkeeping needed to check it."""

    spec: StructureSpec
    structure: frame3d.Structure
    sections: list[Section]
    grades: list[str]
    pitch_deg: float
    span: float
    length: float
    # member index -> unbraced length for LTB, in mm
    lt_lengths: dict[int, float] = field(default_factory=dict)
    snow_case: str = ""
    snow_kn_m2: float = 0.0

    def solve(self) -> frame3d.Results:
        return frame3d.solve(self.structure)

    def deflection(
        self, results: frame3d.Results, limit: str = "roof_general"
    ) -> ec3.Check:
        """Peak vertical deflection against span/limit (EN 1990 A1.4).

        Note the solved deflection comes from the *factored* loads the model was
        built with, so this is conservative -- serviceability is properly checked
        against unfactored loads.
        """
        peak = float(abs(results.displacements[:, 2]).min()
                     if results.displacements[:, 2].min() > 0
                     else abs(results.displacements[:, 2]).max())
        allowed = (self.span * M_TO_MM) / ec3.DEFLECTION_LIMITS[limit]
        return ec3.Check(
            f"deflection (span/{ec3.DEFLECTION_LIMITS[limit]:.0f})", "EN 1990 A1.4",
            peak, allowed, "mm",
            "from factored loads, so conservative for serviceability",
        )

    def check(self, results: frame3d.Results | None = None) -> list[ec3.MemberResult]:
        """Run the Eurocode checks on every member using the solved forces."""
        r = results if results is not None else self.solve()
        out = []
        for e, (sec, grade) in enumerate(zip(self.sections, self.grades)):
            p = r.peak(e)
            m = self.structure.members[e]
            L = r.lengths[e]
            forces = ec3.MemberForces(
                N=p["N"], Vy=p["Vy"], Vz=p["Vz"], My=p["My"], Mz=p["Mz"], T=p["T"]
            )
            lengths = ec3.BucklingLengths(
                Lcr_y=L, Lcr_z=L, L_LT=self.lt_lengths.get(e, L), C1=1.13
            )
            res = ec3.check_member(sec, grade, forces, lengths)
            res.section = f"[{e}] {m.tag or sec.name}"
            out.append(res)
        return out


def pitched_roof(
    span: float,
    length: float,
    pitch_deg: float,
    eaves_height: float = 3.0,
    frame_spacing: float = 5.0,
    purlin_spacing: float = 1.5,
    rafter: str = "IPE300",
    column: str = "HEB200",
    purlin: str = "SHS100x100x5",
    grade: str = "S235",
    snow_kn_m2: float = 2.0,
    snow_case: str = "balanced",
    include_self_weight: bool = True,
    pinned_bases: bool = True,
    gamma_G: float = 1.35,
    gamma_Q: float = 1.5,
) -> Roof:
    """Build a duopitch portal-frame roof and load it with snow.

    All lengths in metres, snow in kN/m^2 on the horizontal projection.

    Portal frames sit in the X-Z plane at intervals of ``frame_spacing`` along
    Y. Purlins run along Y between frames at ``purlin_spacing`` measured up the
    slope, and carry the snow to the rafters. ``snow_case`` is ``balanced``,
    ``drift_left`` or ``drift_right`` -- the halved slope of a drift case gets
    half the load, per EN 1991-1-3 Figure 5.3.
    """
    if span <= 0 or length <= 0:
        raise ValueError("span and length must be positive")
    if not 0 <= pitch_deg < 60:
        raise ValueError("pitch must be between 0 and 60 degrees")

    slope = math.radians(pitch_deg)
    half = span / 2
    rise = half * math.tan(slope)
    slope_len = math.hypot(half, rise)

    n_bays = max(1, round(length / frame_spacing))
    frame_y = [i * length / n_bays for i in range(n_bays + 1)]
    n_purlin = max(1, round(slope_len / purlin_spacing))
    # Positions along one slope, from eaves (0) to apex (1).
    t = [k / n_purlin for k in range(n_purlin + 1)]

    nodes: list[NodeSpec] = []
    index: dict[tuple[int, int], int] = {}  # (frame, station) -> node index

    def add(frame: int, station: int, x: float, y: float, z: float) -> int:
        nodes.append(NodeSpec(x=x, y=y, z=z))
        index[(frame, station)] = len(nodes) - 1
        return len(nodes) - 1

    # Stations along a frame: 0 = left base, 1..n = left slope eaves->apex,
    # n+1..2n = right slope apex->eaves (apex shared), last = right base.
    n_left = len(t)  # eaves..apex inclusive
    for f, y in enumerate(frame_y):
        add(f, 0, 0.0, y, 0.0)  # left base
        for k, tk in enumerate(t):  # left slope, eaves -> apex
            add(f, 1 + k, half * tk, y, eaves_height + rise * tk)
        for k, tk in enumerate(t[1:], start=1):  # right slope, apex -> eaves
            add(f, n_left + k, half + half * tk, y, eaves_height + rise * (1 - tk))
        add(f, n_left + len(t), span, y, 0.0)  # right base

    last_station = n_left + len(t)
    members: list[MemberSpec] = []
    lt: dict[int, float] = {}

    def add_member(i: int, j: int, sec: str, tag: str, lt_len: float | None = None) -> int:
        members.append(MemberSpec(i=i, j=j, section=sec, grade=grade, tag=tag))
        e = len(members) - 1
        if lt_len is not None:
            lt[e] = lt_len * M_TO_MM
        return e

    for f in range(len(frame_y)):
        # Columns: unbraced over their full height for LTB.
        add_member(index[(f, 0)], index[(f, 1)], column, f"column L f{f}", eaves_height)
        add_member(index[(f, last_station)], index[(f, last_station - 1)], column,
                   f"column R f{f}", eaves_height)
        # Rafter segments. Purlins restrain the rafter's top flange, so the
        # unbraced length for LTB is the purlin spacing, not the whole rafter.
        seg = slope_len / n_purlin
        for k in range(1, last_station - 1):
            add_member(index[(f, k)], index[(f, k + 1)], rafter, f"rafter f{f} s{k}", seg)

    # Purlins run along Y, connecting the same station on adjacent frames.
    purlin_members: list[tuple[int, int]] = []  # (member index, station)
    for f in range(len(frame_y) - 1):
        for k in range(1, last_station):
            e = add_member(index[(f, k)], index[(f + 1, k)], purlin, f"purlin s{k} b{f}",
                           length / n_bays)
            purlin_members.append((e, k))

    supports = {}
    kind = "pinned" if pinned_bases else "fixed"
    for f in range(len(frame_y)):
        supports[index[(f, 0)]] = kind
        supports[index[(f, last_station)]] = kind

    # -- snow, applied to the purlins -----------------------------------------
    # A purlin's tributary width is the slope distance it collects, but the
    # snow load is defined on the horizontal projection, so multiply by cos.
    trib_slope = slope_len / n_purlin  # full spacing; edges get half
    left_factor, right_factor = 1.0, 1.0
    if snow_case == "drift_left":
        right_factor = 0.5
    elif snow_case == "drift_right":
        left_factor = 0.5
    elif snow_case != "balanced":
        raise ValueError("snow_case must be balanced, drift_left or drift_right")

    member_loads: list[LoadSpec] = []
    for e, station in purlin_members:
        edge = station in (1, last_station - 1)  # eaves purlins collect half
        apex = station == n_left  # apex purlin collects from both slopes
        width = trib_slope * (0.5 if edge else 1.0)
        factor = left_factor if station <= n_left else right_factor
        if apex:
            width = trib_slope * 0.5 * (left_factor + right_factor)
            factor = 1.0
        udl = snow_kn_m2 * width * math.cos(slope) * factor  # kN/m
        if include_self_weight:
            udl += loads.self_weight_udl(get_section(purlin).A)
        member_loads.append(LoadSpec(member=e, udl_z=gamma_G * 0 + gamma_Q * udl))

    if include_self_weight:
        for e, m in enumerate(members):
            if m.tag.startswith(("rafter", "column")):
                sw = loads.self_weight_udl(get_section(m.section).A)
                member_loads.append(LoadSpec(member=e, udl_z=gamma_G * sw))

    spec = StructureSpec(nodes=nodes, members=members, supports=supports,
                         member_loads=member_loads)
    structure, sections, grades = build(spec)
    return Roof(spec, structure, sections, grades, pitch_deg, span, length,
                lt, snow_case, snow_kn_m2)


def single_beam(
    span: float,
    section: str = "IPE200",
    grade: str = "S235",
    udl_kn_m: float = 0.0,
    point_kn: float = 0.0,
    fixity: str = "simple",
    restrained: bool = False,
    n_elements: int = 8,
) -> Roof:
    """One beam or rod, the simplest useful case. Lengths in metres, loads in kN.

    ``restrained`` means the compression flange is held laterally along its
    length (by a deck or purlins), so lateral-torsional buckling cannot occur.
    """
    s = get_section(section)
    n = n_elements if point_kn == 0 else 2 * (n_elements // 2)
    xs = [span * k / n for k in range(n + 1)]
    nodes = [NodeSpec(x=x) for x in xs]
    members = [MemberSpec(i=k, j=k + 1, section=section, grade=grade, tag=section)
               for k in range(n)]

    last = n
    supports = {
        "simple": {0: "pinned", last: "roller"},
        "cantilever": {0: "fixed"},
        "fixed": {0: "fixed", last: "fixed"},
        "propped": {0: "fixed", last: "roller"},
    }[fixity]

    point = ([LoadSpec(node=n // 2, fz=-point_kn)] if point_kn else [])
    udl = ([LoadSpec(member=k, udl_z=udl_kn_m) for k in range(n)] if udl_kn_m else [])

    spec = StructureSpec(nodes=nodes, members=members, supports=supports,
                         point_loads=point, member_loads=udl)
    structure, sections, grades = build(spec)
    lt = {k: 0.0 if restrained else span * M_TO_MM for k in range(n)}
    return Roof(spec, structure, sections, grades, 0.0, span, 0.0, lt)
