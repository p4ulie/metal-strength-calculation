"""EN 1993-1-1 checks against fully hand-worked values.

Each expected number below is derived by hand in the comment above it, so a
reviewer can re-do the arithmetic without trusting the code.
"""

import math

import pytest

from metal_strength import ec3
from metal_strength.sections import get_section


def test_flexural_buckling_hand_calculation():
    """IPE300, S235, Lcr,z = 6.0 m.

    iz  = sqrt(604e4 / 5381)            = 33.51 mm
    l1  = 93.9 * eps = 93.9
    lam = (6000 / 33.51) / 93.9         = 1.907
    curve b -> alpha = 0.34
    Phi = 0.5(1 + 0.34(1.907-0.2) + 1.907^2) = 2.608
    chi = 1/(2.608 + sqrt(2.608^2 - 1.907^2)) = 0.2279
    Nb  = 0.2279 * 5381 * 235           = 288 kN
    """
    s = get_section("IPE300")
    Nb, x, lam = ec3.flexural_buckling(s, 235.0, 6000.0, "z")
    assert lam == pytest.approx(1.907, rel=2e-3)
    assert x == pytest.approx(0.2279, rel=5e-3)
    assert Nb / 1e3 == pytest.approx(288.0, rel=5e-3)


def test_chi_matches_the_closed_form():
    for curve, a in ec3.ALPHA.items():
        for lam in (0.3, 0.8, 1.5, 2.5):
            phi = 0.5 * (1 + a * (lam - 0.2) + lam**2)
            expected = min(1.0, 1 / (phi + math.sqrt(phi**2 - lam**2)))
            assert ec3.chi(lam, curve) == pytest.approx(expected, rel=1e-12)


def test_critical_moment_hand_calculation():
    """IPE300 over 6.0 m, C1 = 1.0 (uniform moment).

    Iz = 604e4, Iw = 1.263e11 mm^6, It = 2.06e5 mm^4
    Mcr = pi^2 E Iz / L^2 * sqrt(Iw/Iz + L^2 G It / (pi^2 E Iz))
    """
    s = get_section("IPE300")
    L = 6000.0
    expected = (math.pi**2 * ec3.E * s.Iz / L**2) * math.sqrt(
        s.Iw / s.Iz + L**2 * ec3.G * s.It / (math.pi**2 * ec3.E * s.Iz)
    )
    assert ec3.critical_moment(s, L, C1=1.0) == pytest.approx(expected, rel=1e-12)
    # And C1 scales it linearly.
    assert ec3.critical_moment(s, L, C1=1.13) == pytest.approx(1.13 * expected, rel=1e-12)


def test_ltb_reduces_capacity_with_unrestrained_length():
    s = get_section("IPE300")
    caps = [ec3.lateral_torsional_buckling(s, 235.0, 1, L)[0] for L in (1000, 3000, 6000, 9000)]
    assert caps == sorted(caps, reverse=True), "capacity must fall as length grows"
    assert caps[0] == pytest.approx(s.Wpl_y * 235.0, rel=1e-12)  # no reduction when short


def test_closed_sections_are_immune_to_ltb():
    for name in ("SHS100x100x5", "CHS114.3x5"):
        Mb, x, lam = ec3.lateral_torsional_buckling(get_section(name), 235.0, 1, 10_000.0)
        assert x == 1.0 and lam == 0.0


def test_classification():
    # IPE300 S235 in pure bending: class 1.
    assert ec3.classify(get_section("IPE300"), 235.0, M=1e8)[0] == 1
    # IPE600 in S355 has a slender web; must not silently claim class 1.
    cls, _ = ec3.classify(get_section("IPE600"), 355.0, M=1e9)
    assert cls >= 1
    # Solid bars never buckle locally.
    from metal_strength.sections import custom_rectangle
    assert ec3.classify(custom_rectangle(20, 100), 235.0, M=1e6)[0] == 1


def test_class_4_is_flagged_not_silently_reported():
    """A very slender fabricated section must warn, not return a resistance."""
    from metal_strength.sections import Section
    slender = Section("fake", "I", A=5000, h=1000, b=200, tw=3, tf=4, r=0,
                      Iy=1e9, Iz=1e6, Wel_y=2e6, Wel_z=1e4, Wpl_y=2.3e6, Wpl_z=1.5e4,
                      It=1e4, Iw=1e11, Av_y=3000, Av_z=1600)
    cls, warns = ec3.classify(slender, 355.0, M=1e8)
    assert cls == 4
    assert any("class 4" in w for w in warns)


def test_bending_utilisation_end_to_end():
    """IPE300 S235, laterally restrained, My = 100 kNm.

    Mc,Rd = Wpl * fy = 628.4e3 * 235 = 147.7 kNm  ->  utilisation 0.68
    """
    s = get_section("IPE300")
    r = ec3.check_member(
        s, "S235",
        ec3.MemberForces(My=100e6),
        ec3.BucklingLengths(Lcr_y=6000, Lcr_z=6000, L_LT=0.0),  # fully restrained
    )
    bend = next(c for c in r.checks if c.name.startswith("bending y"))
    assert bend.capacity / 1e6 == pytest.approx(147.7, rel=5e-3)
    assert bend.utilisation == pytest.approx(0.677, rel=5e-3)


def test_shear_moment_interaction_only_bites_above_half():
    s = get_section("IPE300")
    lengths = ec3.BucklingLengths(6000, 6000, 0.0)
    Vpl = s.Av_y * (235.0 / math.sqrt(3))

    low = ec3.check_member(s, "S235", ec3.MemberForces(My=100e6, Vz=0.3 * Vpl), lengths)
    high = ec3.check_member(s, "S235", ec3.MemberForces(My=100e6, Vz=0.9 * Vpl), lengths)
    cap = lambda r: next(c for c in r.checks if c.name.startswith("bending y")).capacity
    assert cap(low) == pytest.approx(s.Wpl_y * 235.0, rel=1e-9)
    assert cap(high) < cap(low)


def test_deflection_check():
    s = get_section("IPE300")
    r = ec3.check_member(s, "S235", ec3.MemberForces(My=1e6),
                         ec3.BucklingLengths(6000, 6000, 0.0),
                         deflection=25.0, span=6000.0)
    d = next(c for c in r.checks if c.name.startswith("deflection"))
    assert d.capacity == pytest.approx(30.0)  # 6000 / 200
    assert d.ok


def test_combined_axial_and_bending_is_worse_than_either_alone():
    s = get_section("HEB200")
    lengths = ec3.BucklingLengths(4000, 4000, 4000)
    only_n = ec3.check_member(s, "S355", ec3.MemberForces(N=-400e3), lengths)
    only_m = ec3.check_member(s, "S355", ec3.MemberForces(My=80e6), lengths)
    both = ec3.check_member(s, "S355", ec3.MemberForces(N=-400e3, My=80e6), lengths)
    assert both.utilisation > max(only_n.utilisation, only_m.utilisation)
    assert any("6.61" in c.clause for c in both.checks)


def test_grade_thickness_bands():
    assert ec3.yield_strength("S355", 40.0) == (355.0, 490.0)
    assert ec3.yield_strength("S355", 40.1) == (335.0, 470.0)
    with pytest.raises(ValueError):
        ec3.yield_strength("S355", 100.0)
    with pytest.raises(ValueError):
        ec3.yield_strength("S999", 10.0)
