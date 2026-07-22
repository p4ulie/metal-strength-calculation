"""EN 1993-1-1 resistance and stability checks for steel members.

Every check returns its utilisation together with the clause it came from, so a
result can be explained and audited rather than just believed.

Units: N, mm, MPa. Utilisation <= 1.0 passes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .sections import Section

E = 210_000.0  # MPa
G = 81_000.0  # MPa
NU = 0.3

# EN 1993-1-1 Table 3.1. (fy, fu) for t <= 40 mm and for 40 < t <= 80 mm.
GRADES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "S235": ((235.0, 360.0), (215.0, 360.0)),
    "S275": ((275.0, 430.0), (255.0, 410.0)),
    "S355": ((355.0, 490.0), (335.0, 470.0)),
    "S420": ((420.0, 520.0), (390.0, 520.0)),
    "S460": ((460.0, 540.0), (430.0, 540.0)),
}

# EN 1993-1-1 Table 6.1 -- recommended values; override for a national annex.
GAMMA_M0 = 1.0  # cross-section resistance
GAMMA_M1 = 1.0  # member stability
GAMMA_M2 = 1.25  # net section / connections

# EN 1993-1-1 Table 6.1, imperfection factor per buckling curve.
ALPHA = {"a0": 0.13, "a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}

# Deflection limits, EN 1993-1-1 NA / EN 1990 Annex A1. span / value.
DEFLECTION_LIMITS = {"roof_general": 200.0, "roof_brittle_finish": 250.0, "floor": 250.0}


def yield_strength(grade: str, thickness: float) -> tuple[float, float]:
    """(fy, fu) in MPa for a grade and the governing plate thickness in mm."""
    g = grade.upper()
    if g not in GRADES:
        raise ValueError(f"grade must be one of {sorted(GRADES)}, got {grade!r}")
    if thickness > 80.0:
        raise ValueError("EN 1993-1-1 Table 3.1 stops at 80 mm; use EN 10025 directly")
    return GRADES[g][0 if thickness <= 40.0 else 1]


def epsilon(fy: float) -> float:
    """Material factor eps = sqrt(235/fy), used by every slenderness limit."""
    return math.sqrt(235.0 / fy)


@dataclass
class Check:
    """One verification: what was checked, against what, and how close it came."""

    name: str
    clause: str
    demand: float
    capacity: float
    unit: str = ""
    note: str = ""

    @property
    def utilisation(self) -> float:
        if self.capacity == 0:
            return math.inf if self.demand else 0.0
        return abs(self.demand) / abs(self.capacity)

    @property
    def ok(self) -> bool:
        return self.utilisation <= 1.0

    def __str__(self) -> str:
        flag = "OK " if self.ok else "FAIL"
        return (f"{flag} {self.name:<28s} {self.utilisation:5.2f}  "
                f"{self.demand:.3g}/{self.capacity:.3g} {self.unit}  [{self.clause}]"
                + (f"  {self.note}" if self.note else ""))


@dataclass
class MemberForces:
    """Design actions on a member. Sign of N: positive is tension."""

    N: float = 0.0
    Vy: float = 0.0
    Vz: float = 0.0
    My: float = 0.0
    Mz: float = 0.0
    T: float = 0.0


@dataclass
class BucklingLengths:
    """Effective lengths for stability, in mm. Default to the member length."""

    Lcr_y: float
    Lcr_z: float
    L_LT: float  # distance between lateral restraints to the compression flange
    C1: float = 1.13  # moment-shape factor for M_cr; 1.13 = UDL on a simple span


@dataclass
class MemberResult:
    section: str
    grade: str
    fy: float
    section_class: int
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def utilisation(self) -> float:
        return max((c.utilisation for c in self.checks), default=0.0)

    @property
    def governing(self) -> Check | None:
        return max(self.checks, key=lambda c: c.utilisation, default=None)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def report(self) -> str:
        head = (f"{self.section} {self.grade} (fy={self.fy:.0f} MPa, "
                f"class {self.section_class}) -- utilisation {self.utilisation:.2f}")
        lines = [head, "-" * len(head)]
        lines += [str(c) for c in sorted(self.checks, key=lambda c: -c.utilisation)]
        lines += [f"  ! {w}" for w in self.warnings]
        return "\n".join(lines)


# --- Cross-section classification (Table 5.2) -------------------------------


def classify(s: Section, fy: float, N: float = 0.0, M: float = 0.0) -> tuple[int, list[str]]:
    """Classify a cross-section under the given axial force and major-axis moment.

    ``N`` positive is tension (which cannot cause local buckling, so it is
    treated as pure bending).
    """
    warn: list[str] = []
    if s.family in ("CHS",):
        # Table 5.2 sheet 3: tubular sections classify on d/t.
        dt = s.h / s.tw
        e2 = epsilon(fy) ** 2
        for limit, cls in ((50 * e2, 1), (70 * e2, 2), (90 * e2, 3)):
            if dt <= limit:
                return cls, warn
        return 4, warn
    if s.family in ("rect", "round"):
        return 1, warn  # solid sections cannot buckle locally

    eps = epsilon(fy)
    cf, cw = s.cf_over_tf, s.cw_over_tw
    Nc = max(-N, 0.0)  # compression only

    # Flange: outstand for an I, internal for a hollow section.
    if s.family == "I":
        flange_limits = (9 * eps, 10 * eps, 14 * eps)
    else:
        flange_limits = (33 * eps, 38 * eps, 42 * eps)
    flange_cls = next((c for lim, c in zip(flange_limits, (1, 2, 3)) if cf <= lim), 4)

    # Web: the stress distribution depends on how much of it is in compression.
    c_web = cw * s.tw
    if M == 0.0 and Nc > 0.0:
        web_limits = (33 * eps, 38 * eps, 42 * eps)  # pure compression
    elif Nc == 0.0:
        web_limits = (72 * eps, 83 * eps, 124 * eps)  # pure bending
    else:
        # Combined: alpha is the compressed proportion of the web depth.
        alpha = min(max(0.5 * (1 + Nc / (fy * s.tw * c_web)), 0.0), 1.0)
        c1 = 396 * eps / (13 * alpha - 1) if alpha > 0.5 else 36 * eps / alpha
        c2 = 456 * eps / (13 * alpha - 1) if alpha > 0.5 else 41.5 * eps / alpha
        # Elastic stress ratio at the two web edges.
        sig_n = Nc / s.A
        sig_m = abs(M) / s.Wel_y if s.Wel_y else 0.0
        psi = (sig_n - sig_m) / (sig_n + sig_m) if (sig_n + sig_m) else -1.0
        psi = min(max(psi, -3.0), 1.0)
        c3 = (42 * eps / (0.67 + 0.33 * psi) if psi > -1
              else 62 * eps * (1 - psi) * math.sqrt(-psi))
        web_limits = (c1, c2, c3)
    web_cls = next((c for lim, c in zip(web_limits, (1, 2, 3)) if cw <= lim), 4)

    cls = max(flange_cls, web_cls)
    if cls == 4:
        warn.append(
            "class 4 section: local buckling reduces the effective cross-section "
            "(EN 1993-1-5). This tool does not compute effective widths -- the "
            "resistances below are NOT valid."
        )
    return cls, warn


# --- Resistances ------------------------------------------------------------


def section_modulus(s: Section, cls: int, axis: str = "y") -> float:
    """W to use for bending resistance, per section class."""
    if axis == "y":
        return s.Wpl_y if cls <= 2 else s.Wel_y
    return s.Wpl_z if cls <= 2 else s.Wel_z


def buckling_curve(s: Section, fy: float, axis: str) -> str:
    """EN 1993-1-1 Table 6.2."""
    if s.family == "CHS" or s.family == "RHS":
        return "a" if fy <= 460 else "a0"  # hot finished; cold formed would be "c"
    if s.family in ("rect", "round"):
        return "c"
    hb = s.h / s.b
    tf = s.tf
    if fy >= 460:
        return "a0"
    if hb > 1.2:
        if tf <= 40:
            return "a" if axis == "y" else "b"
        return "b" if axis == "y" else "c"
    if tf <= 100:
        return "b" if axis == "y" else "c"
    return "d"


def chi(lambda_bar: float, curve: str) -> float:
    """Flexural buckling reduction factor, EN 1993-1-1 6.3.1.2."""
    if lambda_bar <= 0.2:
        return 1.0
    a = ALPHA[curve]
    phi = 0.5 * (1 + a * (lambda_bar - 0.2) + lambda_bar**2)
    return min(1.0, 1.0 / (phi + math.sqrt(max(phi**2 - lambda_bar**2, 0.0))))


def flexural_buckling(s: Section, fy: float, Lcr: float, axis: str) -> tuple[float, float, float]:
    """(N_b_Rd, chi, lambda_bar) for buckling about the given axis."""
    i = s.iy if axis == "y" else s.iz
    lam1 = 93.9 * epsilon(fy)
    lam = (Lcr / i) / lam1 if i > 0 else 0.0
    x = chi(lam, buckling_curve(s, fy, axis))
    return x * s.A * fy / GAMMA_M1, x, lam


def critical_moment(s: Section, L: float, C1: float = 1.13) -> float:
    """Elastic critical moment for lateral-torsional buckling.

    General case for a doubly symmetric section, ends free to warp and rotate
    about the weak axis (k = kw = 1), load applied at the shear centre.
    """
    if s.Iw == 0.0 and s.family in ("CHS", "RHS"):
        return math.inf  # closed sections are not susceptible to LTB
    if L <= 0:
        return math.inf
    return (C1 * math.pi**2 * E * s.Iz / L**2
            * math.sqrt(s.Iw / s.Iz + L**2 * G * s.It / (math.pi**2 * E * s.Iz)))


def lateral_torsional_buckling(
    s: Section, fy: float, cls: int, L: float, C1: float = 1.13
) -> tuple[float, float, float]:
    """(M_b_Rd, chi_LT, lambda_bar_LT), EN 1993-1-1 6.3.2.3 for rolled sections."""
    Wy = section_modulus(s, cls, "y")
    Mcr = critical_moment(s, L, C1)
    if math.isinf(Mcr):
        return Wy * fy / GAMMA_M1, 1.0, 0.0
    lam = math.sqrt(Wy * fy / Mcr)
    if lam <= 0.4:  # lambda_LT_0 for rolled sections
        return Wy * fy / GAMMA_M1, 1.0, lam
    a_lt = 0.34 if s.h / s.b <= 2.0 else 0.49  # Table 6.5
    beta = 0.75
    phi = 0.5 * (1 + a_lt * (lam - 0.4) + beta * lam**2)
    x = 1.0 / (phi + math.sqrt(max(phi**2 - beta * lam**2, 0.0)))
    x = min(x, 1.0, 1.0 / lam**2)
    return x * Wy * fy / GAMMA_M1, x, lam


# --- The full member check --------------------------------------------------


def check_member(
    s: Section,
    grade: str,
    forces: MemberForces,
    lengths: BucklingLengths,
    deflection: float | None = None,
    span: float | None = None,
    deflection_limit: str = "roof_general",
    Cm: float = 0.9,
) -> MemberResult:
    """Run every EN 1993-1-1 check that applies and return the collected result.

    ``forces`` are design (factored) actions. ``deflection`` and ``span`` are
    optional and, if given, are checked at the serviceability limit state --
    pass the *unfactored* deflection.
    """
    fy, _fu = yield_strength(grade, max(s.tf, s.tw))
    cls, warns = classify(s, fy, forces.N, forces.My)
    res = MemberResult(s.name, grade.upper(), fy, cls, warnings=list(warns))

    Nc = max(-forces.N, 0.0)  # compression magnitude
    Nt = max(forces.N, 0.0)

    # -- axial ---------------------------------------------------------------
    if Nt:
        res.checks.append(Check("tension", "6.2.3", Nt, s.A * fy / GAMMA_M0, "N"))
    if Nc:
        res.checks.append(Check("compression (section)", "6.2.4", Nc,
                                s.A * fy / GAMMA_M0, "N"))

    # -- shear ---------------------------------------------------------------
    Vpl_z = s.Av_y * (fy / math.sqrt(3)) / GAMMA_M0  # shear parallel to the web
    Vpl_y = s.Av_z * (fy / math.sqrt(3)) / GAMMA_M0
    if forces.Vz:
        res.checks.append(Check("shear z (web)", "6.2.6", abs(forces.Vz), Vpl_z, "N"))
    if forces.Vy:
        res.checks.append(Check("shear y", "6.2.6", abs(forces.Vy), Vpl_y, "N"))

    # -- bending, with shear interaction where it bites ----------------------
    Wy = section_modulus(s, cls, "y")
    Mc_y = Wy * fy / GAMMA_M0
    note = ""
    if Vpl_z and abs(forces.Vz) > 0.5 * Vpl_z and s.family == "I":
        rho = (2 * abs(forces.Vz) / Vpl_z - 1) ** 2
        Aw = (s.h - 2 * s.tf) * s.tw
        Mc_y = min(Mc_y, (Wy - rho * Aw**2 / (4 * s.tw)) * fy / GAMMA_M0)
        note = f"reduced for high shear (rho={rho:.2f}, 6.2.8)"
    if forces.My:
        res.checks.append(Check("bending y (section)", "6.2.5", abs(forces.My),
                                Mc_y, "Nmm", note))
    Mc_z = section_modulus(s, cls, "z") * fy / GAMMA_M0
    if forces.Mz:
        res.checks.append(Check("bending z (section)", "6.2.5", abs(forces.Mz),
                                Mc_z, "Nmm"))

    # -- torsion -------------------------------------------------------------
    if forces.T and s.It:
        tau = abs(forces.T) * max(s.tf, s.tw) / s.It  # St Venant shear stress
        res.checks.append(Check("torsion (St Venant)", "6.2.7", tau,
                                fy / math.sqrt(3) / GAMMA_M0, "MPa",
                                "warping torsion not included"))

    # -- member stability ----------------------------------------------------
    Nb_y, chi_y, lam_y = flexural_buckling(s, fy, lengths.Lcr_y, "y")
    Nb_z, chi_z, lam_z = flexural_buckling(s, fy, lengths.Lcr_z, "z")
    Mb, chi_lt, lam_lt = lateral_torsional_buckling(s, fy, cls, lengths.L_LT, lengths.C1)

    if Nc:
        res.checks.append(Check("buckling y-y", "6.3.1", Nc, Nb_y, "N",
                                f"chi={chi_y:.3f}, lambda={lam_y:.2f}"))
        res.checks.append(Check("buckling z-z", "6.3.1", Nc, Nb_z, "N",
                                f"chi={chi_z:.3f}, lambda={lam_z:.2f}"))
    if forces.My and s.family == "I":
        res.checks.append(Check("lateral-torsional", "6.3.2", abs(forces.My), Mb, "Nmm",
                                f"chi_LT={chi_lt:.3f}, lambda_LT={lam_lt:.2f}, "
                                f"L={lengths.L_LT:.0f}mm"))

    # -- combined axial + bending (6.61 / 6.62, Annex B) ---------------------
    if Nc and (forces.My or forces.Mz):
        NRk = s.A * fy
        MyRk = section_modulus(s, cls, "y") * fy
        MzRk = section_modulus(s, cls, "z") * fy
        ny = Nc / (chi_y * NRk / GAMMA_M1)
        nz = Nc / (chi_z * NRk / GAMMA_M1)
        kyy = min(Cm * (1 + (lam_y - 0.2) * ny), Cm * (1 + 0.8 * ny))
        kzz = min(Cm * (1 + (2 * lam_z - 0.6) * nz), Cm * (1 + 1.4 * nz))
        kyz = 0.6 * kzz
        # kzy only bites once the member is LTB-sensitive; below that it is 1.0.
        kzy = (max(1 - 0.1 * lam_lt * nz / (Cm - 0.25), 1 - 0.1 * nz / (Cm - 0.25))
               if lam_lt >= 0.4 else 1.0)
        My_term = abs(forces.My) / (chi_lt * MyRk / GAMMA_M1)
        Mz_term = abs(forces.Mz) / (MzRk / GAMMA_M1) if MzRk else 0.0
        u61 = Nc / (chi_y * NRk / GAMMA_M1) + kyy * My_term + kyz * Mz_term
        u62 = Nc / (chi_z * NRk / GAMMA_M1) + kzy * My_term + kzz * Mz_term
        res.checks.append(Check("combined N+M (6.61)", "6.3.3 eq 6.61", u61, 1.0, "-",
                                f"kyy={kyy:.2f}"))
        res.checks.append(Check("combined N+M (6.62)", "6.3.3 eq 6.62", u62, 1.0, "-",
                                f"kzy={kzy:.2f}, kzz={kzz:.2f}"))
        res.warnings.append(
            f"interaction factors use Cm={Cm} (Annex B); refine Cmy/Cmz/CmLT "
            "from the actual moment diagram for a final design"
        )

    # -- serviceability ------------------------------------------------------
    if deflection is not None and span:
        limit = span / DEFLECTION_LIMITS[deflection_limit]
        res.checks.append(Check(f"deflection (L/{DEFLECTION_LIMITS[deflection_limit]:.0f})",
                                "EN 1990 A1.4", abs(deflection), limit, "mm",
                                "serviceability, unfactored loads"))

    if cls == 4:
        res.warnings.append("results above are invalid for a class 4 section")
    return res


def demo() -> None:
    """Self-check against hand calculations and published worked examples."""
    from .sections import get_section

    # -- material and epsilon
    assert yield_strength("S235", 10) == (235.0, 360.0)
    assert yield_strength("S355", 50) == (335.0, 470.0)
    assert math.isclose(epsilon(235.0), 1.0)
    assert math.isclose(epsilon(355.0), math.sqrt(235 / 355))

    # -- IPE300 S235 in pure bending is class 1, Mc,Rd = Wpl*fy
    s = get_section("IPE300")
    cls, _ = classify(s, 235.0, N=0.0, M=1e8)
    assert cls == 1, cls
    assert math.isclose(section_modulus(s, cls) * 235.0, 628.4e3 * 235, rel_tol=2e-3)

    # -- buckling curve selection, Table 6.2: IPE300 h/b=2.0>1.2, tf<40
    assert buckling_curve(s, 235.0, "y") == "a"
    assert buckling_curve(s, 235.0, "z") == "b"
    # HEB300 h/b = 1.0 <= 1.2
    assert buckling_curve(get_section("HEB300"), 235.0, "y") == "b"

    # -- chi is monotonic, bounded, and equals 1 below the plateau
    assert chi(0.1, "b") == 1.0
    assert 0.0 < chi(2.0, "b") < chi(1.0, "b") < chi(0.5, "b") <= 1.0

    # -- a stocky column reaches the squash load; a slender one does not
    nb_short, x_short, _ = flexural_buckling(s, 235.0, 500.0, "z")
    assert math.isclose(x_short, 1.0)
    nb_long, x_long, lam = flexural_buckling(s, 235.0, 6000.0, "z")
    assert x_long < 0.5 and nb_long < nb_short

    # -- closed sections are immune to LTB
    assert math.isinf(critical_moment(get_section("SHS100x100x5"), 5000.0))

    # -- a short span does not need an LTB reduction; a long one does
    _, x1, _ = lateral_torsional_buckling(s, 235.0, 1, 1000.0)
    _, x2, _ = lateral_torsional_buckling(s, 235.0, 1, 8000.0)
    assert x1 == 1.0 and x2 < 0.6

    print("ec3: ok")


if __name__ == "__main__":
    demo()
