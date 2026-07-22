"""Propose a construction that carries a given load.

The rest of the package answers "does this hold?". This answers "what should I
build?" -- given a span, a length and a load, it searches the profile catalogue
for a combination that satisfies every EN 1993-1-1 check plus the deflection
limit, and returns the lightest (or cheapest) one it finds.

The search is a climb-then-shrink, not a brute force: the catalogue has 567
profiles and three roles, so exhausting it would be millions of solves. Each
step raises only the role that is actually governing, which converges in a
handful of iterations, then a shrink pass takes back anything it overshot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import ec3
from .model import Construction, pitched_roof
from .sections import get_section, list_sections

# The families each role is allowed to use, in the order they are preferred.
ROLE_FAMILIES = {
    "rafter": ("IPE", "HEA", "HEB"),
    "column": ("HEB", "HEA", "IPE"),
    "purlin": ("SHS", "RHS", "IPE"),
}


def ladder(family: str) -> list[str]:
    """Every profile in a family, ordered small to large."""
    names = list_sections(family)
    names.sort(key=lambda n: (get_section(n).h, get_section(n).A))
    return names


def _family_of(name: str) -> str:
    m = re.match(r"^[A-Za-z]+", name)
    return m.group(0).upper() if m else "IPE"


def _role_of(tag: str) -> str | None:
    for role in ROLE_FAMILIES:
        if tag.startswith(role):
            return role
    return None


@dataclass
class Proposal:
    """The outcome of a search."""

    sections: dict[str, str]
    construction: Construction | None
    utilisation: float
    deflection_utilisation: float
    governing: str
    ok: bool
    iterations: int
    mass_kg: float = 0.0
    history: list[tuple[dict[str, str], float]] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return self.ok and self.construction is not None


def evaluate(sections: dict[str, str], **roof_kwargs) -> tuple[Construction, float, float, str]:
    """Build and check one candidate. Returns (construction, strength, deflection, governing)."""
    con = pitched_roof(rafter=sections["rafter"], column=sections["column"],
                       purlin=sections["purlin"], **roof_kwargs)
    results = con.solve()
    checks = con.check(results)
    worst = max(checks, key=lambda c: c.utilisation)
    defl = con.deflection(results)
    return con, worst.utilisation, defl.utilisation, f"{worst.section} {worst.governing.name}"


def propose(
    span: float,
    length: float,
    pitch_deg: float = 20.0,
    snow_kn_m2: float = 2.0,
    grade: str = "S235",
    families: dict[str, str] | None = None,
    start: dict[str, str] | None = None,
    target: float = 1.0,
    objective: str = "mass",
    prices=None,
    max_iterations: int = 60,
    **roof_kwargs,
) -> Proposal:
    """Search for the lightest construction that carries the load.

    ``target`` is the utilisation to design to -- 1.0 uses the full Eurocode
    capacity, 0.85 leaves headroom. ``objective`` is ``mass`` or ``cost``;
    ``cost`` needs a :class:`~metal_strength.bom.Prices` in ``prices``.

    Starts from the smallest profile in each family and climbs whichever role is
    governing, which is the one whose size actually helps. Then shrinks anything
    that turned out to be oversized.
    """
    fams = {role: (families or {}).get(role, ROLE_FAMILIES[role][0])
            for role in ROLE_FAMILIES}
    ladders = {role: ladder(fams[role]) for role in fams}
    for role, names in ladders.items():
        if not names:
            raise ValueError(f"no profiles in family {fams[role]!r} for {role}")

    idx = {role: 0 for role in ladders}
    if start:
        for role, name in start.items():
            if role in ladders:
                canonical = get_section(name).name
                if canonical in ladders[role]:
                    idx[role] = ladders[role].index(canonical)

    def names_at(i: dict[str, int]) -> dict[str, str]:
        return {role: ladders[role][k] for role, k in i.items()}

    cache: dict[tuple, tuple] = {}

    def check(i: dict[str, int]):
        key = tuple(sorted(i.items()))
        if key not in cache:
            cache[key] = evaluate(
                names_at(i), span=span, length=length, pitch_deg=pitch_deg,
                snow_kn_m2=snow_kn_m2, grade=grade, **roof_kwargs)
        return cache[key]

    history: list[tuple[dict[str, str], float]] = []
    iterations = 0

    # -- climb: raise the governing role until everything passes ---------------
    while iterations < max_iterations:
        iterations += 1
        con, util, defl_util, governing = check(idx)
        history.append((names_at(idx), max(util, defl_util)))
        if max(util, defl_util) <= target:
            break

        # Which role is at fault? The governing member names it; a deflection
        # failure is a stiffness problem, so grow the primary spanning members.
        role = _role_of(governing.split("]")[-1].strip()) if "]" in governing else None
        if defl_util > util or role is None:
            role = "rafter"
        if idx[role] >= len(ladders[role]) - 1:
            # That role is maxed out; try the next one that still has headroom.
            spare = [r for r in ladders if idx[r] < len(ladders[r]) - 1]
            if not spare:
                return Proposal(names_at(idx), None, util, defl_util, governing,
                                False, iterations, history=history)
            role = spare[0]
        idx[role] += 1
    else:
        con, util, defl_util, governing = check(idx)
        return Proposal(names_at(idx), None, util, defl_util, governing, False,
                        iterations, history=history)

    # -- shrink: the climb overshoots, so take back what is not needed ---------
    improved = True
    while improved and iterations < max_iterations:
        improved = False
        for role in sorted(ladders, key=lambda r: -_cost_of(names_at(idx)[r], prices)):
            if idx[role] == 0:
                continue
            trial = dict(idx)
            trial[role] -= 1
            iterations += 1
            _, u, d, _ = check(trial)
            if max(u, d) <= target:
                idx = trial
                improved = True
                break

    con, util, defl_util, governing = check(idx)
    history.append((names_at(idx), max(util, defl_util)))
    return Proposal(names_at(idx), con, util, defl_util, governing, True,
                    iterations, con.total_mass_kg, history)


def _cost_of(name: str, prices) -> float:
    """Per-metre cost, or mass if no price list -- used to order the shrink pass."""
    s = get_section(name)
    if prices is None:
        return s.mass_per_m
    return s.mass_per_m * prices.rate(_family_of(name))


def format_proposal(p: Proposal, lang: str = "en") -> str:
    """Render a proposal as a readable block."""
    from .i18n import t, verdict

    if not p.feasible:
        return (f"{t('proposal', lang)}: {t('fails', lang)}\n"
                f"  {t('infeasible', lang)}\n"
                f"  {t('searched', lang)}: {p.iterations}\n"
                f"  best reached {max(p.utilisation, p.deflection_utilisation):.2f} "
                f"with {', '.join(f'{k}={v}' for k, v in p.sections.items())}")

    lines = [f"{t('proposal', lang)}   {verdict(p.ok, lang)}", ""]
    for role, name in p.sections.items():
        s = get_section(name)
        lines.append(f"  {role:<10s} {name:<16s} {s.mass_per_m:6.1f} kg/m")
    lines += [
        "",
        f"  {t('utilisation', lang):<18s} {p.utilisation:.2f}   "
        f"({t('governing', lang)}: {p.governing})",
        f"  {t('deflection', lang):<18s} {p.deflection_utilisation:.2f}",
        f"  {t('total_mass', lang):<18s} {p.mass_kg:,.0f} kg",
        f"  {t('searched', lang):<18s} {p.iterations}",
    ]
    return "\n".join(lines)
