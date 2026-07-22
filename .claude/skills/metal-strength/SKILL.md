---
name: metal-strength
description: Use when judging whether a metal member is strong enough - bending stress, deflection, buckling, or snow and roof loading - or when the user asks about Eurocode/EN steel design, section properties, safe spans, allowable loads, or how much snow a structure can carry.
---

# Metal strength: judging bending and safe values

Answer with numbers, and say which check governs. A member is "strong enough"
only when **every** applicable check passes, and the one that governs is rarely
the one people expect: on roofs it is usually deflection or lateral-torsional
buckling, not bending stress.

## Decide first: can this be done by hand?

| Situation | What to do |
|---|---|
| Single member, standard support case, load known | Hand check with the tables below. Fast and adequate. |
| Axially loaded strut or rod | Hand check: buckling section below. |
| Statically indeterminate frame, portal, or a whole roof | Use the package - internal forces cannot be hand-derived. |
| Class 4 (slender) section, or combined axial + bending near the limit | Use the package; and for class 4, neither is adequate - say so. |
| A number is going into something that gets built | Say plainly it needs a licensed engineer's check. |

To use the package (this repo):

```
uv run python -m metal_strength.cli beam --span 6 --section IPE200 --udl 5
uv run python -m metal_strength.cli roof --span 12 --length 20 --pitch 20 \
    --snow-depth 1.0 --snow-state wet
uv run python -m metal_strength.cli sections IPE300
```
Or the MCP server (`python -m metal_strength.mcp_server`): `check_beam`,
`check_rod_buckling`, `check_roof`, `snow_load_from_depth`, `section_properties`.

## The order to check things

1. **Bending** - `M_Ed / M_c,Rd`
2. **Shear** - and if `V_Ed > 0.5 V_pl,Rd`, bending capacity is reduced
3. **Lateral-torsional buckling** - unless the compression flange is held sideways
4. **Buckling** - if there is any compression
5. **Combined N+M** - if there is both
6. **Deflection** - serviceability, unfactored loads. Often governs roofs.

## Material

| Grade | f_y (t<=40mm) | f_y (40-80mm) | f_u |
|---|---|---|---|
| S235 | 235 | 215 | 360 |
| S275 | 275 | 255 | 430 |
| S355 | 355 | 335 | 490 |
| S420 | 420 | 390 | 520 |
| S460 | 460 | 430 | 540 |

MPa = N/mm². E = 210 000 MPa, G = 81 000 MPa, density 7850 kg/m³ (78.5 kN/m³).
`eps = sqrt(235/f_y)` - appears in every slenderness limit.

**Partial factors** (EN 1993-1-1 recommended): gamma_M0 = gamma_M1 = 1.0,
gamma_M2 = 1.25. **Actions** (EN 1990 eq. 6.10): 1.35 permanent + 1.5 variable
for strength; 1.0 + 1.0 for deflection.

## Beam formulas

`w` = load per unit length, `P` = point load, `L` = span, `EI` = 210000 x I.

| Case | M_max | V_max | delta_max |
|---|---|---|---|
| Cantilever, P at tip | `P L` | `P` | `P L³ / 3EI` |
| Cantilever, UDL | `w L² / 2` | `w L` | `w L⁴ / 8EI` |
| Simply supported, P at mid | `P L / 4` | `P / 2` | `P L³ / 48EI` |
| Simply supported, UDL | `w L² / 8` | `w L / 2` | `5 w L⁴ / 384EI` |
| Fixed both ends, UDL | `w L² / 12` (ends), `w L² / 24` (mid) | `w L / 2` | `w L⁴ / 384EI` |
| Propped cantilever, UDL | `w L² / 8` (fixed end) | `5 w L / 8` | `w L⁴ / 185EI` |

**Keep units straight.** Work in N and mm: kN/m = N/mm, kNm = 10⁶ Nmm,
cm⁴ = 10⁴ mm⁴, cm³ = 10³ mm³.

## The checks

**Bending.** `M_c,Rd = W f_y / gamma_M0`, with `W = W_pl` for class 1-2 and
`W_el` for class 3. Or as a stress: `sigma = M / W_el` against `f_y`.
Plastic modulus is roughly 1.12-1.15 x elastic for an I-section, so using
`W_el` is safe if you are unsure of the class.

**Shear.** `V_pl,Rd = A_v (f_y / sqrt(3)) / gamma_M0`. For a rolled I loaded
parallel to the web, `A_v ~= A - 2 b t_f + (t_w + 2r) t_f`, near enough the web
area. Shear rarely governs except on short heavily loaded spans.

**Deflection.** Against `span / limit`: **L/200** general roof,
**L/250** roof with a brittle finish or a floor. Check with *unfactored* loads.

**Buckling (compression).**
```
N_cr = pi² E I / L_cr²                     Euler
lambda_bar = sqrt(A f_y / N_cr) = (L_cr/i) / (93.9 eps)
Phi = 0.5 [1 + alpha (lambda_bar - 0.2) + lambda_bar²]
chi = 1 / (Phi + sqrt(Phi² - lambda_bar²))   <= 1.0
N_b,Rd = chi A f_y / gamma_M1
```
Ignore buckling when `lambda_bar <= 0.2`.

Effective length `L_cr = k L`: **k = 0.5** both ends fixed, **0.7** one fixed
one pinned, **1.0** both pinned (the safe default), **2.0** cantilever.

Imperfection factor by buckling curve:

| Curve | a0 | a | b | c | d |
|---|---|---|---|---|---|
| alpha | 0.13 | 0.21 | 0.34 | 0.49 | 0.76 |

Rolled I, t_f <= 40mm: **h/b > 1.2** -> curve a about y-y, b about z-z;
**h/b <= 1.2** -> b and c. Hot-finished hollow sections -> curve a.
Cold-formed hollow -> curve c. See `references/buckling-curves.md`.

Buckling almost always governs about the **weak axis** (z-z), because `i_z` is
several times smaller than `i_y`. Check both, take the lower.

**Lateral-torsional buckling.** A beam bent about its strong axis can buckle
sideways unless the compression flange is restrained. `M_b,Rd = chi_LT W_y f_y
/ gamma_M1`, with `chi_LT` from `lambda_bar_LT = sqrt(W_y f_y / M_cr)` and the
same curve shape (rolled sections: `lambda_LT,0 = 0.4`, `beta = 0.75`,
alpha_LT = 0.34 for h/b <= 2 else 0.49).

`M_cr` needs `I_z`, `I_T`, `I_w` and the **unrestrained length** - use the tool.
Rules of thumb: a deck or purlins fixed to the top flange remove LTB entirely;
an unrestrained IPE beam over ~15x its depth loses roughly half its capacity.
**If in doubt, assume unrestrained** - it is the conservative direction.

**Combined axial + bending.** EN 1993-1-1 eq. 6.61/6.62. For a quick screen:
`N_Ed/N_b,Rd + M_Ed/M_b,Rd <= 1` is roughly right and slightly unconservative.
Use the tool for anything near the limit.

## Snow

**`s = mu_1 x C_e x C_t x s_k`** (EN 1991-1-3), acting on the *horizontal
projection* of the roof.

Depth to load - the answer to "how much is a metre of snow":

| State | Density | 1 m depth |
|---|---|---|
| Fresh | 1.0 kN/m³ | **1.0 kN/m²** |
| Settled | 2.0 kN/m³ | **2.0 kN/m²** |
| Old | 3.5 kN/m³ | **3.5 kN/m²** |
| Wet | 4.0 kN/m³ | **4.0 kN/m²** |

A 4x spread - always ask which, or state the assumption. Wet snow is the
design case.

**mu_1** = 0.8 for pitch <= 30 deg; falls linearly to 0 between 30 and 60 deg;
0 above 60 deg. **But 0.8 for all pitches if snow guards stop it sliding.**

**C_e** = 0.8 windswept, 1.0 normal, 1.2 sheltered. **C_t** = 1.0 normally.

A duopitch roof needs **three** arrangements: balanced, and two drift cases
with one slope at half load. The unbalanced ones often govern the rafters.

For `s_k` from a zone map: `s_k = (0.264 Z - 0.002) [1 + (A/256)²]` for the
Central East region (Slovakia, Czechia, Poland, Hungary), A in metres.
**The national annex takes precedence** - use its value if the user has it.

## Sections without a catalogue

| Shape | A | I | W_el | W_pl |
|---|---|---|---|---|
| Rectangle b x h | `b h` | `b h³/12` | `b h²/6` | `b h²/4` |
| Round, dia d | `pi d²/4` | `pi d⁴/64` | `pi d³/32` | `d³/6` |
| Tube d, wall t | `pi t (d-t)` | `pi(d⁴-d_i⁴)/64` | `2I/d` | `(d³-d_i³)/6` |

Radius of gyration `i = sqrt(I/A)`; for a rectangle about its weak axis,
`i = b/sqrt(12) = 0.289 b`.

Common profiles are in `references/section-properties.md`; the full 567-profile
catalogue is `metal_strength/sections.py` (`get_section("IPE300")`).

## Where a hand check stops being enough

Say so rather than guessing:

- **Indeterminate structures** - portals, continuous beams, any 3D frame. The
  internal forces need the solver.
- **Class 4 sections** - local buckling reduces the effective cross-section
  (EN 1993-1-5). Neither this skill nor the package handles it.
- **Connections, base plates, welds and bolts** - EN 1993-1-8, not covered.
- **Second-order (P-delta) effects** - matter on slender sway frames.
- **Wind** - EN 1991-1-4. On a light metal roof wind *uplift* usually governs,
  not snow. "It holds the snow" is not "it is compliant".
- **Fatigue, fire, seismic** - separate Eurocode parts entirely.

Always close a real design question with: this is an indicative check, and
anything being built needs a licensed structural engineer.
