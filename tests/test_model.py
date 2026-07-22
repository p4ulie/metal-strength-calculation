"""The metres/kN boundary layer and the roof generator."""

import math

import pytest

from metal_strength.model import (
    LoadSpec,
    MemberSpec,
    NodeSpec,
    StructureSpec,
    build,
    pitched_roof,
    single_beam,
)


def test_units_are_converted_at_the_boundary():
    spec = StructureSpec(
        nodes=[NodeSpec(x=0), NodeSpec(x=6)],
        members=[MemberSpec(i=0, j=1, section="IPE200")],
        supports={0: "fixed"},
        point_loads=[LoadSpec(node=1, fz=-10.0)],  # kN
        member_loads=[LoadSpec(member=0, udl_z=5.0)],  # kN/m
    )
    s, sections, grades = build(spec)
    assert s.nodes[1].x == 6000.0  # metres -> mm
    assert s.nodal_loads[1][2] == -10_000.0  # kN -> N
    assert s.member_loads[0].globalz == 5.0  # kN/m is exactly N/mm
    assert sections[0].name == "IPE200" and grades == ["S235"]


def test_unknown_support_is_rejected():
    spec = StructureSpec(nodes=[NodeSpec(x=0), NodeSpec(x=1)],
                         members=[MemberSpec(i=0, j=1)], supports={0: "welded"})
    with pytest.raises(ValueError, match="support must be"):
        build(spec)


def test_spec_round_trips_through_json():
    """The MCP wire format must survive serialisation."""
    spec = StructureSpec(
        nodes=[NodeSpec(x=0), NodeSpec(x=0, z=4), NodeSpec(x=8, z=4)],
        members=[MemberSpec(i=0, j=1, section="HEB200"),
                 MemberSpec(i=1, j=2, section="IPE300", pinned=True)],
        supports={0: "pinned"},
    )
    again = StructureSpec.model_validate_json(spec.model_dump_json())
    assert again == spec


def test_single_beam_reproduces_the_closed_form():
    beam = single_beam(6.0, "IPE300", udl_kn_m=5.0)
    r = beam.solve()
    peak = max(r.peak(e)["My"] for e in range(len(beam.spec.members)))
    assert peak / 1e6 == pytest.approx(5 * 6**2 / 8, rel=2e-3)  # wL^2/8 = 22.5 kNm


def test_restrained_beam_has_no_ltb_penalty():
    free = single_beam(8.0, "IPE200", udl_kn_m=3.0, restrained=False)
    held = single_beam(8.0, "IPE200", udl_kn_m=3.0, restrained=True)
    assert max(c.utilisation for c in held.check()) < \
           max(c.utilisation for c in free.check())


def test_roof_geometry():
    span, length, pitch = 12.0, 20.0, 20.0
    roof = pitched_roof(span=span, length=length, pitch_deg=pitch,
                        eaves_height=3.0, frame_spacing=5.0, snow_kn_m2=2.0)
    xs = [n.x for n in roof.spec.nodes]
    ys = [n.y for n in roof.spec.nodes]
    zs = [n.z for n in roof.spec.nodes]
    assert min(xs) == 0.0 and max(xs) == pytest.approx(span)
    assert min(ys) == 0.0 and max(ys) == pytest.approx(length)
    assert min(zs) == 0.0
    # Apex height = eaves + half-span * tan(pitch)
    assert max(zs) == pytest.approx(3.0 + (span / 2) * math.tan(math.radians(pitch)))
    # Five frames at 5 m over 20 m, each with two bases.
    assert sum(1 for k in roof.spec.supports) == 10


def test_roof_members_are_tagged_by_role():
    roof = pitched_roof(span=10.0, length=10.0, pitch_deg=15.0, snow_kn_m2=2.0)
    tags = [m.tag for m in roof.spec.members]
    assert any(t.startswith("column") for t in tags)
    assert any(t.startswith("rafter") for t in tags)
    assert any(t.startswith("purlin") for t in tags)


def test_purlins_shorten_the_ltb_length_of_the_rafter():
    """Purlins restrain the rafter, so LTB uses the purlin spacing, not the span."""
    roof = pitched_roof(span=12.0, length=15.0, pitch_deg=20.0,
                        purlin_spacing=1.5, snow_kn_m2=2.0)
    rafters = [e for e, m in enumerate(roof.spec.members) if m.tag.startswith("rafter")]
    for e in rafters:
        assert roof.lt_lengths[e] < 2000.0  # mm, i.e. about the purlin spacing


def test_more_snow_means_more_utilisation():
    common = dict(span=12.0, length=15.0, pitch_deg=20.0, rafter="IPE400",
                  column="HEB240", purlin="SHS140x140x5")
    light = pitched_roof(**common, snow_kn_m2=1.0)
    heavy = pitched_roof(**common, snow_kn_m2=4.0)
    u_light = max(c.utilisation for c in light.check())
    u_heavy = max(c.utilisation for c in heavy.check())
    assert u_heavy > 2 * u_light


def test_bigger_section_lowers_utilisation():
    common = dict(span=12.0, length=15.0, pitch_deg=20.0, snow_kn_m2=3.0,
                  column="HEB300", purlin="SHS160x160x8")
    utils = [max(c.utilisation for c in
                 pitched_roof(**common, rafter=r).check())
             for r in ("IPE300", "IPE400", "IPE500")]
    assert utils == sorted(utils, reverse=True), utils


def test_drift_cases_are_unsymmetric():
    common = dict(span=12.0, length=10.0, pitch_deg=20.0, snow_kn_m2=2.0)
    balanced = pitched_roof(**common, snow_case="balanced")
    drift = pitched_roof(**common, snow_case="drift_left")
    rb = balanced.solve()
    rd = drift.solve()
    # A balanced case gives a symmetric structure symmetric reactions; a drift
    # case does not.
    left_b = rb.reactions[0, 2]
    left_d = rd.reactions[0, 2]
    assert left_b != pytest.approx(left_d, rel=1e-3)


def test_bad_roof_geometry_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        pitched_roof(span=0.0, length=10.0, pitch_deg=20.0)
    with pytest.raises(ValueError, match="pitch"):
        pitched_roof(span=10.0, length=10.0, pitch_deg=70.0)
    with pytest.raises(ValueError, match="snow_case"):
        pitched_roof(span=10.0, length=10.0, pitch_deg=20.0, snow_case="blizzard")


def test_deflection_check_uses_the_span():
    roof = pitched_roof(span=12.0, length=15.0, pitch_deg=20.0, snow_kn_m2=2.0)
    d = roof.deflection(roof.solve())
    assert d.capacity == pytest.approx(12_000 / 200)
    assert d.demand > 0


def test_flat_roof_still_builds():
    """Zero pitch is degenerate geometry -- it must not divide by zero."""
    roof = pitched_roof(span=8.0, length=10.0, pitch_deg=0.0, snow_kn_m2=2.0)
    r = roof.solve()
    assert abs(r.displacements[:, 2]).max() > 0
