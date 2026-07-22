"""The MCP surface: every tool registers, has a description, and round-trips.

Tool functions are called directly here; the stdio transport itself is
exercised by tests/smoke_mcp.py.
"""

import asyncio

import pytest

from metal_strength import mcp_server as srv

EXPECTED_TOOLS = {
    "snow_load_from_depth", "snow_load_eurocode", "list_sections",
    "section_properties", "check_beam", "check_rod_buckling", "check_roof",
    "solve_frame", "render_snow_cases", "propose_construction", "material_list",
    "list_shapes",
}


def test_list_shapes_tool_matches_the_shapes_module():
    from metal_strength import loads, shapes

    listed = srv.list_shapes_tool()["shapes"]
    assert [e["shape"] for e in listed] == list(shapes.SHAPES)
    for entry in listed:
        assert entry["snow_cases"] == list(loads.ARRANGEMENTS[entry["shape"]])
        assert entry["description"]


def test_check_roof_reports_the_shape_and_flags_approximate_mu():
    plain = srv.check_roof(span_m=12.0, length_m=15.0, pitch_deg=20.0,
                           snow_depth_m=0.5, rafter="IPE450", column="HEB240",
                           purlin="SHS140x140x5")
    assert plain.shape == "duopitch" and not plain.mu_approximate

    mansard = srv.check_roof(span_m=12.0, length_m=15.0, pitch_deg=20.0,
                             snow_depth_m=0.5, shape="mansard", rafter="IPE450",
                             column="HEB240", purlin="SHS140x140x5")
    assert mansard.shape == "mansard" and mansard.mu_approximate


def test_all_tools_registered_with_descriptions():
    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, EXPECTED_TOOLS - names
    for t in tools:
        assert t.description and len(t.description) > 40, f"{t.name} needs a description"
        assert t.inputSchema["type"] == "object"


def test_snow_from_depth_tool():
    r = srv.snow_load_from_depth(1.0, "wet", pitch_deg=20.0)
    assert r.sk_kn_m2 == 4.0
    assert len(r.cases) == 3
    # mu1 = 0.8 at 20 degrees, Ce = 1.0
    assert r.cases[0]["left_kn_m2"] == pytest.approx(3.2)
    assert r.cases[1]["right_kn_m2"] == pytest.approx(1.6)


def test_snow_eurocode_tool():
    r = srv.snow_load_eurocode(zone=2, altitude_m=400, region="central_east")
    assert r.sk_kn_m2 > 0
    assert "Annex C" in r.explanation


def test_section_properties_tool():
    r = srv.section_properties("IPE300")
    assert r.area_cm2 == pytest.approx(53.8, rel=5e-3)
    assert r.Wpl_y_cm3 == pytest.approx(628.4, rel=5e-3)
    assert r.mass_kg_per_m == pytest.approx(42.2, rel=1e-2)


def test_list_sections_tool():
    r = srv.list_sections_tool("IPE")
    assert r["count"] >= 15
    assert all(n.startswith("IPE") for n in r["names"])


def test_check_beam_tool():
    r = srv.check_beam(6.0, "IPE200", "S235", udl_kn_per_m=5.0, restrained=True)
    assert r.ok
    assert 0 < r.worst_utilisation < 1.0
    assert r.deflection_mm == pytest.approx(20.7, rel=2e-2)
    assert r.worst_members[0].checks
    assert r.disclaimer

    # An obviously undersized beam must fail, not quietly pass.
    bad = srv.check_beam(12.0, "IPE100", "S235", udl_kn_per_m=20.0)
    assert not bad.ok and bad.worst_utilisation > 1.0


def test_check_rod_buckling_tool():
    r = srv.check_rod_buckling(6.0, "IPE300", "S235", axial_load_kn=200.0)
    # Hand-checked in tests/test_ec3.py: Nb,z = 288 kN at 6 m.
    assert r["buckling_zz"]["N_b_Rd_kn"] == pytest.approx(288.0, rel=5e-3)
    assert r["capacity_kn"] == pytest.approx(288.0, rel=5e-3)
    assert r["utilisation"] == pytest.approx(200 / 288, rel=1e-2)
    assert r["ok"]
    # A longer strut must be weaker.
    assert srv.check_rod_buckling(9.0, "IPE300")["capacity_kn"] < r["capacity_kn"]


def test_check_roof_tool_the_headline_question():
    """Will a 12 m span roof hold 1 m of wet snow?"""
    r = srv.check_roof(span_m=12.0, length_m=20.0, pitch_deg=20.0,
                       snow_depth_m=1.0, snow_state="wet",
                       rafter="IPE300", column="HEB200")
    assert not r.ok, "IPE300 on 12 m under 4 kN/m2 must not pass"
    assert r.members_checked > 50
    assert r.worst_utilisation > 1.0

    # Sized up, it should pass.
    good = srv.check_roof(span_m=12.0, length_m=20.0, pitch_deg=20.0,
                          snow_depth_m=1.0, snow_state="wet",
                          rafter="IPE450", column="HEB240", purlin="SHS140x140x5")
    assert good.ok, f"worst {good.worst_utilisation} in {good.governing_member}"


def test_check_roof_requires_a_snow_input():
    with pytest.raises(ValueError, match="snow_depth_m or snow_kn_m2"):
        srv.check_roof(span_m=10.0, length_m=10.0)


def test_drift_cases_differ_from_balanced():
    common = dict(span_m=12.0, length_m=15.0, pitch_deg=30.0, snow_kn_m2=2.0,
                  rafter="IPE360", column="HEB220")
    balanced = srv.check_roof(**common, case="balanced")
    drift = srv.check_roof(**common, case="drift_left")
    assert balanced.worst_utilisation != drift.worst_utilisation


def test_solve_frame_tool():
    """A portal frame given explicitly, rather than generated."""
    from metal_strength.model import LoadSpec, MemberSpec, NodeSpec, StructureSpec

    spec = StructureSpec(
        nodes=[NodeSpec(x=0, z=0), NodeSpec(x=0, z=4), NodeSpec(x=8, z=4),
               NodeSpec(x=8, z=0)],
        members=[MemberSpec(i=0, j=1, section="HEB200"),
                 MemberSpec(i=1, j=2, section="IPE300"),
                 MemberSpec(i=2, j=3, section="HEB200")],
        supports={0: "pinned", 3: "pinned"},
        member_loads=[LoadSpec(member=1, udl_z=10.0)],
    )
    r = srv.solve_frame(spec)
    assert r.members_checked == 3
    assert r.worst_utilisation > 0
    assert r.deflection_mm > 0


def test_charts_are_produced_on_request(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "CHARTS", tmp_path)
    r = srv.check_beam(6.0, "IPE200", udl_kn_per_m=5.0, charts=True)
    assert len(r.charts) == 2
    for path in r.charts:
        from pathlib import Path
        assert Path(path).exists() and Path(path).stat().st_size > 1000


def test_render_snow_cases(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(srv, "CHARTS", tmp_path)
    p = srv.render_snow_cases(2.0, 25.0)["path"]
    assert Path(p).exists()
