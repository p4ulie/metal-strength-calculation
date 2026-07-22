"""EN 1991-1-3 snow actions and EN 1990 combinations."""

import math

import pytest

from metal_strength import loads


def test_module_self_check():
    loads.demo()  # the assertions live with the code


@pytest.mark.parametrize("state,expected", [
    ("fresh", 1.0), ("settled", 2.0), ("old", 3.5), ("wet", 4.0)])
def test_one_metre_of_snow(state, expected):
    """The headline number: what does a metre of snow actually weigh."""
    assert loads.snow_from_depth(1.0, state) == expected


def test_depth_scales_linearly():
    assert loads.snow_from_depth(0.5, "wet") == 2.0
    assert loads.snow_from_depth(2.0, "settled") == 4.0
    assert loads.snow_from_depth(0.0, "wet") == 0.0


def test_bad_inputs_are_rejected():
    with pytest.raises(ValueError, match="state"):
        loads.snow_from_depth(1.0, "slushy")
    with pytest.raises(ValueError, match="negative"):
        loads.snow_from_depth(-1.0)
    with pytest.raises(ValueError, match="exposure"):
        loads.roof_snow_load(2.0, 20, exposure="breezy")
    with pytest.raises(ValueError, match="region"):
        loads.sk_from_zone(2, 400, "atlantis")


@pytest.mark.parametrize("pitch,expected", [
    (0, 0.8), (15, 0.8), (30, 0.8), (45, 0.4), (60, 0.0), (75, 0.0)])
def test_shape_coefficient(pitch, expected):
    assert loads.mu1(pitch) == pytest.approx(expected)


def test_snow_guards_hold_the_snow_on_a_steep_roof():
    assert loads.mu1(50) == pytest.approx(0.8 * 10 / 30)
    assert loads.mu1(50, snow_guards=True) == 0.8
    assert loads.mu1(80, snow_guards=True) == 0.8


def test_negative_pitch_is_treated_as_its_magnitude():
    assert loads.mu1(-20) == loads.mu1(20)


def test_exposure_scales_the_load():
    sk = 2.0
    windswept = loads.roof_snow_load(sk, 0, exposure="windswept")[0].left
    normal = loads.roof_snow_load(sk, 0, exposure="normal")[0].left
    sheltered = loads.roof_snow_load(sk, 0, exposure="sheltered")[0].left
    assert windswept < normal < sheltered
    assert normal == pytest.approx(0.8 * sk)
    assert sheltered == pytest.approx(1.2 * normal)


def test_duopitch_gives_three_arrangements():
    cases = loads.roof_snow_load(2.0, 20, "duopitch")
    assert [c.name for c in cases] == ["balanced", "drift_left", "drift_right"]
    full = cases[0].left
    assert cases[1].left == full and cases[1].right == pytest.approx(full / 2)
    assert cases[2].left == pytest.approx(full / 2) and cases[2].right == full
    assert all(c.governing == full for c in cases)


def test_monopitch_gives_one():
    assert len(loads.roof_snow_load(2.0, 20, "monopitch")) == 1


def test_annex_c_altitude_effect():
    """sk rises with the square of altitude and vanishes at zone 0."""
    sea = loads.sk_from_zone(2, 0)
    high = loads.sk_from_zone(2, 1000)
    assert high > 3 * sea
    a, b, div = loads.REGIONS["central_east"]
    assert sea == pytest.approx(a * 2 + b)
    assert high == pytest.approx((a * 2 + b) * (1 + (1000 / div) ** 2))


def test_regions_have_distinct_formulas():
    """Each region has its own zone factor and altitude divisor.

    Do not compare regions at the same zone number -- a zone 2 in the Alpine
    map is not the same climate as a zone 2 in the Central East map. The
    formulas are only meaningful with the zone/altitude pairing taken off that
    region's own national map.
    """
    at_altitude = {r: loads.sk_from_zone(2, 600, r) for r in loads.REGIONS}
    assert len({round(v, 6) for v in at_altitude.values()}) > 3
    # Every region must still rise with altitude.
    for region in loads.REGIONS:
        assert loads.sk_from_zone(2, 600, region) > loads.sk_from_zone(2, 0, region)


def test_slope_udl_projects_onto_the_rafter():
    """Snow acts on the plan projection, so a sloping rafter picks up s*w*cos(a)."""
    assert loads.slope_udl(2.0, 1.5, 0) == pytest.approx(3.0)
    assert loads.slope_udl(2.0, 1.5, 30) == pytest.approx(3.0 * math.cos(math.radians(30)))
    assert loads.slope_udl(2.0, 1.5, 60) == pytest.approx(1.5)


def test_self_weight_uses_the_eurocode_unit_weight():
    """EN 1991-1-1 Table A.4 gives steel as 77.0-78.5 kN/m3.

    We take the conservative 78.5, which is ~2% above the weight implied by the
    7850 kg/m3 used for the catalogue mass. Deliberate, and on the safe side
    for a load.
    """
    from metal_strength.sections import get_section
    ipe = get_section("IPE300")
    assert loads.self_weight_udl(ipe.A) == pytest.approx(0.4224, rel=1e-3)
    mass_derived = ipe.mass_per_m * 9.81 / 1000  # 42.2 kg/m -> 0.414 kN/m
    assert 1.0 < loads.self_weight_udl(ipe.A) / mass_derived < 1.03


def test_load_combinations():
    assert loads.ULS.apply(1.0, 2.0) == pytest.approx(1.35 + 3.0)
    assert loads.SLS.apply(1.0, 2.0) == pytest.approx(3.0)
    # Uplift: permanent load is favourable, so it is not amplified.
    assert loads.ULS_UPLIFT.apply(1.0, 2.0) == pytest.approx(1.0 + 3.0)
