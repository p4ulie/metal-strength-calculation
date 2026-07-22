"""Steel cross-section properties.

Geometry (h, b, tw, tf, r / d, t) is tabulated in ``data/profiles.json``; every
derived property is computed here from closed-form formulas. One source of
truth, nothing hand-typed that a typo could corrupt, and
``tests/test_sections.py`` cross-checks the results against an independent
mesh-based computation (the ``blue-prints`` package, dev-only).

Units throughout: mm, mm^2, mm^3, mm^4.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "profiles.json"

STEEL_DENSITY = 7850.0  # kg/m^3

# --- Fillet constants -------------------------------------------------------
# A "fillet" is a square of side r minus the inscribed quarter circle: the
# material in a rolled section's root radius, or the material *missing* from a
# hollow section's rounded corner. Derived once, used for both.
_F_AREA = 1.0 - math.pi / 4  # x r^2   = 0.214602
_F_CENT = (5 / 6 - math.pi / 4) / _F_AREA  # x r, centroid from the sharp corner = 0.223400
_F_INER = (1 / 3 - (math.pi / 16 + math.pi / 4 - 2 / 3)) - _F_AREA * _F_CENT**2  # x r^4


@dataclass(frozen=True)
class Section:
    """Cross-section properties. Bending about y is the strong axis."""

    name: str
    family: str  # "I" | "CHS" | "RHS" | "rect" | "round"
    A: float
    h: float
    b: float
    tw: float
    tf: float
    r: float
    Iy: float
    Iz: float
    Wel_y: float
    Wel_z: float
    Wpl_y: float
    Wpl_z: float
    It: float  # St Venant torsion constant
    Iw: float  # warping constant, mm^6
    Av_y: float  # shear area for shear parallel to the web / height
    Av_z: float

    @property
    def iy(self) -> float:
        """Radius of gyration about the strong axis."""
        return math.sqrt(self.Iy / self.A)

    @property
    def iz(self) -> float:
        return math.sqrt(self.Iz / self.A)

    @property
    def mass_per_m(self) -> float:
        """kg/m."""
        return self.A * 1e-6 * STEEL_DENSITY

    @property
    def cf_over_tf(self) -> float:
        """Outstand flange slenderness c/t for classification (EN 1993-1-1 Table 5.2)."""
        if self.family == "I":
            return (self.b - self.tw - 2 * self.r) / 2 / self.tf
        if self.family == "RHS":
            return (self.b - 2 * self.tf - 2 * self.r) / self.tf
        return 0.0

    @property
    def cw_over_tw(self) -> float:
        """Web slenderness c/t."""
        if self.family == "I":
            return (self.h - 2 * self.tf - 2 * self.r) / self.tw
        if self.family == "RHS":
            return (self.h - 2 * self.tf - 2 * self.r) / self.tw
        return 0.0


# --- Closed-form property builders -----------------------------------------


def _i_section(name: str, h: float, b: float, tw: float, tf: float, r: float) -> Section:
    """Doubly symmetric rolled I/H section with root radii."""
    hw = h - 2 * tf  # clear web height
    a_f = _F_AREA * r**2  # area of one root fillet
    i_f = _F_INER * r**4  # its second moment about its own centroid
    c_f = _F_CENT * r  # its centroid, measured from the web/flange corner

    A = 2 * b * tf + hw * tw + 4 * a_f

    # Strong axis: full rectangle minus the two side voids, plus the four fillets.
    dy = h / 2 - tf - c_f  # fillet centroid distance from the neutral axis
    Iy = b * h**3 / 12 - (b - tw) * hw**3 / 12 + 4 * (i_f + a_f * dy**2)

    # Weak axis: two flanges + web + fillets sitting beside the web.
    dz = tw / 2 + c_f
    Iz = 2 * tf * b**3 / 12 + hw * tw**3 / 12 + 4 * (i_f + a_f * dz**2)

    # Plastic moduli = 2 x first moment of the half section about the axis.
    Wpl_y = 2 * (b * tf * (h - tf) / 2 + tw * (h / 2 - tf) ** 2 / 2 + 2 * a_f * dy)
    Wpl_z = 2 * (tf * b**2 / 4 + hw * tw**2 / 8 + 2 * a_f * dz)

    # St Venant torsion, El Darwish & Johnston formula for rolled I-sections:
    # the two flange strips, the web strip, and a junction correction.
    D = ((tf + r) ** 2 + tw * r + tw**2 / 4) / (2 * r + tf) if r > 0 else 0.0
    t_ratio, r_ratio = tw / tf, r / tf
    alpha = (
        -0.042
        + 0.2204 * t_ratio
        + 0.1355 * r_ratio
        - 0.0865 * t_ratio * r_ratio
        - 0.0725 * t_ratio**2
    )
    # Accuracy note: this reproduces catalogue It within about +2..6% (checked
    # against IPE300, HEA200, HEB300). It feeds only M_cr in the LTB check, so
    # treat an LTB utilisation within ~5% of 1.0 as inconclusive.
    It = (2 * b * tf**3 + (h - tf) * tw**3) / 3 + 2 * alpha * D**4

    Iw = Iz * (h - tf) ** 2 / 4

    # EN 1993-1-1 6.2.6(3)a: rolled I, shear parallel to the web.
    Av_y = max(A - 2 * b * tf + (tw + 2 * r) * tf, hw * tw)
    Av_z = 2 * b * tf  # shear parallel to the flanges

    return Section(name, "I", A, h, b, tw, tf, r, Iy, Iz,
                   Iy / (h / 2), Iz / (b / 2), Wpl_y, Wpl_z, It, Iw, Av_y, Av_z)


def _chs(name: str, d: float, t: float) -> Section:
    di = d - 2 * t
    A = math.pi / 4 * (d**2 - di**2)
    I = math.pi / 64 * (d**4 - di**4)
    Wpl = (d**3 - di**3) / 6
    Av = 2 * A / math.pi
    return Section(name, "CHS", A, d, d, t, t, 0.0, I, I,
                   2 * I / d, 2 * I / d, Wpl, Wpl, 2 * I, 0.0, Av, Av)


def _rounded_rect(h: float, b: float, r: float) -> tuple[float, float, float, float, float]:
    """(A, Iy, Iz, Sy, Sz) of a solid rectangle with rounded corners.

    Sy/Sz are half-section first moments, i.e. Wpl = 2 * S.
    """
    a_f = _F_AREA * r**2
    i_f = _F_INER * r**4
    dy = h / 2 - _F_CENT * r
    dz = b / 2 - _F_CENT * r
    A = h * b - 4 * a_f
    Iy = b * h**3 / 12 - 4 * (i_f + a_f * dy**2)
    Iz = h * b**3 / 12 - 4 * (i_f + a_f * dz**2)
    Sy = b * h**2 / 8 - 2 * a_f * dy
    Sz = h * b**2 / 8 - 2 * a_f * dz
    return A, Iy, Iz, Sy, Sz


def _rhs(name: str, h: float, b: float, t: float, ro: float, ri: float) -> Section:
    """Square / rectangular hollow section: outer rounded rectangle minus inner."""
    Ao, Iyo, Izo, Syo, Szo = _rounded_rect(h, b, ro)
    Ai, Iyi, Izi, Syi, Szi = _rounded_rect(h - 2 * t, b - 2 * t, ri)
    A, Iy, Iz = Ao - Ai, Iyo - Iyi, Izo - Izi
    Wpl_y, Wpl_z = 2 * (Syo - Syi), 2 * (Szo - Szi)

    # Bredt: closed thin-walled torsion from the mid-line enclosed area.
    rm = (ro + ri) / 2
    hm, bm = h - t, b - t
    Am = hm * bm - (4 - math.pi) * rm**2
    pm = 2 * (hm + bm) - 8 * rm + 2 * math.pi * rm
    It = 4 * Am**2 * t / pm

    # EN 1993-1-1 6.2.6(3)b: uniform-thickness hollow section.
    Av_y = A * h / (h + b)
    Av_z = A * b / (h + b)
    return Section(name, "RHS", A, h, b, t, t, ro - t, Iy, Iz,
                   Iy / (h / 2), Iz / (b / 2), Wpl_y, Wpl_z, It, 0.0, Av_y, Av_z)


# --- Public API -------------------------------------------------------------


@lru_cache(maxsize=1)
def _profiles() -> dict[str, dict]:
    return json.loads(_DATA.read_text())


def _normalise(name: str) -> str:
    """Accept the ways people actually write profile names.

    ``CHS 114.3x5`` / ``chs114.3X5`` -> ``CHS114_3x5``; the catalogue stores a
    square hollow section as ``SHS100x5``, but ``SHS100x100x5`` is how it is
    usually written, so collapse the repeated dimension.
    """
    key = name.replace(" ", "").replace(".", "_").upper().replace("X", "x")
    if key.startswith("SHS"):
        parts = key[3:].split("x")
        if len(parts) == 3 and parts[0] == parts[1]:
            key = "SHS" + parts[0] + "x" + parts[2]
    return key


def get_section(name: str) -> Section:
    """Look up a catalogue profile, e.g. ``IPE300``, ``HEB200``, ``CHS114.3x5``.

    Spelling variants of the same profile return the same cached object.
    """
    key = _normalise(name)
    if key not in _profiles():
        raise KeyError(f"unknown profile {name!r}; try list_sections() for the catalogue")
    return _build(key)


@lru_cache(maxsize=None)
def _build(key: str) -> Section:
    d = _profiles()[key]
    if d["family"] == "I":
        return _i_section(key, d["h"], d["b"], d["tw"], d["tf"], d["r"])
    if d["family"] == "CHS":
        return _chs(key, d["d"], d["t"])
    return _rhs(key, d["h"], d["b"], d["t"], d["ro"], d["ri"])


def list_sections(family: str | None = None) -> list[str]:
    """Catalogue names, optionally filtered by prefix (``IPE``, ``HEA``, ``CHS``...)."""
    names = list(_profiles())
    if family:
        f = family.upper()
        names = [n for n in names if n.startswith(f)]
    return names


def custom_rectangle(b: float, h: float, name: str = "rect") -> Section:
    """Solid rectangular bar, b wide by h deep. The plain 'metal rod' case."""
    A = b * h
    Iy, Iz = b * h**3 / 12, h * b**3 / 12
    # Solid-rectangle torsion constant, Saint-Venant series approximation.
    a, c = max(b, h) / 2, min(b, h) / 2
    It = a * c**3 * (16 / 3 - 3.36 * c / a * (1 - c**4 / (12 * a**4)))
    return Section(name, "rect", A, h, b, b, h, 0.0, Iy, Iz,
                   b * h**2 / 6, h * b**2 / 6, b * h**2 / 4, h * b**2 / 4,
                   It, 0.0, A * 5 / 6, A * 5 / 6)


def custom_round(d: float, name: str = "round") -> Section:
    """Solid round bar."""
    A = math.pi * d**2 / 4
    I = math.pi * d**4 / 64
    return Section(name, "round", A, d, d, d, d, 0.0, I, I,
                   2 * I / d, 2 * I / d, d**3 / 6, d**3 / 6, 2 * I, 0.0,
                   A * 0.9, A * 0.9)


def custom_tube(d: float, t: float, name: str = "tube") -> Section:
    """Circular hollow bar by outside diameter and wall thickness."""
    return _chs(name, d, t)
