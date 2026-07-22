# metal-strength

Eurocode steel strength calculator — from a single bending rod to a whole 3D
roof under a metre of snow.

```
uv sync
uv run python -m metal_strength.cli roof --span 12 --length 20 --pitch 20 \
    --snow-depth 1.0 --snow-state wet --rafter IPE450 --column HEB240 \
    --purlin SHS140x140x5 --out out
```

```
=> the structure PASSES (strength 0.90, deflection 0.51)
```

Add `--show` to open the charts in interactive windows (zoom, pan, save) as
well as writing the PNGs:

```
uv run python -m metal_strength.cli beam --span 6 --section IPE200 --udl 5 --show
```

## What it does

| Layer | Module | Basis |
|---|---|---|
| Section properties | `sections.py` | 567 profiles (IPE, HEA, HEB, HEM, CHS, SHS, RHS), computed closed-form from tabulated geometry |
| Actions | `loads.py` | EN 1991-1-3 snow, EN 1990 combinations |
| Analysis | `frame3d.py` | 3D direct stiffness, 6 DOF/node, pure numpy |
| Design checks | `ec3.py` | EN 1993-1-1 §6.2, §6.3 |
| Geometry | `shapes.py`, `model.py` | roof profiles, frame generator, single beams |
| Design | `design.py` | proposes sections that carry a given load |
| Costing | `bom.py` | material list, indicative prices, VAT |
| Language | `i18n.py` | report labels in en / sk / cs |
| Output | `viz.py` | charts as PNGs, one window, or a live dashboard |
| LLM access | `mcp_server.py` | MCP over stdio, 12 tools |

There is a `./ms` wrapper in the repo carrying the parameters worth not
retyping (`./ms`, `./ms design --cost`, `./ms serve --http --show`). Anything
you pass overrides its defaults.

## Roof shapes

`--shape` picks the profile; the frame, the purlins, the columns under every
valley and the EN 1991-1-3 snow arrangements all follow from it.

| shape | snow arrangements |
|---|---|
| `flat` | balanced |
| `monopitch` | balanced |
| `duopitch` (default) | balanced, drift left, drift right |
| `mansard` | balanced, drift left, drift right — mu approximate |
| `gambrel` | balanced, drift left, drift right — mu approximate |
| `sawtooth` | balanced, valley drift |
| `multispan` | balanced, valley drift |

```
uv run python -m metal_strength.cli roof --span 30 --length 20 --pitch 15 \
    --shape multispan --case valley_drift --snow-depth 1.0 --snow-state wet
```

`--pitch` always means the *upper* slope, so a mansard's steep lower slope and a
sawtooth's return face are set by the shape, not by you. Snow slides off both of
them: above 60 degrees mu is zero (EN 1991-1-3 Table 5.2), which the model
applies per slope.

Repeating shapes read `--span` as the total width and divide it into bays as
near 10 m as they can, each bay getting a column at its valley.

**Not supported**: hipped, pyramidal, conical and domed roofs. Those are not a
constant profile extruded along the length — the frames stop being identical —
so they would need a different generator, not another entry in this table.

The Eurocode gives no shape coefficient for a mansard, a gambrel or a
hand-drawn profile. Those get mu from each slope's own pitch and every report,
chart and MCP response says so. Have the arrangement confirmed before building
anything off it.

## Drawing your own profile

In the live dashboard (`--show`), tick **edit profile** and drag the corners:
the frame rebuilds as a `custom` shape and re-solves on release. Vertices snap
to 0.25 m, and a profile that cannot be a roof — doubling back, two corners on
the same vertical, anything on the ground — is refused with the reason, leaving
the previous one in place.

Which snow arrangement applies is still your call: the shape radio stays live
and nominates the standard shape mu comes from, and the answer is stamped
approximate.

## Design it for me

Instead of checking a construction you drew, let it propose one:

```
uv run python -m metal_strength.cli design --span 12 --length 20 --pitch 20 \
    --snow-depth 1.0 --snow-state wet --cost --waste 5 --lang sk --country SK
```

```
NAVRHNUTÁ KONŠTRUKCIA   VYHOVUJE
  krokva    IPE400    66.3 kg/m
  stĺp      HEB240    83.2 kg/m
  väznica   SHS100x10 27.4 kg/m
  využitie  0.96   priehyb 0.62   spolu 11,665 kg
```

The solver starts from the smallest profile in each family and raises whichever
role is actually governing, then shrinks back anything it overshot. Typically
~50 solves, a few seconds. `--target 0.85` leaves headroom; `--objective cost`
optimises money rather than mass; `--rafter-family HEB` constrains the search.
If nothing in the catalogue carries the load it says so rather than proposing
something undersized.

## Material list and cost

`--bom` prints the material list, `--cost` prices it:

```
prvok      profil      akosť  ks  dĺžka [m]  spolu [kg]  cena [CZK/kg]  náklady [CZK]
väznica    SHS100x10   S235   36      5.000      4935.2          22.90        118,666
krokva     IPE400      S235   40      1.597      4235.5          30.00        133,418
stĺp       HEB240      S235   10      3.000      2496.0          31.00         81,244
materiál bez DPH   13,766.45 EUR  (333,328 CZK)
DPH 23% (SK)        3,166.28 EUR
```

Component roles are translated (rafter → krokva → krokev). **Profile
designations and steel grades are not** — `IPE400`, `HEB240`, `S235` are EN
standard names, and a Slovak merchant sells an IPE 400 as an IPE 400. Eurocode
clause numbers and check names stay in English too, so the report remains
cross-referenceable against the standard.

`--lang en|sk|cs` translates the report, `--country SK|CZ` sets the VAT rate
(23% / 21%) and the display currency, `--waste 5` adds an off-cut allowance,
`--fx` overrides the exchange rate.

**The mass is exact. The money is not.** See
[Prices — read this](#prices--read-this) before using a total for anything.

## Command line

Four subcommands. `--out DIR` writes charts, `--show` opens them in windows
(both work together; `--show` alone uses a temp directory).

```
metal-strength snow     --depth 1.0 --state wet --pitch 20
metal-strength snow     --zone 2 --altitude 400 --region central_east --pitch 20
metal-strength beam     --span 6 --section IPE200 --udl 5 [--point 20]
                        [--fixity simple|cantilever|fixed|propped] [--restrained]
metal-strength roof     --span 12 --length 20 --pitch 20 --snow-depth 1.0
                        [--shape duopitch|monopitch|flat|mansard|gambrel|
                                 sawtooth|multispan]
                        [--snow-state wet] [--snow 3.2] [--case drift_left]
                        [--rafter IPE450] [--column HEB240] [--purlin SHS140x140x5]
                        [--frame-spacing 5] [--purlin-spacing 1.5] [--eaves-height 3]
                        [--grade S355]
metal-strength design   --span 12 --length 20 --pitch 20 --snow-depth 1.0
                        [--shape multispan] [--target 0.85] [--objective mass|cost]
                        [--rafter-family IPE] [--column-family HEB]
metal-strength sections IPE300
metal-strength sections --family HEB
```

`beam`, `roof` and `design` all accept `--bom`, `--cost`, `--prices FILE`,
`--lang en|sk|cs`, `--country SK|CZ`, `--waste PERCENT` and `--fx RATE`.

`--restrained` on a beam means a deck or purlins hold the compression flange
sideways, so lateral-torsional buckling cannot occur. Leaving it off is the
conservative assumption and often halves the capacity — it is usually the check
that governs an unrestrained beam.

## How much is a metre of snow?

Between **1.0 and 4.0 kN/m²** — a 4× spread — depending on its state
(EN 1991-1-3 Annex E):

| State | Density | 1 m depth |
|---|---|---|
| Fresh | 1.0 kN/m³ | 1.0 kN/m² |
| Settled | 2.0 kN/m³ | 2.0 kN/m² |
| Old | 3.5 kN/m³ | 3.5 kN/m² |
| Wet | 4.0 kN/m³ | 4.0 kN/m² |

```
uv run python -m metal_strength.cli snow --depth 1.0 --state wet --pitch 20
```

## Why bigger rafters can turn the columns green

Counter-intuitive, and correct. In a pinned-base portal frame the column's
moment comes from the frame's horizontal thrust, `M = H · h`, and the thrust
falls as the rafter gets stiffer — the frame spreads less, so it pushes the
column tops outward less. Kleinlogel's closed form for a rectangular portal
under a UDL says the same thing without any help from this solver:

```
H = w L² / (4 h (2k + 3)),   k = (I_rafter / L) / (I_column / h)
```

Bigger `I_rafter` → bigger `k` → smaller `H`. Swapping IPE300 for IPE600 on a
12 m frame takes the eaves moment from 142 to 98 kNm, so the column utilisation
drops even though the roof got heavier.

The weight does arrive, though: over that same swap the column's axial load
rises 106 → 115 kN. To see weight alone, change the **purlins** — they add mass
without stiffening the portal, and column utilisation then rises monotonically
(0.59 → 0.66 across SHS100 to SHS250).

Both are pinned by tests: the thrust against the closed form to 0.2%, and the
purlin case as a monotonic check.

## Checks performed

Cross-section classification (1–4) · tension · compression · shear with
moment interaction · bending (plastic or elastic per class) · St Venant
torsion · flexural buckling both axes · lateral-torsional buckling ·
combined N+M (eq. 6.61/6.62, Annex B) · deflection.

Every result carries its utilisation, the governing formula and the clause:

```
FAIL combined N+M (6.62)     2.01  2.01/1 -     [6.3.3 eq 6.62]  kzy=0.99
FAIL lateral-torsional       1.82  268/147 kNm  [6.3.2]  chi_LT=0.995, L=1596mm
OK   shear z (web)           0.39  137/348 kN   [6.2.6]
```

## MCP server

```
uv run python -m metal_strength.cli roof --span 12 --length 20 --show   # window + MCP on :8000
uv run python -m metal_strength.cli serve                               # stdio, no window
uv run python -m metal_strength.mcp_server                              # same, for MCP client configs
uv run python tests/smoke_mcp.py                  # exercise every tool
```

Tools: `snow_load_from_depth`, `snow_load_eurocode`, `list_sections`,
`list_shapes`, `section_properties`, `check_beam`, `check_rod_buckling`,
`check_roof`, `tune_roof`, `roof_report`, `solve_frame`, `propose_construction`,
`material_list`, `render_snow_cases`.

### One process, not two

There is one application, `metal-strength`, and **any window it opens serves
MCP**. `--show` starts the dashboard and the HTTP server together on port 8000
(next free port if that one is busy — the URL is printed), so the sliders and
`tune_roof` drive **the same roof**: a tool call moves the handles, and moving a
handle is what the next tool call reports. `--port` moves it, `--no-mcp` opens
the window without serving it.

`serve` is the other case only: stdio, no window, for an MCP client that
launches this process itself.

**Reaching it from another machine.** `--host 0.0.0.0` binds every interface,
`--host 10.0.0.5` one of them. Loopback is the default for a reason: there is
**no authentication**, so anyone who can reach the port can drive the model and
read the reports it writes. A non-loopback bind also switches off MCP's
DNS-rebinding guard — without that it answers `421 Misdirected Request` to any
`Host` header that is not localhost — and prints a warning saying so. Prefer one
trusted interface, or a VPN or SSH tunnel, over `0.0.0.0`.

That works because there is one parameter dict, not two kept in step: the
window reads and writes the MCP server's session directly, so no redraw can
read a stale value off an untouched widget and silently revert a tool's change.
Values with no widget (span, length, eaves height) are session-only; the window
just shows the result.

It has to be one process. matplotlib's GUI can only be touched from the thread
running its event loop, so the main thread keeps the window, the server runs
beside it on a daemon thread, and a tool call posts its change through a queue
and waits for the main thread to apply it. Two processes cannot do this at all:
a separate `./ms --show` and a separate server hold two unrelated roofs in two
memories, and no tool call will ever move that window.

### Tuning a roof remotely

`tune_roof` holds a roof between calls, so you state only what changes and get
the verdict plus the four-panel chart back inline:

```
tune_roof(shape="multispan", span_m=30)   -> 0.78, 27,867 kg, chart
tune_roof(rafter="IPE500")                -> 0.78, 28,553 kg, chart
tune_roof(snow_depth_m=1.5)               -> ...
tune_roof(reset=True)                     -> back to the defaults
```

Everything omitted keeps its value, `changed` in the reply says what actually
moved, and `snow_cases_available` tells you which arrangements the current
shape allows. Naming a depth after a direct `snow_kn_m2` switches back to the
depth. One session per process — right for one person driving it, not for two.

### A report to send

`--pdf FILE` on `beam`, `roof` or `design` writes a four-page report; over MCP
the same thing is `roof_report`, which returns the PDF **inline** as a resource
blob rather than a path, so a client on another machine gets the bytes:

| page | contents |
|---|---|
| 1 | verdict, parameters, the twelve worst members, deflection, disclaimer |
| 2 | the four charts — 3D utilisation, ranking, deflected shape, force diagrams |
| 3 | the EN 1991-1-3 snow arrangements for that shape |
| 4 | material list with indicative prices (omitted if you did not ask for costs) |

Charts are vector, so it prints sharp. `--lang` / `language=` translates the
prose. Written by matplotlib's own PDF backend — no extra dependency.

### Shapes in words

`shape=` covers the seven presets. Anything else — an arch, an asymmetric roof,
a stepped clerestory — is drawn point by point with `profile_points`, the frame
outline as `[[x, z], ...]` in metres from the left eaves to the right, columns
added under the ends and every valley automatically:

```
tune_roof(profile_points=[[0,3],[2,4.0],[4,4.7],[6,5.0],[8,4.7],[10,4.0],[12,3]])
  -> shape "custom", mu_approximate true
```

Every reply returns `profile_points` for the shape in force — **presets
included** — plus `slope_pitches_deg`. That is what makes an instruction like
"bend that arch more" or "raise the ridge half a metre" work: read the outline
back, modify it, send it again. Naming a `shape` discards the drawing.

Refusals carry the reason (x must strictly increase, nothing below ground) and
leave the previous roof standing.

`propose_construction` is the design solver; `material_list` returns the BOM
with an indicative cost and a `price_note` that must be repeated to the user.

Register it with Claude Code:

```json
{ "mcpServers": { "metal-strength": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/strength-calculation",
             "python", "-m", "metal_strength.mcp_server"] } } }
```

## Claude Code skill

`.claude/skills/metal-strength/` lets Claude judge bending and safe values in
conversation without running anything: steel grades, closed-form beam
formulas, the χ buckling tables, snow densities, and — importantly — where a
hand check stops being adequate. `tests/test_skill_consistency.py` parses every
number back out of the markdown and checks it against the code, so the skill
cannot silently drift from the engine.

## Validation

`uv run pytest` — 149 tests, ~75 s (`pytest -m slow` adds 6 more, ~5 min). Nothing is checked against itself; every
layer is validated against something derived independently of it.

| Suite | n | Checked against |
|---|---|---|
| `test_frame3d.py` | 13 | Closed-form solutions to 0.1 %: cantilever (point and UDL), simply supported, fixed-fixed, propped, pure torsion `TL/GJ`, pure axial, portal-frame equilibrium, pin-ended truss, mechanism detection, and the same cantilever rotated into three global directions — which is what catches a wrong direction-cosine matrix. |
| `test_sections.py` | 14 | Published catalogue values to 0.5 % across IPE/HEA/HEB/CHS/SHS/RHS. `pytest -m slow` adds an independent re-derivation of all 90 I-profiles by mesh integration via `blue-prints` (~4 min). |
| `test_ec3.py` | 12 | Hand calculations, each derived in a comment above its assertion — e.g. IPE300 S235 at 6 m gives λ̄ = 1.907, χ = 0.2279, N_b,Rd = 288 kN. |
| `test_loads.py` | 23 | EN 1991-1-3 by hand: snow densities, μ₁ at every pitch break, snow guards, exposure, the Annex C altitude term, EN 1990 combinations. |
| `test_model.py` | 14 | Roof geometry (apex height, frame count, purlin-restrained LTB lengths), unit conversion at the metres/kN boundary, and monotonicity — more snow and smaller sections must raise utilisation. |
| `test_skill_consistency.py` | 17 | The skill's markdown parsed back out and compared to the code: grades, partial factors, χ tables, snow densities, classification limits, and every closed-form beam formula re-derived by the FEM engine. |
| `test_mcp_server.py` | 13 | Every tool registers with a description, round-trips its pydantic model, and gives the right answer — including that an undersized roof actually fails. |
| `test_viz.py` | 11 | Both chart modes, and that a backend switch cannot leak into later tests. |
| `test_bom_design.py` | 27 | The solver's own verdict re-checked independently; more load and longer spans must need more steel; an impossible load must be refused, not under-designed. Material-list mass reconciled against the model, VAT arithmetic, and that estimated price rates are declared as estimates. |

Plus `tests/smoke_mcp.py` — drives the server over a real stdio transport and
calls all 11 tools.

Two of the bugs these caught were in the documentation, not the code: the χ
table written by hand was wrong in four of five columns, and one recalled
catalogue `Iz` was 3 % off. Both surfaced only because the tables are compared
against the implementation.

## Charts and the live dashboard

`--out DIR` writes PNGs (utilisation in 3D, ranking, deflected shape, force
diagrams). `--show` opens one window instead. Both work on `beam`, `roof` and
`design`, and can be combined:

```
uv run python -m metal_strength.cli roof --span 12 --length 20 --pitch 20 \
    --snow-depth 1.0 --snow-state wet --out out --show
```

On `roof`, `--show` gets sliders: drag them and the frame re-solves live; drag
the 3D panel to orbit. Close the window to exit.

Chart text follows `--lang` (titles, axes, verdict, member roles). Profile
names, steel grades and Eurocode clause references stay in EN form, as
everywhere else.

Charts render headless by default (matplotlib `Agg`). `--show` picks the first
GUI backend that imports; if none does it says so and falls back to writing
files, so install one — `uv pip install pyqt6`.

## Seeing every member

The ranking chart lists the 12 worst by default. `--top N` changes that and
`--top 0` shows **all** of them — 86 for a modest roof, 227 for a multi-span:

```
./ms --top 0 --out out
```

The labelling adapts to the room it has rather than to the member count: on a
tall standalone PNG every name is printed at 7 pt, in the dashboard's small
panel they thin to every fifth and shrink to 4.5 pt, and if even that would
collide the axis becomes a position (1 … n) — every bar is still drawn, so the
distribution reads either way. The title carries the count and how many fail.

To identify a specific member, the 3D panel is the better tool; the ranking is
for seeing the spread.

## Speed

One dashboard interaction — move a slider, switch a shape, drag a vertex —
costs about 265 ms: ~15 ms to re-solve, the rest to redraw. It used to be near
a second. Two things did it, neither of them a GPU:

- **BLAS threads.** Stiffness matrices here are a few hundred DOF. OpenBLAS
  spawns a thread per core for them by default and spends all its time
  synchronising: a 330x330 solve measured **0.9 ms on one thread and 23-300 ms
  on sixteen**. `metal_strength/__init__.py` pins the thread count to 1 before
  numpy loads. Export `OPENBLAS_NUM_THREADS` yourself to override — worth doing
  only if you ever solve a genuinely large frame. This also took the test suite
  from 145 s to 30 s.
- **One artist per member.** The 3D and deflection panels drew a separate line
  for every member — a few hundred artists to build and render each frame. They
  are now single `LineCollection`s, and text hinting is off in GUI windows only.

**Not OpenGL.** Matplotlib has no GPU backend, so a GPU path means replacing it
with pyqtgraph or VisPy: a new dependency, a rewrite of every chart, and the
loss of the same code producing the report PNGs — all to hardware-accelerate a
few hundred line segments that were never the bottleneck. If the remaining
~250 ms redraw ever needs to come down, the next step is blitting the one panel
that changed, not a new toolkit.

## Prices — read this

The shipped rates are a **dated snapshot of published Czech list prices**, not a
quote, and not scraped live. What they are:

| Family | CZK/kg | Basis |
|---|---|---|
| IPE | 30.0 | measured — 12 profiles IPE80–IPE330 spanned 29.4–31.0 |
| HEB | 31.0 | measured — 12 profiles HEB100–HEB320 spanned 28.8–31.6 |
| SHS / RHS | 22.9 | measured — hollow section (jekl), 1st quality, flat rate |
| HEA / HEM / CHS | 31.0 / 33.0 / 28.0 | **assumed** — no published list found |

Read 2026-07-22 from [mzhutni.cz IPE](https://www.mzhutni.cz/ipe-c80/),
[mzhutni.cz HEB](https://www.mzhutni.cz/heb-c84/) and
[levny-hutni-material.cz](https://www.levny-hutni-material.cz/cenik/ocelove-jekly/).
VAT rates from [vatcalc](https://www.vatcalc.com/slovakia/slovakia-2026-vat-update/).
EUR/CZK ≈ 24.22.

Consequences you should hold in mind:

- Rates marked **assumed** are estimates. The report names them every time.
- `--country SK` converts Czech list prices into euro. A Slovak supplier will
  quote differently. The report says so.
- Most SK/CZ steel merchants quote by phone, per order and per quantity. A real
  quote will not match a list price.
- Steel moves. A rate read in July is not a rate in December.

**Use your own numbers.** `--prices quote.json` takes a plain file:

```json
{ "currency": "EUR", "origin": "SK", "vat_rate": {"SK": 0.23},
  "eur_per_unit": 1.0,
  "per_kg": {"IPE": 1.50, "HEB": 1.60, "SHS": 1.20, "default": 1.50} }
```

Costs cover **material only** — no fabrication, coating, connections, transport
or erection, which on a real building often exceed the steel itself.

## Limitations — read before trusting a number

- **Not a substitute for a licensed structural engineer.** Indicative checks only.
- **Wind is not covered** (EN 1991-1-4). On a light metal roof wind *uplift*
  usually governs. This answers "does it hold the snow", not "is it compliant".
- **Class 4 sections** are detected and flagged, but effective widths
  (EN 1993-1-5) are not computed — resistances are reported as invalid.
- **Connections, base plates, welds and bolts** (EN 1993-1-8) are out of scope.
- **Second-order (P-Δ) effects** are not included; matters on slender sway frames.
- **`I_t` for I-sections** uses the El Darwish & Johnston approximation, ~2–6 %
  high against catalogue values. It feeds only `M_cr`, so treat an LTB
  utilisation within ~5 % of 1.0 as inconclusive.
- **Interaction factors** default to `Cm = 0.9`; refine from the real moment
  diagram for a final design.
- **National annexes govern.** The Annex C zone formula is a fallback for when
  you do not have the national annex to hand — Slovakia's STN EN 1991-1-3/NA1
  values take precedence, and can be passed directly with `--snow`.

Profile geometry is derived from [blue-prints](https://pypi.org/project/blue-prints/) (MIT).

## Licence

MIT
