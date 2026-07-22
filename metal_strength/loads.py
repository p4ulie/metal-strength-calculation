"""Actions on roofs: snow (EN 1991-1-3), self weight, load combinations (EN 1990).

Units: kN, m, so loads come out in kN/m^2 (area) or kN/m (line).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

# EN 1991-1-3 Annex E, bulk weight density of snow [kN/m^3].
# This is what answers "how much is 1 m of snow" -- a 4x spread by state.
SNOW_DENSITY = {
    "fresh": 1.0,
    "settled": 2.0,  # several hours or days after the fall
    "old": 3.5,  # several weeks or months
    "wet": 4.0,
}

# EN 1991-1-3 Table 5.1, exposure coefficient.
EXPOSURE = {
    "windswept": 0.8,  # flat, unobstructed, exposed on all sides
    "normal": 1.0,
    "sheltered": 1.2,  # sheltered by terrain, trees or taller buildings
}

# EN 1991-1-3 Annex C Table C.1, characteristic ground snow load by climatic
# region. Slovakia, Czechia, Poland, Hungary and Austria-east are "central_east".
# (zone_factor, altitude_divisor)
REGIONS = {
    "alpine": (0.642, 0.009, 728),
    "central_east": (0.264, -0.002, 256),
    "central_west": (0.164, 0.082, 966),
    "greece": (0.420, -0.030, 917),
    "iberian": (0.190, -0.095, 524),
    "mediterranean": (0.498, -0.209, 452),
    "sub_atlantic": (0.164, 0.082, 966),
}


class RoofType(StrEnum):
    MONOPITCH = "monopitch"
    DUOPITCH = "duopitch"


@dataclass(frozen=True)
class SnowCase:
    """One EN 1991-1-3 load arrangement.

    ``left`` and ``right`` are the design snow loads on each slope in kN/m^2,
    measured on the *horizontal projection* of the roof -- which is how the
    Eurocode defines it and how you must apply it to a rafter.
    """

    name: str
    left: float
    right: float

    @property
    def governing(self) -> float:
        return max(self.left, self.right)


def snow_from_depth(depth_m: float, state: str = "settled") -> float:
    """Ground snow load [kN/m^2] from a measured depth and snow state.

    >>> snow_from_depth(1.0, "settled")
    2.0
    """
    if state not in SNOW_DENSITY:
        raise ValueError(f"state must be one of {sorted(SNOW_DENSITY)}, got {state!r}")
    if depth_m < 0:
        raise ValueError("snow depth cannot be negative")
    return depth_m * SNOW_DENSITY[state]


def sk_from_zone(zone: float, altitude_m: float, region: str = "central_east") -> float:
    """Characteristic ground snow load from EN 1991-1-3 Annex C Table C.1.

    ``zone`` is the zone number off the national snow map. Use this when you do
    not have the national annex to hand; if you do, pass its value straight in
    as ``sk`` instead -- the national annex always takes precedence.
    """
    if region not in REGIONS:
        raise ValueError(f"region must be one of {sorted(REGIONS)}, got {region!r}")
    a, b, div = REGIONS[region]
    if altitude_m < 0:
        raise ValueError("altitude cannot be negative")
    return (a * zone + b) * (1 + (altitude_m / div) ** 2)


def mu1(pitch_deg: float, snow_guards: bool = False) -> float:
    """Shape coefficient mu_1, EN 1991-1-3 Table 5.2.

    0.8 up to 30 degrees, falling linearly to 0 at 60, nothing above -- snow
    slides off. Snow guards prevent the slide, so 0.8 is held for all pitches.
    """
    a = abs(pitch_deg)
    if snow_guards:
        return 0.8
    if a <= 30.0:
        return 0.8
    if a >= 60.0:
        return 0.0
    return 0.8 * (60.0 - a) / 30.0


def roof_snow_load(
    sk: float,
    pitch_deg: float,
    roof_type: RoofType | str = RoofType.DUOPITCH,
    exposure: str = "normal",
    Ct: float = 1.0,
    snow_guards: bool = False,
) -> list[SnowCase]:
    """All applicable snow arrangements for a roof: ``s = mu * Ce * Ct * sk``.

    Returns every case the Eurocode requires, not just the balanced one -- the
    governing arrangement differs from member to member, so the caller must run
    all of them and envelope the results.
    """
    if exposure not in EXPOSURE:
        raise ValueError(f"exposure must be one of {sorted(EXPOSURE)}, got {exposure!r}")
    if sk < 0:
        raise ValueError("sk cannot be negative")
    Ce = EXPOSURE[exposure]
    m = mu1(pitch_deg, snow_guards)
    full = m * Ce * Ct * sk
    half = 0.5 * full

    if RoofType(roof_type) is RoofType.MONOPITCH:
        return [SnowCase("balanced", full, full)]

    # EN 1991-1-3 Figure 5.3: balanced, plus two drift cases with one slope at
    # half load (wind has redistributed the snow across the ridge).
    return [
        SnowCase("balanced", full, full),
        SnowCase("drift_left", full, half),
        SnowCase("drift_right", half, full),
    ]


def slope_udl(area_load: float, tributary_width_m: float, pitch_deg: float) -> float:
    """Line load [kN/m] along a *sloping* member from a horizontal-projection area load.

    The Eurocode snow load acts on the plan projection, so a rafter of slope
    alpha picks up ``s * width * cos(alpha)`` per metre measured along the rafter.
    """
    return area_load * tributary_width_m * math.cos(math.radians(pitch_deg))


def self_weight_udl(area_mm2: float) -> float:
    """Self weight of a member as a line load [kN/m] from its area in mm^2."""
    return area_mm2 * 1e-6 * 78.5  # 78.5 kN/m^3 for steel


@dataclass(frozen=True)
class Combination:
    """A factored load combination."""

    name: str
    limit_state: str  # "ULS" | "SLS"
    gamma_G: float
    gamma_Q: float

    def apply(self, permanent: float, variable: float) -> float:
        return self.gamma_G * permanent + self.gamma_Q * variable


# EN 1990 eq. 6.10 with the recommended partial factors. ULS sizes the section;
# SLS (characteristic, unfactored) is what deflection limits are checked against.
ULS = Combination("6.10 ULS", "ULS", 1.35, 1.5)
SLS = Combination("characteristic SLS", "SLS", 1.0, 1.0)
# Uplift / minimum-permanent case: self weight helps you, so do not count on it.
ULS_UPLIFT = Combination("6.10 ULS favourable G", "ULS", 1.0, 1.5)


def demo() -> None:
    """Self-check: the numbers a hand calculation must reproduce."""
    assert snow_from_depth(1.0, "fresh") == 1.0
    assert snow_from_depth(1.0, "settled") == 2.0
    assert snow_from_depth(1.0, "wet") == 4.0

    assert mu1(0) == 0.8 and mu1(30) == 0.8
    assert math.isclose(mu1(45), 0.4)
    assert mu1(60) == 0.0 and mu1(75) == 0.0
    assert mu1(75, snow_guards=True) == 0.8

    # 20 deg duopitch, normal exposure, 1 m of settled snow.
    cases = roof_snow_load(snow_from_depth(1.0, "settled"), 20)
    assert len(cases) == 3
    assert math.isclose(cases[0].left, 0.8 * 1.0 * 1.0 * 2.0)  # 1.6 kN/m^2
    assert math.isclose(cases[1].right, 0.8)

    # Annex C, Slovakia-like: zone 2 at 400 m.
    sk = sk_from_zone(2, 400)
    assert math.isclose(sk, (0.264 * 2 - 0.002) * (1 + (400 / 256) ** 2), rel_tol=1e-12)

    assert math.isclose(ULS.apply(1.0, 2.0), 1.35 + 3.0)
    print("loads: ok")


if __name__ == "__main__":
    demo()
