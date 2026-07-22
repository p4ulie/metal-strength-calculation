"""3D frame analysis by the direct stiffness method.

Pure mechanics -- no Eurocode anywhere in this file, so it can be validated
against closed-form solutions independently of any design code.

Six degrees of freedom per node: ``ux uy uz rx ry rz``. Global Z is up.
Units: N, mm, N/mm^2 (MPa). Convert at the boundary, not in here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DOF = 6
_VERTICAL_TOL = 1e-8


@dataclass
class Node:
    x: float
    y: float
    z: float

    @property
    def xyz(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], float)


@dataclass
class Member:
    """A prismatic frame element between two node indices.

    ``roll`` rotates the cross-section about the member axis (radians): 0 puts
    the strong axis (Iy) in the vertical plane, which is how a beam is normally
    installed.

    ``releases`` names end degrees of freedom to condense out, as
    ``("i", dof)`` / ``("j", dof)`` with dof in ``ux uy uz rx ry rz``. Pinning
    both ends' ``ry`` and ``rz`` makes a truss diagonal.
    """

    i: int
    j: int
    E: float
    G: float
    A: float
    Iy: float
    Iz: float
    It: float
    roll: float = 0.0
    releases: tuple[tuple[str, str], ...] = ()
    tag: str = ""


@dataclass
class MemberLoad:
    """Uniformly distributed load on a member, in N/mm."""

    member: int
    wx: float = 0.0  # local axial
    wy: float = 0.0  # local y
    wz: float = 0.0  # local z
    globalz: float = 0.0  # convenience: N/mm acting along global -Z (gravity)


@dataclass
class Structure:
    nodes: list[Node]
    members: list[Member]
    # node index -> six booleans, True where the DOF is restrained
    supports: dict[int, tuple[bool, bool, bool, bool, bool, bool]] = field(default_factory=dict)
    # node index -> six values (Fx Fy Fz Mx My Mz) in N and N*mm
    nodal_loads: dict[int, tuple[float, float, float, float, float, float]] = field(
        default_factory=dict
    )
    member_loads: list[MemberLoad] = field(default_factory=list)

    @property
    def ndof(self) -> int:
        return len(self.nodes) * DOF


_DOF_INDEX = {"ux": 0, "uy": 1, "uz": 2, "rx": 3, "ry": 4, "rz": 5}


def member_length(s: Structure, m: Member) -> float:
    return float(np.linalg.norm(s.nodes[m.j].xyz - s.nodes[m.i].xyz))


def rotation_matrix(s: Structure, m: Member) -> np.ndarray:
    """3x3 direction cosines mapping global vectors into the member's local frame."""
    v = s.nodes[m.j].xyz - s.nodes[m.i].xyz
    L = np.linalg.norm(v)
    if L == 0:
        raise ValueError(f"member {m.i}-{m.j} has zero length")
    ex = v / L
    d = float(np.hypot(ex[0], ex[1]))

    if d < _VERTICAL_TOL:
        # Member is parallel to global Z; the usual formula is singular there.
        sign = float(np.sign(ex[2]))
        R = np.array([[0.0, 0.0, sign], [0.0, 1.0, 0.0], [-sign, 0.0, 0.0]])
    else:
        R = np.array(
            [
                [ex[0], ex[1], ex[2]],
                [-ex[1] / d, ex[0] / d, 0.0],
                [-ex[0] * ex[2] / d, -ex[1] * ex[2] / d, d],
            ]
        )

    if m.roll:
        c, sn = np.cos(m.roll), np.sin(m.roll)
        roll = np.array([[1.0, 0.0, 0.0], [0.0, c, sn], [0.0, -sn, c]])
        R = roll @ R
    return R


def transformation(s: Structure, m: Member) -> np.ndarray:
    """12x12 block-diagonal transformation from global to local DOFs."""
    R = rotation_matrix(s, m)
    T = np.zeros((12, 12))
    for k in range(4):
        T[3 * k : 3 * k + 3, 3 * k : 3 * k + 3] = R
    return T


def local_stiffness(m: Member, L: float) -> np.ndarray:
    """Standard 12x12 prismatic 3D beam element (Euler-Bernoulli)."""
    E, G, A, Iy, Iz, J = m.E, m.G, m.A, m.Iy, m.Iz, m.It
    k = np.zeros((12, 12))

    ea = E * A / L
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea

    gj = G * J / L
    k[3, 3] = k[9, 9] = gj
    k[3, 9] = k[9, 3] = -gj

    # Bending in the local x-y plane -> uses Iz, couples uy with rz.
    a, b, c = 12 * E * Iz / L**3, 6 * E * Iz / L**2, 2 * E * Iz / L
    k[1, 1] = k[7, 7] = a
    k[1, 7] = k[7, 1] = -a
    k[1, 5] = k[5, 1] = k[1, 11] = k[11, 1] = b
    k[5, 7] = k[7, 5] = k[7, 11] = k[11, 7] = -b
    k[5, 5] = k[11, 11] = 2 * c
    k[5, 11] = k[11, 5] = c

    # Bending in the local x-z plane -> uses Iy, couples uz with ry.
    a, b, c = 12 * E * Iy / L**3, 6 * E * Iy / L**2, 2 * E * Iy / L
    k[2, 2] = k[8, 8] = a
    k[2, 8] = k[8, 2] = -a
    k[2, 4] = k[4, 2] = k[2, 10] = k[10, 2] = -b
    k[4, 8] = k[8, 4] = k[8, 10] = k[10, 8] = b
    k[4, 4] = k[10, 10] = 2 * c
    k[4, 10] = k[10, 4] = c
    return k


def equivalent_nodal_loads(wx: float, wy: float, wz: float, L: float) -> np.ndarray:
    """Equivalent joint loads for a UDL, in local coordinates (12 values)."""
    p = np.zeros(12)
    p[0] = p[6] = wx * L / 2
    p[1] = p[7] = wy * L / 2
    p[5], p[11] = wy * L**2 / 12, -wy * L**2 / 12
    p[2] = p[8] = wz * L / 2
    p[4], p[10] = -wz * L**2 / 12, wz * L**2 / 12
    return p


def _condense(k: np.ndarray, p: np.ndarray, released: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Static condensation of released end DOFs (moment hinges, axial releases)."""
    if not released:
        return k, p
    keep = [i for i in range(12) if i not in released]
    krr, krc = k[np.ix_(keep, keep)], k[np.ix_(keep, released)]
    kcc = k[np.ix_(released, released)]
    if abs(np.linalg.det(kcc)) < 1e-12:
        raise ValueError("release set makes the element mechanism-singular")
    kcc_inv = np.linalg.inv(kcc)
    kc = krr - krc @ kcc_inv @ k[np.ix_(released, keep)]
    pc = p[keep] - krc @ kcc_inv @ p[released]

    k_out, p_out = np.zeros((12, 12)), np.zeros(12)
    k_out[np.ix_(keep, keep)] = kc
    p_out[keep] = pc
    return k_out, p_out


def _released_indices(m: Member) -> list[int]:
    out = []
    for end, name in m.releases:
        if name not in _DOF_INDEX:
            raise ValueError(f"unknown release DOF {name!r}")
        out.append(_DOF_INDEX[name] + (0 if end == "i" else 6))
    return sorted(set(out))


@dataclass
class Results:
    displacements: np.ndarray  # (nnodes, 6) global
    reactions: np.ndarray  # (nnodes, 6) global, zero at free DOFs
    end_forces: np.ndarray  # (nmembers, 12) local
    lengths: np.ndarray
    local_udl: np.ndarray  # (nmembers, 3) resolved wx, wy, wz

    def diagram(self, member: int, n: int = 21) -> dict[str, np.ndarray]:
        """Internal actions sampled along a member.

        Returns ``x`` (mm from end i) plus ``N``, ``Vy``, ``Vz``, ``T``, ``My``,
        ``Mz``. Each is the negated resultant of everything acting on the free
        body to the left of the cut, so hogging is positive and sagging
        negative -- consistent between the two bending planes.
        """
        q = self.end_forces[member]
        L = self.lengths[member]
        wx, wy, wz = self.local_udl[member]
        x = np.linspace(0.0, L, n)
        return {
            "x": x,
            "N": -(q[0] + wx * x),
            "Vy": -(q[1] + wy * x),
            "Vz": -(q[2] + wz * x),
            "T": np.full_like(x, -q[3]),
            "My": -(q[4] + q[2] * x + wz * x**2 / 2),
            "Mz": -(q[5] - q[1] * x - wy * x**2 / 2),
        }

    def peak(self, member: int, n: int = 101) -> dict[str, float]:
        """Largest absolute internal action along a member (what design checks need)."""
        d = self.diagram(member, n)
        return {
            "N": float(d["N"][np.argmax(np.abs(d["N"]))]),
            "Vy": float(np.max(np.abs(d["Vy"]))),
            "Vz": float(np.max(np.abs(d["Vz"]))),
            "T": float(np.max(np.abs(d["T"]))),
            "My": float(np.max(np.abs(d["My"]))),
            "Mz": float(np.max(np.abs(d["Mz"]))),
        }


def solve(s: Structure) -> Results:
    """Assemble, apply supports, solve, and recover member end forces."""
    n = s.ndof
    K = np.zeros((n, n))
    P = np.zeros(n)

    lengths = np.array([member_length(s, m) for m in s.members])
    local_udl = np.zeros((len(s.members), 3))

    # Resolve member loads into the local frame once, so force recovery can reuse them.
    for ml in s.member_loads:
        m = s.members[ml.member]
        R = rotation_matrix(s, m)
        w = np.array([ml.wx, ml.wy, ml.wz]) + R @ np.array([0.0, 0.0, -ml.globalz])
        local_udl[ml.member] += w

    for e, m in enumerate(s.members):
        L = lengths[e]
        k = local_stiffness(m, L)
        p = equivalent_nodal_loads(*local_udl[e], L)
        k, p = _condense(k, p, _released_indices(m))

        T = transformation(s, m)
        kg = T.T @ k @ T
        pg = T.T @ p

        dofs = np.r_[m.i * DOF : m.i * DOF + DOF, m.j * DOF : m.j * DOF + DOF]
        K[np.ix_(dofs, dofs)] += kg
        P[dofs] += pg

    for idx, load in s.nodal_loads.items():
        P[idx * DOF : idx * DOF + DOF] += np.asarray(load, float)

    fixed = np.zeros(n, bool)
    for idx, mask in s.supports.items():
        fixed[idx * DOF : idx * DOF + DOF] = np.asarray(mask, bool)
    free = ~fixed
    if not free.any():
        raise ValueError("every degree of freedom is restrained")

    Kff = K[np.ix_(free, free)]
    if np.linalg.cond(Kff) > 1e14:
        raise ValueError(
            "stiffness matrix is singular -- the structure is a mechanism. "
            "Check supports, and that any released members are still restrained."
        )

    u = np.zeros(n)
    u[free] = np.linalg.solve(Kff, P[free])
    reactions = K @ u - P
    reactions[free] = 0.0

    end_forces = np.zeros((len(s.members), 12))
    for e, m in enumerate(s.members):
        L = lengths[e]
        k = local_stiffness(m, L)
        p = equivalent_nodal_loads(*local_udl[e], L)
        k, p = _condense(k, p, _released_indices(m))
        T = transformation(s, m)
        dofs = np.r_[m.i * DOF : m.i * DOF + DOF, m.j * DOF : m.j * DOF + DOF]
        end_forces[e] = k @ (T @ u[dofs]) - p

    return Results(
        u.reshape(-1, DOF), reactions.reshape(-1, DOF), end_forces, lengths, local_udl
    )


# --- Convenience builders ---------------------------------------------------


def simple_beam(
    L: float, E: float, G: float, A: float, Iy: float, Iz: float, It: float,
    w: float = 0.0, P: float = 0.0, fixity: str = "simple",
) -> Structure:
    """A single beam along global X, loaded downward (global -Z).

    ``w`` is a UDL in N/mm, ``P`` a midspan point load in N. ``fixity`` is
    ``simple``, ``cantilever``, ``fixed`` or ``propped``.
    """
    mid = P != 0.0
    xs = [0.0, L / 2, L] if mid else [0.0, L]
    nodes = [Node(x, 0.0, 0.0) for x in xs]
    mk = lambda i, j: Member(i, j, E, G, A, Iy, Iz, It)
    members = [mk(k, k + 1) for k in range(len(nodes) - 1)]

    ALL = (True,) * 6
    PIN = (True, True, True, True, False, False)
    ROLLER = (False, True, True, True, False, False)
    last = len(nodes) - 1
    supports = {
        "simple": {0: PIN, last: ROLLER},
        "cantilever": {0: ALL},
        "fixed": {0: ALL, last: ALL},
        "propped": {0: ALL, last: ROLLER},
    }[fixity]

    s = Structure(nodes, members, dict(supports))
    if w:
        s.member_loads = [MemberLoad(e, globalz=w) for e in range(len(members))]
    if P:
        s.nodal_loads[1] = (0.0, 0.0, -P, 0.0, 0.0, 0.0)
    return s
