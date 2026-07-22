"""Material list, indicative costing, the design solver, and translations."""

import json
import math

import pytest

from metal_strength import design, i18n
from metal_strength.bom import Prices, bill_of_materials, format_bom
from metal_strength.model import pitched_roof, single_beam
from metal_strength.sections import get_section


@pytest.fixture(scope="module")
def roof():
    return pitched_roof(span=12.0, length=20.0, pitch_deg=20.0, snow_kn_m2=3.2,
                        rafter="IPE450", column="HEB240", purlin="SHS140x140x5")


# --- material list ----------------------------------------------------------


def test_bom_mass_matches_the_model(roof):
    """Equal to the model's mass, bar the round-up to whole millimetres.

    Cut lengths go up to the nearest mm, so the list must be very slightly
    heavier than the idealised model -- never lighter, which would under-order.
    """
    b = bill_of_materials(roof)
    assert b.total_mass_kg >= roof.total_mass_kg
    assert b.total_mass_kg == pytest.approx(roof.total_mass_kg, rel=1e-3)
    # And the model's mass is just length x kg/m, which is checkable by hand.
    by_hand = sum(get_section(m.section).mass_per_m * roof.structure_length(e) / 1000.0
                  for e, m in enumerate(roof.spec.members))
    assert roof.total_mass_kg == pytest.approx(by_hand, rel=1e-9)


def test_bom_groups_identical_parts(roof):
    b = bill_of_materials(roof)
    assert len(b.lines) < len(roof.spec.members), "identical members must collapse"
    assert sum(line.count for line in b.lines) == len(roof.spec.members)
    roles = {line.role for line in b.lines}
    assert {"rafter", "column", "purlin"} <= roles


def test_bom_lengths_add_up(roof):
    b = bill_of_materials(roof)
    assert sum(line.total_length_m for line in b.lines) == pytest.approx(
        roof.total_length_m, rel=1e-3)  # cut lengths round up to the mm


def test_waste_allowance_scales_mass_and_cost(roof):
    plain = bill_of_materials(roof, Prices.load())
    waste = bill_of_materials(roof, Prices.load(), waste=0.10)
    assert waste.total_mass_kg == pytest.approx(plain.total_mass_kg * 1.10)
    assert waste.subtotal == pytest.approx(plain.subtotal * 1.10)


def test_bom_without_prices_reports_no_money(roof):
    b = bill_of_materials(roof)
    assert b.subtotal == 0.0 and b.vat == 0.0 and b.total == 0.0
    text = format_bom(b)
    assert "VAT" not in text and "CZK" not in text


# --- pricing ----------------------------------------------------------------


def test_shipped_rates_are_sane():
    p = Prices.load()
    assert p.currency == "CZK"
    for family in ("IPE", "HEB", "SHS", "RHS", "CHS", "default"):
        assert 10.0 < p.rate(family) < 100.0, family
    assert p.retrieved, "the rates must carry the date they were read"
    assert p.sources, "and where they came from"
    for src in p.sources:
        assert src["url"].startswith("http") and src["read"]


def test_assumed_rates_are_declared_as_such():
    """Families with no published list must be flagged, not passed off as measured."""
    p = Prices.load()
    assert p.is_assumed("HEA") and p.is_assumed("HEM") and p.is_assumed("CHS")
    assert not p.is_assumed("IPE") and not p.is_assumed("HEB")
    assert not p.is_assumed("SHS")


def test_bom_surfaces_assumed_rates(roof):
    b = bill_of_materials(roof, Prices.load())
    text = format_bom(b, "en")
    assert "INDICATIVE" in text
    assert "not a quote" in text
    # This roof uses HEB (measured) and SHS/IPE (measured), so nothing assumed.
    assert b.uses_assumed_rates == []

    hea = pitched_roof(span=10.0, length=10.0, pitch_deg=20.0, snow_kn_m2=2.0,
                       column="HEA200")
    assert "HEA" in bill_of_materials(hea, Prices.load()).uses_assumed_rates


def test_vat_and_currency_follow_the_country(roof):
    sk = bill_of_materials(roof, Prices.load(country="SK"))
    cz = bill_of_materials(roof, Prices.load(country="CZ"))
    assert sk.prices.vat_rate == 0.23 and cz.prices.vat_rate == 0.21
    assert sk.prices.display_currency == "EUR"
    assert cz.prices.display_currency == "CZK"
    # Same steel, same list price; only the tax differs.
    assert sk.subtotal == pytest.approx(cz.subtotal)
    assert sk.total > cz.total


def test_slovak_output_says_the_rates_were_converted(roof):
    text = format_bom(bill_of_materials(roof, Prices.load(country="SK")), "sk")
    assert "EUR" in text and "CZK" in text
    assert "prepočítané pre SK" in text, "must disclose the rates are Czech"
    # Czech output has nothing to disclose.
    assert "prepočítané" not in format_bom(
        bill_of_materials(roof, Prices.load(country="CZ")), "cs")


def test_vat_arithmetic(roof):
    b = bill_of_materials(roof, Prices.load(country="CZ"))
    assert b.vat == pytest.approx(b.subtotal * 0.21)
    assert b.total == pytest.approx(b.subtotal * 1.21)


def test_exchange_rate_can_be_overridden(roof):
    a = bill_of_materials(roof, Prices.load(country="SK", fx=0.04))
    b = bill_of_materials(roof, Prices.load(country="SK", fx=0.05))
    assert b.prices.display(b.subtotal) == pytest.approx(
        a.prices.display(a.subtotal) * 1.25)


def test_a_custom_price_list_overrides_the_shipped_one(roof, tmp_path):
    """A supplier quote should be trivial to author -- plain rates, no metadata."""
    path = tmp_path / "quote.json"
    path.write_text(json.dumps({
        "currency": "EUR", "origin": "SK", "includes_vat": False,
        "vat_rate": {"SK": 0.23}, "eur_per_unit": 1.0,
        "per_kg": {"IPE": 1.50, "HEB": 1.60, "SHS": 1.20, "default": 1.50},
    }))
    b = bill_of_materials(roof, Prices.load(path, country="SK"))
    assert b.prices.currency == "EUR"
    assert b.prices.rate("IPE") == 1.50
    assert not b.prices.converted, "an SK list for SK needs no conversion note"
    assert b.uses_assumed_rates == [], "a supplied quote is not an estimate"
    assert 1.2 * b.total_mass_kg < b.subtotal < 1.6 * b.total_mass_kg


# --- translations -----------------------------------------------------------


def test_every_message_covers_every_language():
    for key, entry in i18n.MESSAGES.items():
        missing = set(i18n.LANGUAGES) - set(entry)
        assert not missing, f"{key} is missing {missing}"
        for lang, text in entry.items():
            assert text.strip(), f"{key}/{lang} is empty"


def test_lookup_falls_back_rather_than_crashing():
    assert i18n.t("qty", "sk") == "ks"
    assert i18n.t("qty", "de") == "qty"      # unknown language -> English
    assert i18n.t("no_such_key", "sk") == "no_such_key"
    assert i18n.verdict(True, "sk") == "VYHOVUJE"
    assert i18n.verdict(False, "cs") == "NEVYHOVUJE"


def test_translated_bom_differs_from_english(roof):
    b = bill_of_materials(roof, Prices.load())
    en, sk, cs = (format_bom(b, x) for x in ("en", "sk", "cs"))
    assert en != sk and en != cs and sk != cs
    assert "VÝKAZ" not in en
    assert "ORIENTAČNÉ CENY" in sk and "ORIENTAČNÍ CENY" in cs
    # Roles are translated; EN profile designations and grades are not.
    assert "krokva" in sk and "stĺp" in sk and "väznica" in sk
    assert "krokev" in cs and "sloup" in cs and "vaznice" in cs
    for text in (en, sk, cs):
        assert "IPE450" in text and "HEB240" in text and "S235" in text


# --- the design solver ------------------------------------------------------


def test_proposal_actually_passes_its_own_checks():
    """The solver's verdict must survive an independent re-check."""
    p = design.propose(span=12.0, length=20.0, pitch_deg=20.0, snow_kn_m2=4.0)
    assert p.feasible
    con = p.construction
    checks = con.check()
    worst = max(c.utilisation for c in checks)
    assert worst <= 1.0, f"proposed a design that fails at {worst:.2f}"
    assert con.deflection(con.solve()).utilisation <= 1.0
    assert p.utilisation == pytest.approx(worst, rel=1e-6)


@pytest.mark.slow
def test_proposal_respects_the_target():
    relaxed = design.propose(span=10.0, length=15.0, snow_kn_m2=2.0, target=1.0)
    headroom = design.propose(span=10.0, length=15.0, snow_kn_m2=2.0, target=0.7)
    assert relaxed.utilisation <= 1.0
    assert max(headroom.utilisation, headroom.deflection_utilisation) <= 0.7
    assert headroom.mass_kg >= relaxed.mass_kg, "headroom costs steel"


@pytest.mark.slow
def test_heavier_load_needs_more_steel():
    light = design.propose(span=12.0, length=20.0, snow_kn_m2=1.0)
    heavy = design.propose(span=12.0, length=20.0, snow_kn_m2=4.0)
    assert light.feasible and heavy.feasible
    assert heavy.mass_kg > light.mass_kg


@pytest.mark.slow
def test_longer_span_needs_more_steel():
    short = design.propose(span=8.0, length=15.0, snow_kn_m2=2.0)
    long_ = design.propose(span=16.0, length=15.0, snow_kn_m2=2.0)
    assert long_.feasible
    # Per metre of building, a longer span is heavier.
    assert long_.mass_kg / 16.0 > short.mass_kg / 8.0


def test_solver_is_not_wasteful():
    """The shrink pass must leave the design reasonably utilised, not vastly oversized."""
    p = design.propose(span=12.0, length=20.0, snow_kn_m2=3.0)
    assert p.feasible
    assert max(p.utilisation, p.deflection_utilisation) > 0.55, (
        f"only {p.utilisation:.2f} utilised -- the shrink pass is not working")


@pytest.mark.slow
def test_solver_reports_infeasible_rather_than_lying():
    """An absurd load must be refused, not silently under-designed."""
    p = design.propose(span=40.0, length=30.0, snow_kn_m2=50.0, frame_spacing=10.0)
    assert not p.feasible
    assert p.construction is None
    text = design.format_proposal(p)
    assert "FAILS" in text and "No combination" in text


def test_families_can_be_constrained():
    p = design.propose(span=10.0, length=15.0, snow_kn_m2=2.0,
                       families={"rafter": "HEB", "column": "HEB", "purlin": "RHS"})
    assert p.feasible
    assert p.sections["rafter"].startswith("HEB")
    assert p.sections["purlin"].startswith("RHS")


def test_search_terminates_and_records_its_work():
    p = design.propose(span=12.0, length=20.0, snow_kn_m2=3.0)
    assert 0 < p.iterations < 60
    assert len(p.history) >= 2
    # Utilisation should trend down as the climb adds steel.
    assert p.history[0][1] > p.history[-1][1]


def test_ladder_is_ordered():
    names = design.ladder("IPE")
    depths = [get_section(n).h for n in names]
    assert depths == sorted(depths)
    assert all(n.startswith("IPE") for n in names)


@pytest.mark.slow
def test_cost_objective_uses_the_price_list():
    """With prices in play the shrink pass should not produce a worse design."""
    prices = Prices.load()
    by_mass = design.propose(span=12.0, length=20.0, snow_kn_m2=3.0)
    by_cost = design.propose(span=12.0, length=20.0, snow_kn_m2=3.0,
                             objective="cost", prices=prices)
    assert by_cost.feasible
    cheap = bill_of_materials(by_cost.construction, prices).subtotal
    dear = bill_of_materials(by_mass.construction, prices).subtotal
    assert cheap <= dear * 1.05


def test_format_proposal_is_translated():
    p = design.propose(span=10.0, length=15.0, snow_kn_m2=2.0)
    assert "PROPOSED CONSTRUCTION" in design.format_proposal(p, "en")
    assert "NAVRHNUTÁ KONŠTRUKCIA" in design.format_proposal(p, "sk")
    assert "NAVRŽENÁ KONSTRUKCE" in design.format_proposal(p, "cs")
    sk = design.format_proposal(p, "sk")
    assert "krokva" in sk and "rafter" not in sk


# --- CLI --------------------------------------------------------------------


def test_cli_design_command(capsys):
    from metal_strength import cli

    rc = cli.main(["design", "--span", "10", "--length", "15",
                   "--snow-depth", "1.0", "--snow-state", "settled", "--cost"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PROPOSED CONSTRUCTION" in out and "PASSES" in out
    assert "MATERIAL LIST" in out
    assert "INDICATIVE PRICES" in out


def test_cli_bom_on_a_beam(capsys):
    from metal_strength import cli

    rc = cli.main(["beam", "--span", "6", "--section", "IPE200", "--udl", "5", "--bom"])
    out = capsys.readouterr().out
    assert rc == 0 and "MATERIAL LIST" in out and "IPE200" in out


def test_cli_design_reports_failure_with_a_nonzero_exit(capsys):
    from metal_strength import cli

    rc = cli.main(["design", "--span", "40", "--length", "30", "--snow", "50",
                   "--frame-spacing", "10"])
    assert rc == 1
    assert "No combination" in capsys.readouterr().out


def test_construction_is_the_general_name():
    """The container is no longer roof-specific, but the old name still imports."""
    from metal_strength.model import Construction, Roof

    assert Roof is Construction
    beam = single_beam(6.0, "IPE200", udl_kn_m=5.0)
    assert isinstance(beam, Construction)
    assert beam.total_mass_kg == pytest.approx(
        get_section("IPE200").mass_per_m * 6.0, rel=1e-6)
    assert math.isclose(beam.total_length_m, 6.0, rel_tol=1e-9)
