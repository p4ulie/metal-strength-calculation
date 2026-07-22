"""Roof profiles: the shape of one frame, before any section or load is chosen.

A profile is the rafter polyline from the left eaves to the right eaves, in
metres, with ``z`` measured from the ground. Columns are *derived* from it --
one under each end and one under every valley -- so a sawtooth or a multi-span
roof gets its interior columns without anything special being said.

Everything here is pure geometry. :func:`metal_strength.model.roof` turns a
:class:`Frame` into members and loads; :func:`metal_strength.loads.roof_snow_load`
reads its pitches for the Eurocode shape coefficients.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Repeating shapes divide the total span into bays as near this as they can.
BAY_TARGET_M = 10.0
# ponytail: a sawtooth's steep face is 80deg here, not vertical, which keeps the
# profile strictly increasing in x so the purlin and snow logic still holds.
# Model it as a real vertical post if a glazed north-light face ever needs it.
SAWTOOTH_FACE_DEG = 80.0
# Knuckle position as a fraction of the half-span measured from the apex, and
# the pitch of the lower slope below it. --pitch always means the upper slope.
MANSARD_KNUCKLE, MANSARD_LOWER_DEG = 0.6, 60.0
GAMBREL_KNUCKLE, GAMBREL_LOWER_DEG = 0.5, 55.0

SHAPES: tuple[str, ...] = (
    "flat", "monopitch", "duopitch", "mansard", "gambrel", "sawtooth", "multispan",
)

DESCRIPTIONS: dict[str, str] = {
    "flat": "one horizontal plane; pitch is ignored",
    "monopitch": "a single slope, eaves to ridge (a lean-to is the same geometry)",
    "duopitch": "two slopes meeting at a central apex",
    "mansard": "two pitches per side, steep below the knuckle",
    "gambrel": "the barn form of a mansard, knuckle at mid-slope",
    "sawtooth": "repeating monopitch bays with a steep return face and valley columns",
    "multispan": "repeating duopitch bays with valley columns",
    "custom": "a profile drawn by hand; snow coefficients are approximate",
}

# Shapes the Eurocode gives no shape coefficient for, so mu is approximated from
# each segment's own pitch and the answer must be labelled as such.
APPROXIMATE_MU = frozenset({"mansard", "gambrel", "custom"})


@dataclass(frozen=True)
class Segment:
    """One straight run of the frame, in metres."""

    x0: float
    z0: float
    x1: float
    z1: float
    role: str  # "column" | "rafter"

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.z1 - self.z0)

    @property
    def pitch_deg(self) -> float:
        """Slope of the segment, positive uphill to the right."""
        run = self.x1 - self.x0
        if abs(run) < 1e-9:
            return 90.0
        return math.degrees(math.atan2(self.z1 - self.z0, run))


@dataclass(frozen=True)
class Frame:
    """A complete frame profile: the rafter polyline plus its columns."""

    segments: tuple[Segment, ...]
    points: tuple[tuple[float, float], ...]  # rafter polyline, left to right
    shape: str
    # The nominal pitch the profile was built from -- the *upper* slope for the
    # knuckled shapes. Snow coefficients for the other slopes are scaled
    # relative to this one, because it is the pitch the caller quoted.
    pitch_deg: float = 0.0

    @property
    def rafters(self) -> tuple[Segment, ...]:
        return tuple(s for s in self.segments if s.role == "rafter")

    def pitches(self) -> tuple[float, ...]:
        """Absolute pitch in degrees of each rafter segment, left to right."""
        return tuple(abs(s.pitch_deg) for s in self.rafters)

    @property
    def span(self) -> float:
        return self.points[-1][0] - self.points[0][0]

    @property
    def apex_height(self) -> float:
        return max(z for _, z in self.points)

    @property
    def valleys(self) -> tuple[int, ...]:
        """Indices into ``points`` of interior low points -- where columns land."""
        return _valleys(self.points)

    @property
    def mu_is_approximate(self) -> bool:
        return self.shape in APPROXIMATE_MU


def validate(points: list[tuple[float, float]] | tuple[tuple[float, float], ...]) -> None:
    """Reject a profile the downstream model cannot represent.

    Stations march left to right, so x must strictly increase; a profile that
    doubles back or dips underground would silently produce a nonsense frame.
    """
    if len(points) < 2:
        raise ValueError("a profile needs at least two points")
    for (x0, z0), (x1, z1) in zip(points, points[1:]):
        if x1 <= x0:
            raise ValueError(
                f"profile must increase in x, got {x0:.3f} then {x1:.3f}")
        if z0 < 0 or z1 < 0:
            raise ValueError("profile cannot go below ground")
    if min(z for _, z in points) <= 0:
        raise ValueError("every profile point must sit above the ground")


def _valleys(points) -> tuple[int, ...]:
    return tuple(
        i for i in range(1, len(points) - 1)
        if points[i][1] < points[i - 1][1] and points[i][1] < points[i + 1][1]
    )


def from_points(points, shape: str = "custom", pitch_deg: float | None = None) -> Frame:
    """Build a frame from a rafter polyline, adding end and valley columns."""
    pts = tuple((float(x), float(z)) for x, z in points)
    validate(pts)

    segments = [Segment(pts[0][0], 0.0, pts[0][0], pts[0][1], "column")]
    segments += [Segment(a[0], a[1], b[0], b[1], "rafter") for a, b in zip(pts, pts[1:])]
    segments += [Segment(pts[i][0], 0.0, pts[i][0], pts[i][1], "column")
                 for i in _valleys(pts)]
    segments.append(Segment(pts[-1][0], 0.0, pts[-1][0], pts[-1][1], "column"))
    frame_ = Frame(tuple(segments), pts, shape, pitch_deg or 0.0)
    if pitch_deg is None:
        # A hand-drawn profile quotes its shallowest slope, the one a user would
        # call "the pitch".
        frame_ = Frame(frame_.segments, pts, shape, min(frame_.pitches()))
    return frame_


def _bays(span: float) -> int:
    return max(2, round(span / BAY_TARGET_M))


def _knuckled(span: float, pitch_deg: float, eaves: float,
              knuckle: float, lower_deg: float) -> list[tuple[float, float]]:
    """Half-span profile with a steep lower slope, mirrored about the apex."""
    b = span / 2
    run_lower = (1.0 - knuckle) * b
    run_upper = knuckle * b
    z_knuckle = eaves + run_lower * math.tan(math.radians(lower_deg))
    z_apex = z_knuckle + run_upper * math.tan(math.radians(pitch_deg))
    return [
        (0.0, eaves), (run_lower, z_knuckle), (b, z_apex),
        (b + run_upper, z_knuckle), (span, eaves),
    ]


def frame(shape: str, span: float, pitch_deg: float, eaves_height: float) -> Frame:
    """The profile of one frame for a named shape. Lengths in metres."""
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {list(SHAPES)}, got {shape!r}")
    if span <= 0:
        raise ValueError("span must be positive")
    if eaves_height <= 0:
        raise ValueError("eaves height must be positive")
    if not 0 <= pitch_deg < 60:
        raise ValueError("pitch must be between 0 and 60 degrees")

    rise = math.tan(math.radians(pitch_deg))
    b = span / 2

    if shape == "flat":
        pts = [(0.0, eaves_height), (span, eaves_height)]
    elif shape == "monopitch":
        pts = [(0.0, eaves_height), (span, eaves_height + span * rise)]
    elif shape == "duopitch":
        pts = [(0.0, eaves_height), (b, eaves_height + b * rise), (span, eaves_height)]
    elif shape == "mansard":
        pts = _knuckled(span, pitch_deg, eaves_height, MANSARD_KNUCKLE, MANSARD_LOWER_DEG)
    elif shape == "gambrel":
        pts = _knuckled(span, pitch_deg, eaves_height, GAMBREL_KNUCKLE, GAMBREL_LOWER_DEG)
    elif shape == "sawtooth":
        if pitch_deg <= 0:
            raise ValueError("a sawtooth roof needs a pitch above 0")
        n = _bays(span)
        w = span / n
        # Each bay climbs at the given pitch, then returns steeply to the next
        # valley. Solving run_up + face_run = w with face_run = rise*run_up/tan
        # keeps every bay exactly w wide and the face at SAWTOOTH_FACE_DEG.
        run_up = w / (1.0 + rise / math.tan(math.radians(SAWTOOTH_FACE_DEG)))
        pts = [(0.0, eaves_height)]
        for k in range(n):
            x0 = k * w
            pts.append((x0 + run_up, eaves_height + run_up * rise))
            pts.append(((k + 1) * w, eaves_height))
        pts = pts[:-1] + [(span, eaves_height)]
    else:  # multispan
        n = _bays(span)
        w = span / n
        pts = [(0.0, eaves_height)]
        for k in range(n):
            pts.append((k * w + w / 2, eaves_height + (w / 2) * rise))
            pts.append(((k + 1) * w, eaves_height))

    return from_points(pts, shape, pitch_deg)
