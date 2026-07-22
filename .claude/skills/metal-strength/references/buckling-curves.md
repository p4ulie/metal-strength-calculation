# Buckling curve selection and chi values

## Choosing the curve (EN 1993-1-1 Table 6.2)

| Section | Limits | Buckling about y-y | about z-z |
|---|---|---|---|
| Rolled I / H | h/b > 1.2, t_f <= 40 mm | a | b |
| Rolled I / H | h/b > 1.2, 40 < t_f <= 100 | b | c |
| Rolled I / H | h/b <= 1.2, t_f <= 100 | b | c |
| Rolled I / H | h/b <= 1.2, t_f > 100 | d | d |
| Hollow, hot finished | any | a | a |
| Hollow, cold formed | any | c | c |
| Welded box | generally | b | b |
| Solid bar, angle, tee | any | c | c |

For **S460 and above**, every rolled and hot-finished case moves up to curve
a0. Practical shorthand: IPE (h/b ~ 2) is **a / b**; HEB up to 300
(h/b ~ 1) is **b / c**; hot-finished SHS/CHS is **a**.

Imperfection factor:

| Curve | a0 | a | b | c | d |
|---|---|---|---|---|---|
| alpha | 0.13 | 0.21 | 0.34 | 0.49 | 0.76 |

## chi against relative slenderness

```
Phi = 0.5 [1 + alpha (lambda_bar - 0.2) + lambda_bar^2]
chi = 1 / (Phi + sqrt(Phi^2 - lambda_bar^2))     capped at 1.0
```

| lambda_bar | a0 | a | b | c | d |
|---|---|---|---|---|---|
| 0.2 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 0.4 | 0.970 | 0.953 | 0.926 | 0.897 | 0.850 |
| 0.6 | 0.928 | 0.890 | 0.837 | 0.785 | 0.710 |
| 0.8 | 0.853 | 0.796 | 0.724 | 0.662 | 0.580 |
| 1.0 | 0.725 | 0.666 | 0.597 | 0.540 | 0.467 |
| 1.2 | 0.573 | 0.530 | 0.478 | 0.434 | 0.376 |
| 1.4 | 0.446 | 0.418 | 0.382 | 0.349 | 0.306 |
| 1.6 | 0.352 | 0.333 | 0.308 | 0.284 | 0.251 |
| 1.8 | 0.283 | 0.270 | 0.252 | 0.235 | 0.209 |
| 2.0 | 0.232 | 0.223 | 0.209 | 0.196 | 0.177 |
| 2.5 | 0.151 | 0.147 | 0.140 | 0.132 | 0.121 |
| 3.0 | 0.106 | 0.104 | 0.099 | 0.095 | 0.088 |

`lambda_bar = (L_cr / i) / (93.9 eps)`, with eps = sqrt(235/f_y):

| Grade | S235 | S275 | S355 | S420 | S460 |
|---|---|---|---|---|---|
| eps | 1.00 | 0.92 | 0.81 | 0.75 | 0.71 |
| 93.9 eps | 93.9 | 86.8 | 76.4 | 70.2 | 67.1 |

**Higher grade helps less than you would think in buckling.** Going S235 to
S355 raises the squash load by 51%, but also raises the slenderness by 23%,
which pushes chi down. On a slender strut the net gain can be near zero -- a
bigger section beats a stronger steel.

## Cross-section classification limits (Table 5.2)

Multiply every limit by `eps`. `c` is the flat width, excluding root radii.

| Part | Class 1 | Class 2 | Class 3 |
|---|---|---|---|
| Outstand flange, compression | 9 | 10 | 14 |
| Internal part, compression | 33 | 38 | 42 |
| Internal part (web), bending | 72 | 83 | 124 |
| Tubular, d/t (multiply by eps^2) | 50 | 70 | 90 |

Webs under combined bending and compression use `396 eps/(13a-1)` (class 1)
and `456 eps/(13a-1)` (class 2), where `a` is the compressed proportion of the
web -- the package computes this.

**Class 1 and 2** develop the full plastic moment (`Wpl`); **class 3** only the
elastic (`Wel`); **class 4** buckles locally first and needs an effective
cross-section per EN 1993-1-5, which is out of scope here. Hot-rolled IPE,
HEA, HEB in S235-S355 are class 1 or 2 in bending -- class 4 shows up in
fabricated plate girders and thin cold-formed sections.

## Lateral-torsional buckling, rolled sections (6.3.2.3)

```
lambda_bar_LT = sqrt(W_y f_y / M_cr)
Phi_LT = 0.5 [1 + alpha_LT (lambda_bar_LT - 0.4) + 0.75 lambda_bar_LT^2]
chi_LT = 1 / (Phi_LT + sqrt(Phi_LT^2 - 0.75 lambda_bar_LT^2))
         capped at min(1.0, 1/lambda_bar_LT^2)
```
`alpha_LT` = 0.34 for h/b <= 2, else 0.49. No reduction while
`lambda_bar_LT <= 0.4`.

```
M_cr = C1 (pi^2 E Iz / L^2) sqrt( Iw/Iz + L^2 G It / (pi^2 E Iz) )
```
`L` is the distance between lateral restraints to the compression flange, not
the span. `C1` accounts for the moment shape: **1.00** uniform moment (worst),
**1.13** UDL on a simple span, **1.35** central point load, and
`1.88 - 1.40 psi + 0.52 psi^2` (max 2.7) for a linear moment with end ratio psi.

Closed sections (CHS, SHS, RHS) have such high torsional stiffness that LTB
never governs -- `chi_LT = 1.0`.
