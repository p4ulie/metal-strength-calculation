"""Bill of materials and indicative costing.

The mass is exact -- it comes from the same section properties the analysis
used. The money is not: steel is quoted per order, and the shipped rates are a
dated snapshot of published Czech list prices. Treat a total as a budget
sanity-check, and pass ``--prices`` with a real quote before ordering.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .model import Construction
from .sections import get_section

_DEFAULT_PRICES = Path(__file__).parent / "data" / "prices.json"

# Nominal stock lengths steel is sold in; used to estimate off-cut waste.
STOCK_LENGTH_M = 12.0


@dataclass
class Line:
    """One row of the material list: all members sharing a profile and a role."""

    role: str
    section: str
    count: int
    length_each_m: float
    grade: str

    @property
    def total_length_m(self) -> float:
        return self.count * self.length_each_m

    @property
    def mass_each_kg(self) -> float:
        return get_section(self.section).mass_per_m * self.length_each_m

    @property
    def total_mass_kg(self) -> float:
        return self.count * self.mass_each_kg

    @property
    def family(self) -> str:
        m = re.match(r"^[A-Za-z]+", self.section)
        return m.group(0).upper() if m else "default"


@dataclass
class Prices:
    """Per-kilogram rates plus the tax and currency context around them."""

    currency: str
    per_kg: dict[str, float]
    basis: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    vat_rate: float = 0.0
    includes_vat: bool = False
    eur_per_unit: float = 1.0
    retrieved: str = ""
    sources: list[dict] = field(default_factory=list)
    country: str = "CZ"
    origin: str = "CZ"  # where the rates themselves were published

    @property
    def display_currency(self) -> str:
        """Slovakia is in the euro; Czechia is not."""
        return "EUR" if self.country == "SK" else self.currency

    def display(self, amount: float) -> float:
        """Convert a figure from the list currency into the display currency."""
        if self.display_currency == self.currency:
            return amount
        return amount * self.eur_per_unit

    @property
    def converted(self) -> bool:
        """True when the rates were published somewhere other than the target."""
        return self.country != self.origin

    @classmethod
    def load(cls, path: str | Path | None = None, country: str = "SK",
             fx: float | None = None) -> Prices:
        """Load a price list. ``country`` picks the VAT rate (``SK`` or ``CZ``)."""
        data = json.loads(Path(path or _DEFAULT_PRICES).read_text())
        raw = data.get("per_kg", {})
        # Accept both the annotated shape and a plain {"IPE": 30.0} one, so a
        # hand-written supplier list stays trivial to author.
        rates, basis, notes = {}, {}, {}
        for family, value in raw.items():
            if isinstance(value, dict):
                rates[family] = float(value["rate"])
                basis[family] = value.get("basis", "supplied")
                notes[family] = value.get("note", "")
            else:
                rates[family] = float(value)
                basis[family] = "supplied"
        vat = data.get("vat_rate", 0.0)
        if isinstance(vat, dict):
            vat = vat.get(country.upper(), 0.0)
        return cls(
            currency=data.get("currency", "EUR"), per_kg=rates, basis=basis, notes=notes,
            vat_rate=float(vat), includes_vat=bool(data.get("includes_vat", False)),
            eur_per_unit=float(fx if fx is not None else data.get("eur_per_unit", 1.0)),
            retrieved=data.get("retrieved", ""), sources=data.get("sources", []),
            country=country.upper(), origin=data.get("origin", "CZ"),
        )

    def rate(self, family: str) -> float:
        return self.per_kg.get(family, self.per_kg.get("default", 0.0))

    def is_assumed(self, family: str) -> bool:
        return self.basis.get(family, self.basis.get("default", "")) == "assumed"


@dataclass
class BillOfMaterials:
    lines: list[Line]
    prices: Prices | None = None
    waste_factor: float = 1.0

    @property
    def total_mass_kg(self) -> float:
        return sum(line.total_mass_kg for line in self.lines) * self.waste_factor

    def line_cost(self, line: Line) -> float:
        if self.prices is None:
            return 0.0
        return line.total_mass_kg * self.waste_factor * self.prices.rate(line.family)

    @property
    def subtotal(self) -> float:
        """Material cost before VAT, in the price list's currency."""
        if self.prices is None:
            return 0.0
        base = sum(self.line_cost(line) for line in self.lines)
        return base / (1 + self.prices.vat_rate) if self.prices.includes_vat else base

    @property
    def vat(self) -> float:
        return self.subtotal * self.prices.vat_rate if self.prices else 0.0

    @property
    def total(self) -> float:
        return self.subtotal + self.vat

    def in_eur(self, amount: float) -> float:
        return amount * self.prices.eur_per_unit if self.prices else 0.0

    @property
    def uses_assumed_rates(self) -> list[str]:
        if self.prices is None:
            return []
        return sorted({line.family for line in self.lines
                       if self.prices.is_assumed(line.family)})


def _role_of(tag: str, section: str) -> str:
    """Group members by what they are, falling back to the profile name."""
    first = tag.split()[0] if tag else ""
    return first if first and not first.startswith(("[", section[:2])) else section


def bill_of_materials(construction: Construction, prices: Prices | None = None,
                      waste: float = 0.0) -> BillOfMaterials:
    """Group a construction's members into a material list.

    ``waste`` is an off-cut allowance as a fraction (0.05 = 5%). Members are
    grouped by role and profile, then by length rounded to the millimetre, so
    identical parts appear as one line with a count.
    """
    grouped: dict[tuple[str, str, float, str], int] = {}
    for e, member in enumerate(construction.spec.members):
        # Cut lengths go up to the whole millimetre: you cannot cut a bar short,
        # so the list must never ask for less steel than the model assumed.
        length_m = math.ceil(float(construction.structure_length(e))) / 1000.0
        key = (_role_of(member.tag, member.section), member.section, length_m,
               member.grade)
        grouped[key] = grouped.get(key, 0) + 1

    lines = [Line(role, section, count, length, grade)
             for (role, section, length, grade), count in grouped.items()]
    lines.sort(key=lambda line: (-line.total_mass_kg, line.role))
    return BillOfMaterials(lines, prices, 1.0 + waste)


def format_bom(bom: BillOfMaterials, lang: str = "en", show_prices: bool = True) -> str:
    """Render the material list as a table."""
    from .i18n import t

    has_money = show_prices and bom.prices is not None
    cur = bom.prices.currency if has_money else ""

    head = [t("role", lang), t("profile", lang), t("grade", lang), t("qty", lang),
            t("length_each", lang), t("total_length", lang), t("mass_each", lang),
            t("total_mass", lang)]
    widths = [12, 14, 6, 5, 10, 11, 10, 11]
    if has_money:
        head += [f"{t('rate', lang)} [{cur}/kg]", f"{t('cost', lang)} [{cur}]"]
        widths += [13, 13]

    rows = []
    for line in bom.lines:
        row = [line.role, line.section, line.grade, str(line.count),
               f"{line.length_each_m:.3f}", f"{line.total_length_m:.2f}",
               f"{line.mass_each_kg:.1f}", f"{line.total_mass_kg:.1f}"]
        if has_money:
            row += [f"{bom.prices.rate(line.family):.2f}",
                    f"{bom.line_cost(line):,.0f}"]
        rows.append(row)

    def render(cells):
        return "  ".join(c.ljust(w) if i < 3 else c.rjust(w)
                         for i, (c, w) in enumerate(zip(cells, widths)))

    out = [render(head), "-" * (sum(widths) + 2 * (len(widths) - 1))]
    out += [render(r) for r in rows]
    out.append("-" * (sum(widths) + 2 * (len(widths) - 1)))

    total = [f"{t('total', lang).upper()}", "", "",
             str(sum(line.count for line in bom.lines)), "",
             f"{sum(line.total_length_m for line in bom.lines):.2f}", "",
             f"{bom.total_mass_kg:.1f}"]
    if has_money:
        total += ["", f"{bom.subtotal:,.0f}"]
    out.append(render(total))

    if bom.waste_factor > 1.0:
        out.append(f"  ({t('incl_waste', lang)} {100 * (bom.waste_factor - 1):.0f}%)")

    if has_money:
        p = bom.prices
        out.append("")
        disp = p.display_currency
        both = (lambda v: f"{p.display(v):>12,.0f} {disp}"
                if disp == p.currency else
                f"{p.display(v):>12,.2f} {disp}  ({v:,.0f} {p.currency})")
        out.append(f"  {t('subtotal', lang):<22s} {both(bom.subtotal)}")
        out.append(f"  {t('vat', lang) + f' {100 * p.vat_rate:.0f}% ({p.country})':<22s} "
                   f"{both(bom.vat)}")
        out.append(f"  {t('total_incl_vat', lang):<22s} {both(bom.total)}")
        out.append("")
        out.append(f"  ! {t('price_warning', lang)}")
        if p.retrieved:
            out.append(f"    {t('rates_read', lang)} {p.retrieved}")
        if p.converted:
            out.append(f"    {t('converted_rates', lang).format(origin=p.origin, country=p.country)}")
        if bom.uses_assumed_rates:
            out.append(f"    {t('assumed_rates', lang)}: "
                       f"{', '.join(bom.uses_assumed_rates)}")
    return "\n".join(out)
