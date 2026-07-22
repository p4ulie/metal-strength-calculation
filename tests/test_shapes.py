"""Profile geometry: every shape must build something a solver can stand on."""

from __future__ import annotations

import math

import pytest

from metal_strength import shapes


@pytest.mark.parametrize("shape", shapes.SHAPES)
def test_every_shape_builds(shape):
    f = shapes.frame(shape, span=12.0, pitch_deg=20.0, eaves_height=3.0)
    assert f.shape == shape
    assert f.span == pytest.approx(12.0)
    assert f.points[0] == (0.0, 3.0)
    assert f.points[-1][0] == pytest.approx(12.0)
    # x strictly increases, which is what the purlin logic relies on.
    xs = [x for x, _ in f.points]
    assert all(b > a for a, b in zip(xs, xs[1:]))


@pytest.mark.parametrize("shape", shapes.SHAPES)
def test_every_shape_has_a_description(shape):
    assert shapes.DESCRIPTIONS[shape]


def test_duopitch_apex_and_symmetry():
    f = shapes.frame("duopitch", span=12.0, pitch_deg=20.0, eaves_height=3.0)
    assert f.apex_height == pytest.approx(3.0 + 6.0 * math.tan(math.radians(20)))
    assert f.pitches() == pytest.approx((20.0, 20.0))
    assert len(f.rafters) == 2
    assert f.valleys == ()


def test_flat_ignores_pitch():
    f = shapes.frame("flat", span=8.0, pitch_deg=30.0, eaves_height=4.0)
    assert f.apex_height == pytest.approx(4.0)
    assert f.pitches() == pytest.approx((0.0,))


def test_monopitch_rises_the_whole_way():
    f = shapes.frame("monopitch", span=10.0, pitch_deg=15.0, eaves_height=3.0)
    assert len(f.rafters) == 1
    assert f.apex_height == pytest.approx(3.0 + 10.0 * math.tan(math.radians(15)))


def test_mansard_lower_slope_is_steeper_than_the_pitch():
    f = shapes.frame("mansard", span=12.0, pitch_deg=20.0, eaves_height=3.0)
    lower, upper = f.pitches()[0], f.pitches()[1]
    assert lower == pytest.approx(shapes.MANSARD_LOWER_DEG)
    assert upper == pytest.approx(20.0)
    assert lower > upper
    # Mirrored: four rafter segments, symmetric about mid-span.
    assert len(f.rafters) == 4
    assert f.pitches()[2] == pytest.approx(-(-upper))
    assert f.points[1][1] == pytest.approx(f.points[-2][1])


def test_gambrel_breaks_at_mid_slope():
    f = shapes.frame("gambrel", span=12.0, pitch_deg=20.0, eaves_height=3.0)
    assert f.points[1][0] == pytest.approx(3.0)  # (1 - 0.5) * half-span
    assert f.pitches()[0] == pytest.approx(shapes.GAMBREL_LOWER_DEG)


@pytest.mark.parametrize("shape", ["sawtooth", "multispan"])
def test_repeating_shapes_put_a_column_under_every_valley(shape):
    span = 30.0
    f = shapes.frame(shape, span=span, pitch_deg=15.0, eaves_height=3.0)
    n = max(2, round(span / shapes.BAY_TARGET_M))
    assert len(f.valleys) == n - 1  # interior valleys only
    columns = [s for s in f.segments if s.role == "column"]
    assert len(columns) == n + 1  # two ends plus one per valley
    assert all(s.z0 == 0.0 for s in columns)


def test_sawtooth_face_is_steep():
    f = shapes.frame("sawtooth", span=20.0, pitch_deg=15.0, eaves_height=3.0)
    steep = max(f.pitches())
    assert steep == pytest.approx(shapes.SAWTOOTH_FACE_DEG)


def test_sawtooth_needs_a_pitch():
    with pytest.raises(ValueError, match="pitch"):
        shapes.frame("sawtooth", span=20.0, pitch_deg=0.0, eaves_height=3.0)


def test_custom_profile_round_trips():
    pts = [(0.0, 3.0), (4.0, 5.0), (8.0, 3.5), (10.0, 4.5), (12.0, 3.0)]
    f = shapes.from_points(pts)
    assert f.shape == "custom"
    assert f.points == tuple(pts)
    assert f.valleys == (2,)  # the dip gets its own column
    assert f.mu_is_approximate


@pytest.mark.parametrize("bad", [
    [(0.0, 3.0)],                                  # too short
    [(0.0, 3.0), (0.0, 5.0)],                      # vertical, x does not advance
    [(0.0, 3.0), (5.0, 4.0), (2.0, 3.0)],          # doubles back
    [(0.0, 3.0), (5.0, 0.0)],                      # touches the ground
])
def test_invalid_profiles_are_refused(bad):
    with pytest.raises(ValueError):
        shapes.from_points(bad)


def test_unknown_shape_is_refused():
    with pytest.raises(ValueError, match="shape must be one of"):
        shapes.frame("onion-dome", span=12.0, pitch_deg=20.0, eaves_height=3.0)


# --- the structures these profiles generate ---------------------------------


@pytest.mark.parametrize("shape", shapes.SHAPES)
def test_every_shape_builds_a_solvable_roof(shape):
    from metal_strength.model import roof

    con = roof(span=24.0, length=15.0, pitch_deg=18.0, shape=shape,
               rafter="IPE400", column="HEB240", purlin="SHS140x140x5",
               snow_kn_m2=1.6)
    checks = con.check(con.solve())
    assert checks and all(c.utilisation >= 0 for c in checks)
    assert con.profile.shape == shape
    # Every column base is supported, and nothing floats.
    assert con.spec.supports


def test_duopitch_is_unchanged_by_the_refactor():
    """roof(shape="duopitch") must be exactly what pitched_roof always built."""
    from metal_strength.model import pitched_roof, roof

    kwargs = dict(span=12.0, length=20.0, pitch_deg=20.0, rafter="IPE450",
                  column="HEB240", purlin="SHS140x140x5", snow_kn_m2=1.92)
    old = pitched_roof(**kwargs)
    new = roof(shape="duopitch", **kwargs)
    assert len(old.spec.nodes) == len(new.spec.nodes)
    assert len(old.spec.members) == len(new.spec.members)
    assert (max(c.utilisation for c in old.check()) ==
            pytest.approx(max(c.utilisation for c in new.check())))


def test_valley_drift_is_heavier_than_balanced():
    from metal_strength.model import roof

    kwargs = dict(span=30.0, length=15.0, pitch_deg=15.0, shape="multispan",
                  rafter="IPE400", column="HEB240", purlin="SHS140x140x5",
                  snow_kn_m2=1.6)
    balanced = roof(snow_case="balanced", **kwargs)
    drifted = roof(snow_case="valley_drift", **kwargs)
    assert (max(c.utilisation for c in drifted.check()) >
            max(c.utilisation for c in balanced.check()))


def test_a_shape_refuses_an_arrangement_it_cannot_have():
    from metal_strength.model import roof

    with pytest.raises(ValueError, match="monopitch"):
        roof(span=12.0, length=10.0, pitch_deg=15.0, shape="monopitch",
             snow_case="drift_left")


def test_snow_arrangements_follow_the_shape():
    from metal_strength import loads

    mono = loads.snow_arrangements(
        shapes.frame("monopitch", 12.0, 15.0, 3.0), sk=2.0)
    assert [c.name for c in mono] == ["balanced"]
    assert len(mono[0].values) == 1

    mansard = loads.snow_arrangements(
        shapes.frame("mansard", 12.0, 15.0, 3.0), sk=2.0)
    assert [c.name for c in mansard] == ["balanced", "drift_left", "drift_right"]
    assert len(mansard[0].values) == 4
    # A drift halves the leeward side only.
    assert mansard[1].values[:2] == pytest.approx(mansard[0].values[:2])
    assert mansard[1].values[2:] == pytest.approx(
        tuple(v / 2 for v in mansard[0].values[2:]))

    valley = loads.snow_arrangements(
        shapes.frame("multispan", 30.0, 15.0, 3.0), sk=2.0)
    assert [c.name for c in valley] == ["balanced", "valley_drift"]
    assert max(valley[1].values) == pytest.approx(2 * max(valley[0].values))


def test_snowcase_left_and_right_still_work():
    from metal_strength import loads

    cases = loads.roof_snow_load(2.0, 20.0)
    assert cases[0].left == cases[0].values[0]
    assert cases[1].right == cases[1].values[-1]


def test_snow_slides_off_the_steep_parts():
    """A mansard's 60deg lower slope and a sawtooth face carry no snow."""
    from metal_strength import loads

    mansard = shapes.frame("mansard", 12.0, 20.0, 3.0)
    balanced = loads.case_factors(mansard, "balanced")
    lower = [f for f, seg in zip(balanced, mansard.segments)
             if seg.role == "rafter" and abs(seg.pitch_deg) > 45]
    assert lower and all(f == pytest.approx(0.0, abs=1e-9) for f in lower)

    # Snow guards hold it there, so the same slope loads up again.
    with_guards = loads.case_factors(mansard, "balanced", snow_guards=True)
    lower_guarded = [f for f, seg in zip(with_guards, mansard.segments)
                     if seg.role == "rafter" and abs(seg.pitch_deg) > 45]
    assert all(f == pytest.approx(1.0) for f in lower_guarded)
