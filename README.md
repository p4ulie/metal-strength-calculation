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

## What it does

| Layer | Module | Basis |
|---|---|---|
| Section properties | `sections.py` | 567 profiles (IPE, HEA, HEB, HEM, CHS, SHS, RHS), computed closed-form from tabulated geometry |
| Actions | `loads.py` | EN 1991-1-3 snow, EN 1990 combinations |
| Analysis | `frame3d.py` | 3D direct stiffness, 6 DOF/node, pure numpy |
| Design checks | `ec3.py` | EN 1993-1-1 §6.2, §6.3 |
| Geometry | `model.py` | pitched-roof generator, single beams |
| Output | `viz.py`, `viewer.py` | matplotlib charts, interactive pygame viewer |
| LLM access | `mcp_server.py` | MCP over stdio, 9 tools |

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
uv run python -m metal_strength.mcp_server        # stdio
uv run python tests/smoke_mcp.py                  # exercise every tool
```

Tools: `snow_load_from_depth`, `snow_load_eurocode`, `list_sections`,
`section_properties`, `check_beam`, `check_rod_buckling`, `check_roof`,
`solve_frame`, `render_snow_cases`.

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

`uv run pytest` — 106 tests, ~3 s.

- **FEM vs closed-form**: cantilever, simply supported, fixed-fixed, propped,
  pure torsion, pure axial, portal-frame equilibrium, pin-ended truss, and the
  same cantilever rotated into three global directions (0.1 % tolerance).
- **Sections vs catalogue**: A, I, W to 0.5 % for IPE/HEA/HEB/CHS/SHS/RHS.
- **Sections vs an independent algorithm**: `pytest -m slow` re-derives all 90
  I-profiles by mesh integration via `blue-prints` (~4 min).
- **EC3 vs hand calculation**: every expected number is derived in a comment
  above its assertion, e.g. IPE300 S235 at 6 m gives χ = 0.2279, N_b,Rd = 288 kN.
- **Skill vs code**: 17 tests parsing the markdown tables.
- **MCP over real stdio**: `tests/smoke_mcp.py`, 9/9 tools.

## Interactive viewer

```
uv pip install 'metal-strength[viewer]'
uv run python -m metal_strength.viewer --span 12 --length 20 --pitch 20
```

Drag to orbit, scroll to zoom, arrow keys change the snow depth and the model
re-solves live.

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
