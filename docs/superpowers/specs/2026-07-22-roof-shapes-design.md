# Roof shapes — design

Date: 2026-07-22
Status: implemented (2026-07-22)

## Goal

Let the user pick a roof shape instead of always getting a duopitch portal
frame, and get Eurocode snow arrangements that actually match the shape picked.

Shapes in this cut, all of them a constant profile extruded along Y:

| shape | notes |
|---|---|
| `flat` | pitch forced to 0 |
| `monopitch` | single slope; lean-to is an alias, same geometry |
| `duopitch` | what `pitched_roof()` builds today |
| `mansard` | two pitches per side, steep below the knuckle |
| `gambrel` | mansard's barn form; break at mid-span |
| `sawtooth` | repeating monopitch bays with valley columns |
| `multispan` | repeating duopitch bays with valley columns |

Explicitly **out of scope**: hipped, pyramidal, conical, domed and butterfly
roofs. They are not a constant profile extruded along Y — hips converge, so
frames stop being identical and the purlin tributary and snow application both
break. That is a separate, much larger piece of work.

## Non-goals

- Per-shape geometry knobs on the CLI. Proportions are baked into the presets.
- Wind loading. Not covered today and not added here.

## Architecture

### 1. `metal_strength/shapes.py` — the profile primitive

```python
@dataclass(frozen=True)
class Segment:      # one straight run of the frame, eaves-to-eaves left -> right
    x0: float; z0: float; x1: float; z1: float
    role: str       # "column" | "rafter"

@dataclass(frozen=True)
class Frame:
    segments: tuple[Segment, ...]
    shape: str
    def pitches(self) -> tuple[float, ...]:
        """Pitch in degrees of each rafter segment, left to right."""

SHAPES: tuple[str, ...]                     # for --help, list_shapes, i18n
def frame(shape, span, pitch_deg, eaves_height) -> Frame
```

`frame()` is pure geometry: no sections, no loads, no solver. Metres, `z`
measured from ground, eaves at `eaves_height`.

Repeating shapes (`sawtooth`, `multispan`) treat `span` as the **total** width
and divide it into `max(2, round(span / BAY_TARGET_M))` bays, `BAY_TARGET_M =
10.0` — one module-level constant, changed in one place. Every valley gets a
column to ground.

Baked proportions, defined so `pitch_deg` keeps one unambiguous meaning — it is
always the **upper** slope, and the apex rise follows from the geometry rather
than being an input:

- **mansard**: knuckle at 0.6 of the half-span measured from the apex; upper
  slope `pitch_deg`, lower slope 60 degrees. Apex rise above the eaves is
  therefore `0.4*b*tan(60) + 0.6*b*tan(pitch)` for half-span `b`.
- **gambrel**: same construction with the knuckle at 0.5 of the half-span and
  the lower slope at 55 degrees.

### 2. `metal_strength/model.py` — build from a Frame

New `roof(shape="duopitch", ...)` taking today's `pitched_roof` arguments plus
`shape`. It walks `Frame.segments`:

- a `column` segment becomes one member, unbraced over its full height for LTB
- a `rafter` segment subdivides at `purlin_spacing` measured along the slope,
  each sub-member's LTB length being the purlin spacing
- every node at `z == 0` is a support, pinned or fixed as today

Purlins, self-weight, gamma factors and the `Construction` return value are
untouched: they already work per station and per member tag.

`pitched_roof()` stays as a wrapper delegating to `roof(shape="duopitch", ...)`
so the MCP server, the design solver and the existing tests do not move.

### 3. `metal_strength/loads.py` — snow per shape

`SnowCase` gains `values: tuple[float, ...]`, one entry per rafter segment,
left to right. `.left` and `.right` remain as properties reading
`values[0]` and `values[-1]`, so the two-slope callers (CLI `snow` command, MCP
`snow_load_eurocode`, charts) keep working unchanged.

`roof_snow_load()` takes the `Frame` (or its pitches plus shape) and returns
the arrangements the Eurocode requires for that shape:

- `flat`, `monopitch`: mu1(alpha), one arrangement (EN 1991-1-3 5.3.2)
- `duopitch`: unchanged — balanced, plus two drift cases at half load on one
  slope (Fig 5.3)
- `mansard`, `gambrel`: mu1 evaluated per segment from that segment's own
  pitch, drift cases as duopitch. **EN 1991-1-3 gives no mansard rule.** This
  is an approximation and must be labelled as one — see Warnings below.
- `sawtooth`, `multispan`: EN 1991-1-3 5.3.4 valley accumulation. Undrifted
  case at mu1; drifted case with mu2 at each valley per Fig 5.4.

### 4. Warnings

Shapes whose snow coefficients are approximated (`mansard`, `gambrel`) print a
warning line in the CLI report, add it to the chart suptitle, and set a flag on
the MCP response. Wording goes in `i18n.MESSAGES` under `mu_approximate`,
translated to sk and cs like every other user-facing string.

### 5. Reach

- **CLI**: `--shape` on `roof` and `design`, choices from `shapes.SHAPES`.
- **MCP**: `check_roof` gains a `shape` field; new `list_shapes` tool returning
  the names with their one-line descriptions.
- **Dashboard**: a shape radio group beside the snow-state radio, re-solving on
  change. The solve cache key gains the shape.
- **i18n**: shape display names in a `SHAPES` dict alongside `SNOW_TERMS`,
  with `shape_term()` following the `snow_term()` pattern. Chart and slider
  labels use it; the identifiers stay English on the CLI.
- **Charts**: `viz.snow_cases()` generalises from the hard-coded two-slope
  outline to drawing the frame polyline with one load block per segment.

## Testing

`tests/test_shapes.py`:

1. Every shape in `SHAPES` builds, solves and checks without raising.
2. Geometry assertions per shape: apex height matches `eaves + span/2*tan`,
   duopitch and multispan are symmetric about mid-span, `sawtooth` and
   `multispan` produce the expected valley count and a column at each.
3. **Duopitch regression**: `roof(shape="duopitch", ...)` and today's
   `pitched_roof(...)` give identical node count, member count and worst
   utilisation, pinning the refactor as behaviour-neutral.
4. Snow: for `multispan`, the drifted valley case is strictly heavier at the
   valley than the balanced case; for `monopitch`, exactly one arrangement.
5. `SnowCase.left`/`.right` still agree with `values[0]`/`values[-1]` for the
   two-slope shapes, so the old callers are covered.

Existing suites must pass unchanged — that is the point of keeping
`pitched_roof()`.

### 6. GUI profile editor (in this cut)

The `--show` dashboard gets a shape radio group, and the profile itself becomes
editable with `matplotlib.widgets.PolygonSelector` — draggable vertices, no new
dependency, in the window that already exists.

- The deflected-shape panel doubles as the editor: the frame outline plus the
  two base points at `z == 0` closes the polygon naturally.
- Dragging a vertex snaps `x` to 0.25 m. Vertices are re-sorted by `x`, so
  dragging one past its neighbour reorders rather than failing.
- The solve happens when the selector reports the edit, which matplotlib does on
  mouse release, so a drag does not stutter.
- **Built without** the symmetry mirror this section first proposed: sorting
  already keeps every drag valid, and a mirror is another mode to explain. Add
  it if editing a symmetric roof turns out to be tedious in practice.
- The edited vertex list *is* a `Frame`, so nothing downstream changes.
- Editing switches the shape to `custom`. mu cannot be derived from an
  arbitrary polyline, so the shape radio stays live and nominates which
  Eurocode shape supplies mu; the result is stamped approximate through the
  same `mu_approximate` machinery.

**Validity guard** (not optional): a profile must be strictly monotonic in `x`
from left eaves to right eaves and free of self-intersections, because the
purlin and snow logic assumes stations march left to right. `shapes.validate()`
rejects anything else with a message, and the editor refuses the drag rather
than handing a broken frame to the solver.

## Follow-on

Loading and saving custom profiles (JSON), and a CLI flag to pass a profile
file, so an edited shape can be replayed without the GUI.
