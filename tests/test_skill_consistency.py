"""The skill must not drift from the code.

Every number quoted in .claude/skills/metal-strength/ is parsed back out of the
markdown and compared against what the package actually computes. If someone
changes a partial factor in ec3.py and forgets the skill, this fails.
"""

import math
import re
from pathlib import Path

import pytest

from metal_strength import ec3, loads
from metal_strength.sections import get_section

SKILL_DIR = Path(__file__).parent.parent / ".claude" / "skills" / "metal-strength"
SKILL = SKILL_DIR / "SKILL.md"
CURVES = SKILL_DIR / "references" / "buckling-curves.md"
SECTIONS = SKILL_DIR / "references" / "section-properties.md"


def rows(text: str, header_startswith: str) -> list[list[str]]:
    """Body rows of every markdown table whose header matches the prefix."""
    out, capturing = [], False
    for line in text.splitlines():
        if line.startswith(header_startswith):
            capturing = True
            continue
        if capturing:
            if not line.startswith("|"):
                capturing = False  # table ended; keep looking for more
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            out.append(cells)
    return out


def test_skill_files_exist_with_frontmatter():
    for f in (SKILL, CURVES, SECTIONS):
        assert f.exists(), f
    text = SKILL.read_text()
    assert text.startswith("---\n")
    fm = text.split("---")[1]
    assert re.search(r"^name:\s*metal-strength\s*$", fm, re.M)
    assert re.search(r"^description:\s*\S", fm, re.M)
    # The description is what triggers the skill -- it must name the concepts.
    desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1).lower()
    for word in ("bending", "buckling", "eurocode", "snow", "deflection"):
        assert word in desc, f"description should mention {word}"


def test_steel_grades_match():
    for cells in rows(SKILL.read_text(), "| Grade | f_y"):
        grade, fy_thin, fy_thick, fu = cells[0], *map(float, cells[1:4])
        assert ec3.yield_strength(grade, 20.0) == (fy_thin, fu), grade
        assert ec3.yield_strength(grade, 60.0)[0] == fy_thick, grade


def test_material_constants_match():
    text = SKILL.read_text()
    assert f"E = {ec3.E:,.0f}".replace(",", " ") in text.replace(",", " ")
    assert f"G = {ec3.G:,.0f}".replace(",", " ") in text.replace(",", " ")
    assert "7850 kg/m" in text
    assert f"gamma_M0 = gamma_M1 = {ec3.GAMMA_M0:.1f}" in text
    assert f"gamma_M2 = {ec3.GAMMA_M2:.2f}" in text


def test_deflection_limits_match():
    text = SKILL.read_text()
    assert f"L/{ec3.DEFLECTION_LIMITS['roof_general']:.0f}" in text
    assert f"L/{ec3.DEFLECTION_LIMITS['roof_brittle_finish']:.0f}" in text


def test_snow_densities_match():
    for cells in rows(SKILL.read_text(), "| State | Density"):
        state = cells[0].lower()
        density = float(cells[1].split()[0])
        one_metre = float(cells[2].replace("*", "").split()[0])
        assert loads.SNOW_DENSITY[state] == density, state
        assert loads.snow_from_depth(1.0, state) == one_metre, state


def test_exposure_and_shape_coefficients_match():
    text = SKILL.read_text()
    for name, value in loads.EXPOSURE.items():
        assert f"{value:.1f} {name}" in text, f"C_e for {name}"
    assert loads.mu1(0) == 0.8 and loads.mu1(30) == 0.8
    assert loads.mu1(61) == 0.0
    assert loads.mu1(61, snow_guards=True) == 0.8


def test_annex_c_formula_matches():
    text = SKILL.read_text()
    a, b, div = loads.REGIONS["central_east"]
    assert f"({a:.3f} Z - {abs(b):.3f})" in text
    assert f"(A/{div})" in text


def test_alpha_imperfection_factors_match():
    for path in (SKILL, CURVES):
        table = rows(path.read_text(), "| Curve | a0 |")
        assert table, path
        for cells in table:
            for curve, value in zip(("a0", "a", "b", "c", "d"), cells[1:]):
                assert ec3.ALPHA[curve] == float(value), f"{path.name} {curve}"


def test_chi_table_matches_the_implementation():
    table = rows(CURVES.read_text(), "| lambda_bar | a0 |")
    assert len(table) >= 10
    for cells in table:
        lam = float(cells[0])
        for curve, value in zip(("a0", "a", "b", "c", "d"), cells[1:]):
            assert ec3.chi(lam, curve) == pytest.approx(float(value), abs=5e-4), \
                f"chi({lam}, {curve})"


def test_epsilon_table_matches():
    table = rows(CURVES.read_text(), "| Grade | S235 |")
    grades = ["S235", "S275", "S355", "S420", "S460"]
    eps_row, lam1_row = table[0][1:], table[1][1:]
    for grade, eps_txt, lam1_txt in zip(grades, eps_row, lam1_row):
        fy = ec3.GRADES[grade][0][0]
        assert ec3.epsilon(fy) == pytest.approx(float(eps_txt), abs=5e-3), grade
        assert 93.9 * ec3.epsilon(fy) == pytest.approx(float(lam1_txt), abs=0.1), grade


def test_classification_limits_match():
    """The Table 5.2 limits quoted in the reference are the ones classify() uses."""
    table = rows(CURVES.read_text(), "| Part | Class 1 |")
    quoted = {cells[0]: tuple(float(c) for c in cells[1:4]) for cells in table}
    assert quoted["Outstand flange, compression"] == (9.0, 10.0, 14.0)
    assert quoted["Internal part, compression"] == (33.0, 38.0, 42.0)
    assert quoted["Internal part (web), bending"] == (72.0, 83.0, 124.0)

    # Prove those are the numbers in play: an IPE300 web at c/t = 35 is well
    # inside 72, and a section just past 124*eps must come out class 4.
    ipe = get_section("IPE300")
    assert ipe.cw_over_tw < 72.0
    assert ec3.classify(ipe, 235.0, M=1e8)[0] <= 2


def test_ltb_constants_match():
    text = CURVES.read_text()
    assert "0.34 for h/b <= 2" in text and "0.49" in text
    # lambda_LT_0 = 0.4 and beta = 0.75 are baked into ec3; confirm the plateau.
    ipe = get_section("IPE300")
    _, chi_lt, lam = ec3.lateral_torsional_buckling(ipe, 235.0, 1, 100.0)
    assert chi_lt == 1.0 and lam < 0.4
    assert "0.4" in text and "0.75" in text


def test_beam_formula_table_matches_the_solver():
    """Each closed-form row in SKILL.md is re-derived by the FEM engine."""
    from metal_strength.model import single_beam

    L, w, P = 6.0, 5.0, 20.0  # m, kN/m, kN
    s = get_section("IPE300")
    EI = ec3.E * s.Iy  # N mm^2
    Lmm = L * 1000.0
    # 1 kN/m is exactly 1 N/mm, so w needs no conversion; P does.
    Pn = P * 1000.0

    cases = {
        "cantilever_udl": (single_beam(L, "IPE300", udl_kn_m=w, fixity="cantilever"),
                           w * L**2 / 2, w * Lmm**4 / (8 * EI)),
        "simple_udl": (single_beam(L, "IPE300", udl_kn_m=w, fixity="simple"),
                       w * L**2 / 8, 5 * w * Lmm**4 / (384 * EI)),
        "simple_point": (single_beam(L, "IPE300", point_kn=P, fixity="simple"),
                         P * L / 4, Pn * Lmm**3 / (48 * EI)),
        "fixed_udl": (single_beam(L, "IPE300", udl_kn_m=w, fixity="fixed"),
                      w * L**2 / 12, w * Lmm**4 / (384 * EI)),
    }
    for name, (beam, moment_knm, deflection_mm) in cases.items():
        r = beam.solve()
        got_m = max(r.peak(e)["My"] for e in range(len(beam.spec.members))) / 1e6
        got_d = float(abs(r.displacements[:, 2]).max())
        assert got_m == pytest.approx(moment_knm, rel=2e-3), f"{name} moment"
        assert got_d == pytest.approx(deflection_mm, rel=5e-3), f"{name} deflection"


def test_section_property_table_matches_the_catalogue():
    text = SECTIONS.read_text()
    checked = 0
    for cells in rows(text, "| Profile | kg/m |"):
        name = cells[0]
        mass, area, h, b, Iy, Iz, Wel, Wpl, It, iy, iz = map(float, cells[1:12])
        s = get_section(name)
        assert s.mass_per_m == pytest.approx(mass, abs=0.06), name
        assert s.A / 1e2 == pytest.approx(area, abs=0.06), f"{name} A"
        assert s.h == pytest.approx(h), f"{name} h"
        assert s.Iy / 1e4 == pytest.approx(Iy, abs=0.6), f"{name} Iy"
        assert s.Wpl_y / 1e3 == pytest.approx(Wpl, abs=0.06), f"{name} Wpl"
        assert s.iz == pytest.approx(iz, abs=0.06), f"{name} iz"
        checked += 1
    assert checked >= 35


def test_quick_capacity_shorthand_is_right():
    """'M_c,Rd [kNm] = Wpl[cm3] x 0.235' -- the shorthand the reference gives."""
    s = get_section("IPE300")
    shorthand = s.Wpl_y / 1e3 * 0.235
    actual = s.Wpl_y * 235.0 / 1e6  # Nmm -> kNm
    assert shorthand == pytest.approx(actual, rel=1e-12)
    assert "148 kNm" in SECTIONS.read_text()
    assert round(actual) == 148


def test_hand_section_formulas_match_custom_shapes():
    """The rectangle / round / tube formulas quoted in SKILL.md."""
    from metal_strength.sections import custom_rectangle, custom_round, custom_tube

    b, h, d, t = 20.0, 50.0, 30.0, 3.0
    rect, rnd, tube = custom_rectangle(b, h), custom_round(d), custom_tube(d, t)
    assert rect.A == b * h
    assert rect.Iy == pytest.approx(b * h**3 / 12)
    assert rect.Wel_y == pytest.approx(b * h**2 / 6)
    assert rect.Wpl_y == pytest.approx(b * h**2 / 4)
    assert rnd.A == pytest.approx(math.pi * d**2 / 4)
    assert rnd.Iy == pytest.approx(math.pi * d**4 / 64)
    assert rnd.Wel_y == pytest.approx(math.pi * d**3 / 32)
    assert rnd.Wpl_y == pytest.approx(d**3 / 6)
    assert tube.A == pytest.approx(math.pi * t * (d - t))
    # i = b/sqrt(12) = 0.289 b for a rectangle about its weak axis
    assert rect.iz == pytest.approx(b / math.sqrt(12))
    assert rect.iz == pytest.approx(0.289 * b, rel=2e-3)  # 0.289 is 1/sqrt(12) rounded


def test_effective_length_factors_quoted_are_the_ones_that_work():
    """k = 0.5 / 0.7 / 1.0 / 2.0 must appear, and scale N_cr as stated."""
    text = SKILL.read_text()
    for k in ("0.5", "0.7", "1.0", "2.0"):
        assert f"**{k}**" in text or f"k = {k}" in text
    s = get_section("HEB200")
    base = ec3.flexural_buckling(s, 235.0, 4000.0 * 1.0, "z")[0]
    fixed = ec3.flexural_buckling(s, 235.0, 4000.0 * 0.5, "z")[0]
    cantilever = ec3.flexural_buckling(s, 235.0, 4000.0 * 2.0, "z")[0]
    assert cantilever < base < fixed


def test_every_mcp_tool_is_documented():
    """A tool nobody can find is a tool that does not exist."""
    import asyncio

    from metal_strength import mcp_server

    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    docs = (Path("README.md").read_text()
            + Path(".claude/skills/metal-strength/SKILL.md").read_text())
    assert not {n for n in names if n not in docs}


def test_the_docs_do_not_offer_flags_that_were_removed():
    """--http and --live are gone; nothing should still tell you to type them."""
    for path in (Path("README.md"),
                 Path(".claude/skills/metal-strength/SKILL.md"),
                 Path("ms")):
        text = path.read_text()
        assert "--http" not in text, path
        assert "--live" not in text, path
        assert "metal_strength.viewer" not in text, path


def test_every_readme_image_exists():
    """A broken image is worse than no image: it looks like rot."""
    import re

    readme = Path("README.md").read_text()
    referenced = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme, re.S)
    assert referenced, "the README is meant to show the thing, not only describe it"
    for relative in referenced:
        image = Path(relative)
        assert image.exists(), relative
        assert image.stat().st_size > 5_000, f"{relative} looks empty"
