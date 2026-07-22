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
    "list_shapes", "tune_roof",
}


def test_tune_roof_keeps_state_between_calls():
    srv.tune_roof(reset=True, chart=False)
    first = srv.tune_roof(shape="multispan", span_m=30.0, chart=False)[0]
    assert first["changed"] == {"span_m": 30.0, "shape": "multispan"}
    assert first["parameters"]["rafter"] == srv.TUNE_DEFAULTS["rafter"]

    # One nudge: everything else must survive.
    second = srv.tune_roof(rafter="IPE500", chart=False)[0]
    assert second["changed"] == {"rafter": "IPE500"}
    assert second["parameters"]["span_m"] == 30.0
    assert second["parameters"]["shape"] == "multispan"
    assert second["snow_cases_available"] == ["balanced", "valley_drift"]

    # Heavier section, same load: utilisation must come down, mass must go up.
    assert second["worst_utilisation"] < first["worst_utilisation"]
    assert second["total_mass_kg"] > first["total_mass_kg"]

    back = srv.tune_roof(reset=True, chart=False)[0]
    assert back["parameters"] == srv.TUNE_DEFAULTS


def test_tune_roof_returns_a_chart_and_a_depth_overrides_a_direct_load():
    srv.tune_roof(reset=True, chart=False)
    out = srv.tune_roof(snow_kn_m2=4.0, chart=True)
    state, image = out
    assert state["snow_kn_m2_applied"] == 4.0
    assert image.to_image_content().data, "the chart must come back inline"

    # Naming a depth afterwards means the depth is what you now mean.
    state = srv.tune_roof(snow_depth_m=0.5, chart=False)[0]
    assert state["parameters"]["snow_kn_m2"] is None
    assert state["snow_kn_m2_applied"] == pytest.approx(0.8 * 2.0, rel=1e-3)


def test_tune_roof_is_json_safe():
    import json

    state = srv.tune_roof(reset=True, chart=False)[0]
    json.dumps(state)  # numpy scalars would raise here


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


def test_a_window_and_tune_roof_share_one_set_of_parameters():
    """The bug this design exists to prevent: a tool change silently reverted."""
    import matplotlib.pyplot as plt

    from metal_strength import viz

    plt.close("all")
    srv.tune_roof(reset=True, chart=False)
    fig = viz.dashboard(session=srv._session, span=12.0, length=15.0)
    apply_on_gui = fig._ms_widgets["apply"]

    class Applier:
        session = srv._session

        def __call__(self, params):
            return apply_on_gui(params)

    srv.attach_window(Applier())
    try:
        w = fig._ms_widgets
        assert w["session"] is srv._session, "one dict, not two"

        # A tool call must move the handles, not just the numbers.
        state = srv.tune_roof(snow_depth_m=2.0, rafter="HEB300", chart=False)[0]
        assert state["window"] is True
        assert w["depth"].val == pytest.approx(2.0)
        ladder, _ = w["sections"]["rafter"].valtext.get_text(), None
        assert ladder == "HEB300", "the slider rebuilt onto the HEB ladder"

        # Now move an unrelated slider by hand. The tool's snow depth must
        # survive it -- this is exactly what two stores got wrong.
        w["sections"]["column"].set_val(w["sections"]["column"].val + 1)
        assert srv._session["snow_depth_m"] == pytest.approx(2.0)
        assert srv._session["rafter"] == "HEB300"

        # And the hand-moved column is what the next tool call reports.
        after = srv.tune_roof(chart=False)[0]
        assert after["parameters"]["column"] == srv._session["column"]
        assert after["parameters"]["snow_depth_m"] == pytest.approx(2.0)
    finally:
        srv.attach_window(None)
        plt.close(fig)


def test_serve_is_stdio_only_and_the_window_serves_itself():
    """No --http to remember: a window serves, and serve is the stdio case."""
    from metal_strength import cli

    called = {}
    original = cli._serve
    cli._serve = lambda a: called.setdefault("args", a) and 0 or 0
    try:
        assert cli.main(["serve"]) == 0
        assert called["args"].cmd == "serve"
        assert not hasattr(called["args"], "http")
    finally:
        cli._serve = original


def test_a_window_run_carries_its_own_mcp_knobs():
    from metal_strength import cli

    seen = {}
    original = cli._report
    cli._report = lambda *a, **k: seen.update(k)
    try:
        cli.main(["roof", "--span", "12", "--length", "20", "--snow", "2.0"])
        assert seen["mcp_port"] == 8000, "serving is the default, not opt-in"
        cli.main(["roof", "--span", "12", "--length", "20", "--snow", "2.0",
                  "--no-mcp"])
        assert seen["mcp_port"] is None
    finally:
        cli._report = original


def test_free_port_falls_back_when_the_preferred_one_is_taken():
    import socket

    from metal_strength import cli

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        busy = taken.getsockname()[1]
        taken.listen(1)
        assert cli._free_port(busy, "127.0.0.1") != busy
    assert cli._free_port(0, "127.0.0.1") > 0


def test_tune_roof_draws_a_free_form_profile():
    """An arch is not a preset: the LLM sends points, and can bend them again."""
    import math

    srv.tune_roof(reset=True, chart=False)
    arch = [[x, 3.0 + 2.0 * math.sin(math.pi * x / 12)] for x in range(0, 13, 2)]
    state = srv.tune_roof(profile_points=arch, chart=False)[0]

    assert state["parameters"]["shape"] == "custom"
    assert state["mu_approximate"] is True, "no Eurocode rule for an arbitrary outline"
    assert state["profile_points"][0] == [0.0, 3.0]
    assert max(z for _, z in state["profile_points"]) == pytest.approx(5.0)
    assert len(state["slope_pitches_deg"]) == len(arch) - 1

    # "bend it more": read the points back, scale the rise, send them again.
    bent = [[x, 3.0 + (z - 3.0) * 1.5] for x, z in state["profile_points"]]
    after = srv.tune_roof(profile_points=bent, chart=False)[0]
    assert max(z for _, z in after["profile_points"]) == pytest.approx(6.0)

    # Naming a shape again discards the drawing.
    back = srv.tune_roof(shape="duopitch", chart=False)[0]
    assert back["parameters"]["points"] is None
    assert back["parameters"]["shape"] == "duopitch"
    # A preset reports the outline it generated, so it can be bent in turn.
    assert len(back["profile_points"]) == 3


def test_a_preset_reports_points_that_can_be_sent_straight_back():
    for shape in ("duopitch", "gambrel", "multispan"):
        state = srv.tune_roof(reset=True, shape=shape, chart=False)[0]
        again = srv.tune_roof(profile_points=state["profile_points"],
                              chart=False)[0]
        assert again["profile_points"] == state["profile_points"]
        assert again["worst_utilisation"] == pytest.approx(
            state["worst_utilisation"], rel=1e-6), shape


@pytest.mark.parametrize("bad, reason", [
    ([[0, 3], [0, 5], [12, 3]], "increase in x"),
    ([[0, 3], [8, 5], [4, 3]], "increase in x"),
    ([[0, 3], [12, 0]], "ground"),
    ([[0, 3]], "at least two"),
])
def test_a_drawn_profile_is_refused_with_the_reason(bad, reason):
    srv.tune_roof(reset=True, chart=False)
    with pytest.raises(ValueError, match=reason):
        srv.tune_roof(profile_points=bad, chart=False)
    assert srv._session["points"] is None, "a refusal must not change the roof"


def test_a_drawn_profile_reaches_an_open_window():
    import matplotlib.pyplot as plt

    from metal_strength import viz

    plt.close("all")
    srv.tune_roof(reset=True, chart=False)
    fig = viz.dashboard(session=srv._session)

    class Applier:
        session = srv._session

        def __call__(self, params):
            return fig._ms_widgets["apply"](params)

    srv.attach_window(Applier())
    try:
        srv.tune_roof(profile_points=[[0, 3], [4, 6], [8, 5], [12, 3]], chart=False)
        w = fig._ms_widgets
        assert w["profile"]().shape == "custom"
        assert w["profile"]().points[1] == (4.0, 6.0)
        # "custom" has no radio entry; the radio keeps naming the mu source.
        assert w["shape"].value_selected
    finally:
        srv.attach_window(None)
        plt.close(fig)
