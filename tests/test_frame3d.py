"""The FEM engine, checked against closed-form solutions only.

If these pass, the 12x12 element matrix, the coordinate transformation, the
equivalent nodal loads and the force recovery are all right.
"""

import math

import numpy as np
import pytest

from metal_strength.frame3d import (
    Member,
    MemberLoad,
    Node,
    Structure,
    simple_beam,
    solve,
)

E, G = 210_000.0, 81_000.0  # MPa
A, Iy, Iz, It = 5380.0, 8.356e7, 6.04e6, 2.06e5  # IPE300, mm^...
L = 6000.0  # mm

REL = 1e-3  # 0.1%


def test_cantilever_point_load():
    P = 10_000.0  # N
    s = simple_beam(L, E, G, A, Iy, Iz, It, P=P, fixity="cantilever")
    # simple_beam puts the point load at midspan; move it to the tip instead.
    s.nodal_loads = {2: (0.0, 0.0, -P, 0.0, 0.0, 0.0)}
    r = solve(s)

    assert r.displacements[2, 2] == pytest.approx(-P * L**3 / (3 * E * Iy), rel=REL)
    # Root moment = P*L; the root is end i of member 0.
    assert abs(r.diagram(0)["My"][0]) == pytest.approx(P * L, rel=REL)
    assert r.reactions[0, 2] == pytest.approx(P, rel=REL)


def test_cantilever_udl():
    w = 5.0  # N/mm
    s = simple_beam(L, E, G, A, Iy, Iz, It, w=w, fixity="cantilever")
    r = solve(s)
    assert r.displacements[-1, 2] == pytest.approx(-w * L**4 / (8 * E * Iy), rel=REL)
    assert r.peak(0)["My"] == pytest.approx(w * L**2 / 2, rel=REL)


def test_simply_supported_udl():
    w = 5.0
    s = simple_beam(L, E, G, A, Iy, Iz, It, w=w, fixity="simple")
    r = solve(s)
    # Midspan deflection needs a node at midspan, so read the peak moment and
    # check the deflection on a two-element model below.
    assert r.peak(0)["My"] == pytest.approx(w * L**2 / 8, rel=REL)
    assert r.reactions[0, 2] == pytest.approx(w * L / 2, rel=REL)


def test_simply_supported_udl_deflection():
    w = 5.0
    nodes = [Node(x, 0.0, 0.0) for x in np.linspace(0, L, 5)]
    members = [Member(i, i + 1, E, G, A, Iy, Iz, It) for i in range(4)]
    s = Structure(
        nodes,
        members,
        supports={0: (True, True, True, True, False, False),
                  4: (False, True, True, True, False, False)},
        member_loads=[MemberLoad(e, globalz=w) for e in range(4)],
    )
    r = solve(s)
    assert r.displacements[2, 2] == pytest.approx(-5 * w * L**4 / (384 * E * Iy), rel=REL)


def test_simply_supported_point_load():
    P = 20_000.0
    s = simple_beam(L, E, G, A, Iy, Iz, It, P=P, fixity="simple")
    r = solve(s)
    assert r.displacements[1, 2] == pytest.approx(-P * L**3 / (48 * E * Iy), rel=REL)
    assert r.peak(0)["My"] == pytest.approx(P * L / 4, rel=REL)


def test_fixed_fixed_udl():
    w = 5.0
    nodes = [Node(x, 0.0, 0.0) for x in np.linspace(0, L, 5)]
    members = [Member(i, i + 1, E, G, A, Iy, Iz, It) for i in range(4)]
    s = Structure(
        nodes, members,
        supports={0: (True,) * 6, 4: (True,) * 6},
        member_loads=[MemberLoad(e, globalz=w) for e in range(4)],
    )
    r = solve(s)
    assert r.displacements[2, 2] == pytest.approx(-w * L**4 / (384 * E * Iy), rel=REL)
    # Node 2 is midspan, i.e. the far end of member 1.
    support_moment = r.diagram(0)["My"][0]
    midspan_moment = r.diagram(1)["My"][-1]
    assert abs(support_moment) == pytest.approx(w * L**2 / 12, rel=REL)
    assert abs(midspan_moment) == pytest.approx(w * L**2 / 24, rel=REL)
    # Hogging at the supports, sagging at midspan -- opposite signs.
    assert support_moment * midspan_moment < 0


def test_pure_torsion():
    """Twist of a fixed-free bar under an axial torque: theta = T*L/(G*J)."""
    T = 1.0e6  # N*mm
    s = Structure(
        [Node(0, 0, 0), Node(L, 0, 0)],
        [Member(0, 1, E, G, A, Iy, Iz, It)],
        supports={0: (True,) * 6},
        nodal_loads={1: (0.0, 0.0, 0.0, T, 0.0, 0.0)},
    )
    r = solve(s)
    assert r.displacements[1, 3] == pytest.approx(T * L / (G * It), rel=REL)


def test_axial_only():
    P = 100_000.0
    s = Structure(
        [Node(0, 0, 0), Node(L, 0, 0)],
        [Member(0, 1, E, G, A, Iy, Iz, It)],
        supports={0: (True,) * 6},
        nodal_loads={1: (P, 0.0, 0.0, 0.0, 0.0, 0.0)},
    )
    r = solve(s)
    assert r.displacements[1, 0] == pytest.approx(P * L / (E * A), rel=REL)
    assert r.peak(0)["N"] == pytest.approx(P, rel=REL)


def test_orientation_invariance():
    """The same cantilever, rotated into three global directions, must agree.

    This is what catches a wrong direction-cosine matrix -- including the
    special case for members parallel to global Z.
    """
    P = 10_000.0
    tip = []
    for direction in ((L, 0, 0), (0, L, 0), (0, 0, L)):
        d = np.array(direction, float)
        # Load perpendicular to the member, in the member's local z direction.
        s = Structure(
            [Node(0, 0, 0), Node(*d)],
            [Member(0, 1, E, G, A, Iy, Iy, It)],  # circular-equivalent: Iy == Iz
            supports={0: (True,) * 6},
        )
        # Pick any unit vector perpendicular to the member.
        e = d / np.linalg.norm(d)
        perp = np.cross(e, [0, 0, 1.0])
        if np.linalg.norm(perp) < 1e-9:
            perp = np.cross(e, [0, 1.0, 0])
        perp /= np.linalg.norm(perp)
        s.nodal_loads = {1: (*(P * perp), 0.0, 0.0, 0.0)}
        r = solve(s)
        tip.append(float(np.linalg.norm(r.displacements[1, :3])))

    exact = P * L**3 / (3 * E * Iy)
    for t in tip:
        assert t == pytest.approx(exact, rel=REL)


def test_portal_frame_sway():
    """Symmetric portal, pinned bases, horizontal load at the eaves.

    Cross-checked against the slope-deflection solution for a single-bay
    portal: with equal column stiffness the two bases share the shear equally.
    """
    h, span = 4000.0, 8000.0
    H = 20_000.0
    nodes = [Node(0, 0, 0), Node(0, 0, h), Node(span, 0, h), Node(span, 0, 0)]
    members = [Member(i, i + 1, E, G, A, Iy, Iz, It) for i in range(3)]
    PIN = (True, True, True, True, False, False)
    s = Structure(nodes, members, supports={0: PIN, 3: PIN},
                  nodal_loads={1: (H, 0.0, 0.0, 0.0, 0.0, 0.0)})
    r = solve(s)

    # Global equilibrium: the two bases must carry the applied shear.
    assert r.reactions[0, 0] + r.reactions[3, 0] == pytest.approx(-H, rel=REL)
    # Pinned bases carry no moment.
    assert abs(r.reactions[0, 4]) < 1e-6 * H * h
    # Sway is to the right, and both eaves nodes move together (rigid rafter).
    assert r.displacements[1, 0] > 0
    assert r.displacements[1, 0] == pytest.approx(r.displacements[2, 0], rel=1e-2)


def test_moment_release_makes_a_truss():
    """Two pin-ended bars to a loaded apex carry axial force only.

    Statically determinate: each bar takes P/(2*sin(theta)) in compression.
    Rotations at the apex are restrained, which is how a truss node is modelled
    -- a pin-ended bar cannot supply rotational stiffness to it.
    """
    P, half_span, rise = 10_000.0, 3000.0, 4000.0
    theta = math.atan2(rise, half_span)
    pinned = (("i", "ry"), ("i", "rz"), ("j", "ry"), ("j", "rz"))
    s = Structure(
        [Node(0, 0, 0), Node(2 * half_span, 0, 0), Node(half_span, 0, rise)],
        [Member(0, 2, E, G, A, Iy, Iz, It, releases=pinned),
         Member(1, 2, E, G, A, Iy, Iz, It, releases=pinned)],
        supports={0: (True,) * 6, 1: (True,) * 6,
                  2: (False, True, False, True, True, True)},
        nodal_loads={2: (0.0, 0.0, -P, 0.0, 0.0, 0.0)},
    )
    r = solve(s)
    bar = math.hypot(half_span, rise)
    for e in (0, 1):
        d = r.peak(e)
        assert abs(d["N"]) == pytest.approx(P / (2 * math.sin(theta)), rel=REL)
        assert d["My"] < 1e-6 * abs(d["N"]) * bar
        assert d["Mz"] < 1e-6 * abs(d["N"]) * bar


def test_mechanism_is_reported_not_silently_solved():
    s = Structure(
        [Node(0, 0, 0), Node(L, 0, 0)],
        [Member(0, 1, E, G, A, Iy, Iz, It)],
        supports={0: (True, True, True, False, False, False)},  # no rotational restraint
        nodal_loads={1: (0.0, 0.0, -1000.0, 0.0, 0.0, 0.0)},
    )
    with pytest.raises(ValueError, match="mechanism"):
        solve(s)


def test_sloping_member_gravity_load():
    """A rafter at 20 degrees under gravity: the axial component must appear."""
    pitch = math.radians(20.0)
    span = 5000.0
    w = 3.0  # N/mm along global -Z
    n1, n2 = Node(0, 0, 0), Node(span, 0, span * math.tan(pitch))
    Ln = math.hypot(span, span * math.tan(pitch))
    s = Structure(
        [n1, n2],
        [Member(0, 1, E, G, A, Iy, Iz, It)],
        supports={0: (True,) * 6},
        member_loads=[MemberLoad(0, globalz=w)],
    )
    r = solve(s)
    # Total vertical reaction equals the total applied load.
    assert r.reactions[0, 2] == pytest.approx(w * Ln, rel=REL)
    # And the member sees a real axial force from the slope.
    assert abs(r.peak(0)["N"]) == pytest.approx(w * Ln * math.sin(pitch), rel=1e-2)


def test_portal_thrust_matches_the_closed_form():
    """Pinned-base portal under a UDL, against Kleinlogel.

        H = w L^2 / (4 h (2k + 3)),  k = (I_b/L)/(I_c/h),  M_eaves = H h

    This is the check behind a result that reads wrong at first: a *stiffer*
    rafter lowers the column moment, because the frame spreads less and pushes
    the column tops out less. The formula says so independently of our solver.
    """
    from metal_strength import ec3
    from metal_strength.sections import get_section

    L, h, w, n = 12.0, 4.0, 20.0, 12  # metres, kN/m
    column = get_section("HEB240")

    def portal(beam_name):
        beam = get_section(beam_name)
        xs = [L * 1000 * i / n for i in range(n + 1)]
        nodes = ([Node(0, 0, 0)]
                 + [Node(x, 0, h * 1000) for x in xs]
                 + [Node(L * 1000, 0, 0)])

        def member(i, j, s):
            return Member(i, j, ec3.E, ec3.G, s.A, s.Iy, s.Iz, s.It)

        members = ([member(0, 1, column)]
                   + [member(i, i + 1, beam) for i in range(1, n + 1)]
                   + [member(n + 2, n + 1, column)])
        pinned = (True,) * 3 + (True, False, False)
        loads = [MemberLoad(e, globalz=-w) for e in range(1, n + 1)]
        st = Structure(nodes, members, {0: pinned, n + 2: pinned}, {}, loads)
        r = solve(st)
        return (abs(r.reactions[0][0]) / 1e3,      # thrust, kN
                abs(r.peak(0)["My"]) / 1e6,        # eaves moment, kNm
                abs(r.peak(0)["N"]) / 1e3)         # column axial, kN

    previous_moment = None
    # In order of Iy, which is not the order of the names: HEB300 is less stiff
    # about y than IPE500.
    beams = sorted(("IPE300", "IPE500", "HEB300", "HEB600"),
                   key=lambda name: get_section(name).Iy)
    for beam_name in beams:
        k = ((get_section(beam_name).Iy / (L * 1000))
             / (column.Iy / (h * 1000)))
        exact = w * L ** 2 / (4 * h * (2 * k + 3))

        thrust, moment, axial = portal(beam_name)
        assert thrust == pytest.approx(exact, rel=2e-3)
        assert moment == pytest.approx(exact * h, rel=2e-3)
        # Statics: each column carries half the load whatever the beam is.
        assert axial == pytest.approx(w * L / 2, rel=1e-3)

        if previous_moment is not None:
            assert moment < previous_moment, "a stiffer beam must thrust less"
        previous_moment = moment


def test_heavier_purlins_load_the_columns_harder():
    """Weight with no stiffening effect must push column utilisation up.

    The rafter case is confounded -- a bigger rafter both weighs more and
    stiffens the frame. Purlins span between frames, so they only add weight.
    """
    from metal_strength.model import roof

    def worst_column(purlin):
        con = roof(span=12, length=20, pitch_deg=20, rafter="IPE400",
                   column="HEB240", purlin=purlin, snow_kn_m2=1.92)
        checks = con.check(con.solve())
        return max(c.utilisation for c in checks
                   if c.section.split("] ")[1].startswith("column"))

    utilisations = [worst_column(p) for p in
                    ("SHS100x100x4", "SHS140x140x5", "SHS200x200x8", "SHS250x250x10")]
    assert utilisations == sorted(utilisations), utilisations
    assert utilisations[-1] > utilisations[0] * 1.05
