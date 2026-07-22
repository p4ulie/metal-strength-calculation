"""Section properties: against published catalogue values, and against an
independent mesh-based computation.

The catalogue tests are the primary check -- they compare against numbers a
reader can look up in EN 10365 / a producer's table. The blue-prints test is
the belt-and-braces one: a completely different algorithm (finite-element mesh
integration of the actual polygon) applied to all 90 I-profiles at once.
"""

import math

import pytest

from metal_strength.sections import (
    custom_rectangle,
    custom_round,
    get_section,
    list_sections,
)

# name -> (A cm2, Iy cm4, Iz cm4, Wel_y cm3, Wpl_y cm3)
CATALOGUE = {
    "IPE200": (28.5, 1943.0, 142.4, 194.3, 220.6),
    "IPE300": (53.8, 8356.0, 603.8, 557.1, 628.4),
    "HEA200": (53.8, 3692.0, 1336.0, 388.6, 429.5),
    "HEB300": (149.1, 25170.0, 8563.0, 1678.0, 1869.0),
    "CHS114.3x5": (17.17, 257.0, 257.0, 44.9, 59.8),
    "SHS100x100x5": (18.7, 279.0, 279.0, 55.9, 66.4),
    # Iz cross-checked by hand on the sharp-cornered tube:
    # (100^3*200 - 84^3*184)/12 = 758 cm4, less the rounded corners -> 739.
    "RHS200x100x8": (44.7, 2234.0, 739.0, 223.0, 282.0),
}


@pytest.mark.parametrize("name,expected", CATALOGUE.items())
def test_against_catalogue(name, expected):
    s = get_section(name)
    got = (s.A / 1e2, s.Iy / 1e4, s.Iz / 1e4, s.Wel_y / 1e3, s.Wpl_y / 1e3)
    for label, g, e in zip(("A", "Iy", "Iz", "Wel_y", "Wpl_y"), got, expected):
        assert g == pytest.approx(e, rel=5e-3), f"{name} {label}: {g:.4g} vs {e:.4g}"


def test_torsion_and_warping_constants():
    """It and Iw for IPE300 / HEB300 against the catalogue.

    It comes from the El Darwish & Johnston approximation and runs a few per
    cent high; the tolerance below is deliberately loose and documents that.
    Iw is exact for a doubly symmetric I-section, so it is held tight.
    """
    ipe, heb = get_section("IPE300"), get_section("HEB300")
    assert ipe.It / 1e4 == pytest.approx(20.12, rel=0.06)
    assert heb.It / 1e4 == pytest.approx(185.0, rel=0.06)
    assert ipe.Iw / 1e9 == pytest.approx(125.9, rel=5e-3)  # 1e3 cm^6
    assert heb.Iw / 1e9 == pytest.approx(1688.0, rel=5e-3)
    # CHS torsion is exact: It = 2*I.
    chs = get_section("CHS114.3x5")
    assert chs.It == pytest.approx(2 * chs.Iy, rel=1e-12)


def test_name_normalisation():
    a = get_section("CHS114.3x5")
    for alias in ("chs114.3x5", "CHS 114.3 x 5", "CHS114_3x5"):
        assert get_section(alias) is a
    # A square hollow section written the long way.
    assert get_section("SHS100x100x5") is get_section("SHS100x5")


def test_unknown_profile_is_a_clear_error():
    with pytest.raises(KeyError, match="unknown profile"):
        get_section("IPE999")


def test_catalogue_is_populated():
    assert len(list_sections("IPE")) >= 15
    assert len(list_sections("HEB")) >= 20
    assert len(list_sections("CHS")) >= 100
    assert len(list_sections()) > 500


def test_derived_properties():
    s = get_section("IPE300")
    assert s.iy == pytest.approx(math.sqrt(s.Iy / s.A))
    assert s.iy > s.iz  # strong axis is stiffer
    assert s.mass_per_m == pytest.approx(42.2, rel=1e-2)  # IPE300 is 42.2 kg/m
    assert s.Wpl_y > s.Wel_y  # plastic modulus always exceeds elastic


def test_custom_shapes():
    r = custom_rectangle(20.0, 50.0)
    assert r.A == 1000.0
    assert r.Iy == pytest.approx(20 * 50**3 / 12)
    assert r.Wel_y == pytest.approx(20 * 50**2 / 6)
    assert r.Wpl_y == pytest.approx(20 * 50**2 / 4)

    c = custom_round(30.0)
    assert c.A == pytest.approx(math.pi * 30**2 / 4)
    assert c.Iy == pytest.approx(math.pi * 30**4 / 64)
    assert c.It == pytest.approx(2 * c.Iy)  # polar moment for a circle


def test_every_profile_is_self_consistent():
    """No NaNs, no negatives, and the plastic modulus always beats the elastic."""
    for name in list_sections():
        s = get_section(name)
        for field in ("A", "Iy", "Iz", "Wel_y", "Wel_z", "Wpl_y", "Wpl_z", "It", "Av_y"):
            v = getattr(s, field)
            assert math.isfinite(v) and v > 0, f"{name}.{field} = {v}"
        assert s.Wpl_y >= s.Wel_y, name
        assert s.Wpl_z >= s.Wel_z, name
        assert s.Iy >= s.Iz or s.family in ("CHS", "round"), name


@pytest.mark.slow
def test_cross_check_against_independent_mesh_computation():
    """All I-profiles vs blue-prints, which integrates the real polygon by FEM.

    Different algorithm, different author, same answer -- that is what makes
    this worth running. Skipped when the dev dependency is not installed.
    """
    bp = pytest.importorskip(
        "blueprints.structural_sections.steel.standard_profiles",
        reason="pip install blue-prints to run the independent cross-check",
    )
    checked = 0
    for family in (bp.IPE, bp.HEA, bp.HEB, bp.HEM):
        for key in family._database:
            ours = get_section(key)
            props = getattr(family, key).section_properties()
            assert ours.A == pytest.approx(props.mass, rel=2e-3), f"{key} area"
            assert ours.Wel_y == pytest.approx(props.zxx_plus, rel=5e-3), f"{key} Wel_y"
            assert ours.Wpl_y == pytest.approx(props.sxx, rel=5e-3), f"{key} Wpl_y"
            checked += 1
    assert checked >= 80
