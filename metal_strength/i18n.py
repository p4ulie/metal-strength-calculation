"""Report labels in English, Slovak and Czech.

What is translated: everything the reader is meant to read as prose -- column
headings, roles, verdicts, warnings.

What is not, deliberately:

* **Profile designations** (``IPE400``, ``HEB240``, ``SHS100x10``) are EN
  standard names. A Slovak or Czech merchant sells an IPE 400 as an IPE 400.
* **Steel grades** (``S235``) are EN 10025 designations, likewise.
* **Clause numbers** (``6.3.3 eq 6.62``) and **check names** are how an
  engineer cross-references the Eurocode; translating them would make the
  report harder to check, not easier.
"""

from __future__ import annotations

LANGUAGES = ("en", "sk", "cs")

# Component roles. The English key is the internal identifier used in code and
# in member tags; these are the display forms.
ROLES: dict[str, dict[str, str]] = {
    "rafter": {"en": "rafter", "sk": "krokva", "cs": "krokev"},
    "column": {"en": "column", "sk": "stĺp", "cs": "sloup"},
    "purlin": {"en": "purlin", "sk": "väznica", "cs": "vaznice"},
    "beam": {"en": "beam", "sk": "nosník", "cs": "nosník"},
    "brace": {"en": "brace", "sk": "stuženie", "cs": "ztužení"},
    "tie": {"en": "tie", "sk": "tiahlo", "cs": "táhlo"},
}

# Snow states and EN 1991-1-3 load arrangements. Keys are the identifiers used
# on the command line and in the code; these are display forms only.
SNOW_TERMS: dict[str, dict[str, str]] = {
    "fresh": {"en": "fresh", "sk": "čerstvý", "cs": "čerstvý"},
    "settled": {"en": "settled", "sk": "uľahnutý", "cs": "ulehlý"},
    "old": {"en": "old", "sk": "starý", "cs": "starý"},
    "wet": {"en": "wet", "sk": "mokrý", "cs": "mokrý"},
    "balanced": {"en": "balanced", "sk": "rovnomerné", "cs": "rovnoměrné"},
    "drift_left": {"en": "drift_left", "sk": "závej vľavo", "cs": "závěj vlevo"},
    "drift_right": {"en": "drift_right", "sk": "závej vpravo", "cs": "závěj vpravo"},
}

MESSAGES: dict[str, dict[str, str]] = {
    # -- material list columns
    "role": {"en": "role", "sk": "prvok", "cs": "prvek"},
    "profile": {"en": "profile", "sk": "profil", "cs": "profil"},
    "grade": {"en": "grade", "sk": "akosť", "cs": "jakost"},
    "qty": {"en": "qty", "sk": "ks", "cs": "ks"},
    "length_each": {"en": "length [m]", "sk": "dĺžka [m]", "cs": "délka [m]"},
    "total_length": {"en": "total [m]", "sk": "spolu [m]", "cs": "celkem [m]"},
    "mass_each": {"en": "mass [kg]", "sk": "hmotn. [kg]", "cs": "hmotn. [kg]"},
    "total_mass": {"en": "total [kg]", "sk": "spolu [kg]", "cs": "celkem [kg]"},
    "rate": {"en": "rate", "sk": "cena", "cs": "cena"},
    "cost": {"en": "cost", "sk": "náklady", "cs": "náklady"},
    "total": {"en": "total", "sk": "spolu", "cs": "celkem"},
    # -- money
    "subtotal": {"en": "material, ex VAT", "sk": "materiál bez DPH",
                 "cs": "materiál bez DPH"},
    "vat": {"en": "VAT", "sk": "DPH", "cs": "DPH"},
    "total_incl_vat": {"en": "total incl. VAT", "sk": "spolu s DPH",
                       "cs": "celkem s DPH"},
    "incl_waste": {"en": "includes off-cut allowance of",
                   "sk": "vrátane odpadu", "cs": "včetně odpadu"},
    "price_warning": {
        "en": "INDICATIVE PRICES - published list rates, not a quote. "
              "Confirm with your supplier before ordering.",
        "sk": "ORIENTAČNÉ CENY - zverejnené cenníky, nie ponuka. "
              "Pred objednaním overte u dodávateľa.",
        "cs": "ORIENTAČNÍ CENY - zveřejněné ceníky, nikoli nabídka. "
              "Před objednáním ověřte u dodavatele.",
    },
    "converted_rates": {
        "en": "rates published in {origin}, converted for {country} "
              "at the exchange rate above - a {country} supplier may quote differently",
        "sk": "ceny zverejnené v {origin}, prepočítané pre {country} kurzom vyššie - "
              "dodávateľ v {country} môže ponúknuť inú cenu",
        "cs": "ceny zveřejněné v {origin}, přepočtené pro {country} kurzem výše - "
              "dodavatel v {country} může nabídnout jinou cenu",
    },
    "rates_read": {"en": "rates read on", "sk": "ceny zistené dňa",
                   "cs": "ceny zjištěny dne"},
    "assumed_rates": {"en": "estimated, no published list found for",
                      "sk": "odhadnuté, bez zverejneného cenníka pre",
                      "cs": "odhadnuté, bez zveřejněného ceníku pro"},
    "material_only": {
        "en": "material only - no fabrication, coating, connections or erection",
        "sk": "iba materiál - bez výroby, náterov, spojov a montáže",
        "cs": "pouze materiál - bez výroby, nátěrů, spojů a montáže",
    },
    # -- verdict
    "passes": {"en": "PASSES", "sk": "VYHOVUJE", "cs": "VYHOVUJE"},
    "fails": {"en": "FAILS", "sk": "NEVYHOVUJE", "cs": "NEVYHOVUJE"},
    "utilisation": {"en": "utilisation", "sk": "využitie", "cs": "využití"},
    "governing": {"en": "governing check", "sk": "rozhodujúci posudok",
                  "cs": "rozhodující posudek"},
    "deflection": {"en": "deflection", "sk": "priehyb", "cs": "průhyb"},
    "members": {"en": "members", "sk": "prvkov", "cs": "prvků"},
    "worst_members": {"en": "worst members", "sk": "najviac zaťažené prvky",
                      "cs": "nejvíce zatížené prvky"},
    "material_list": {"en": "MATERIAL LIST", "sk": "VÝKAZ MATERIÁLU",
                      "cs": "VÝKAZ MATERIÁLU"},
    # -- chart labels
    "internal_actions": {"en": "internal actions", "sk": "vnútorné sily",
                         "cs": "vnitřní síly"},
    "along_member": {"en": "distance along member [m]",
                     "sk": "vzdialenosť po prvku [m]",
                     "cs": "vzdálenost po prvku [m]"},
    "max": {"en": "max", "sk": "max", "cs": "max"},
    "deflected_shape": {"en": "deflected shape", "sk": "deformovaný tvar",
                        "cs": "deformovaný tvar"},
    "peak": {"en": "peak", "sk": "max", "cs": "max"},
    "worst": {"en": "worst", "sk": "najhoršie", "cs": "nejhorší"},
    "in": {"en": "in", "sk": "v prvku", "cs": "v prvku"},
    "strength": {"en": "strength", "sk": "únosnosť", "cs": "únosnost"},
    "snow": {"en": "snow", "sk": "sneh", "cs": "sníh"},
    "snow_depth": {"en": "snow depth [m]", "sk": "výška snehu [m]",
                   "cs": "výška sněhu [m]"},
    "snow_state": {"en": "snow state", "sk": "stav snehu", "cs": "stav sněhu"},
    "roof_at": {"en": "m roof at", "sk": "m strecha so sklonom",
                "cs": "m střecha se sklonem"},
    "to_scale": {"en": "to scale", "sk": "v mierke", "cs": "v měřítku"},
    "snow_arrangements": {"en": "EN 1991-1-3 snow arrangements",
                          "sk": "Zaťaženie snehom podľa EN 1991-1-3",
                          "cs": "Zatížení sněhem podle EN 1991-1-3"},
    "pitch": {"en": "pitch", "sk": "sklon", "cs": "sklon"},
    # -- design solver
    "proposal": {"en": "PROPOSED CONSTRUCTION", "sk": "NAVRHNUTÁ KONŠTRUKCIA",
                 "cs": "NAVRŽENÁ KONSTRUKCE"},
    "searched": {"en": "sections tried", "sk": "skúšaných variantov",
                 "cs": "zkoušených variant"},
    "infeasible": {
        "en": "No combination in the catalogue carries this load. "
              "Reduce the span, add frames, or lower the load.",
        "sk": "Žiadna kombinácia z katalógu toto zaťaženie neunesie. "
              "Zmenšite rozpätie, pridajte rámy alebo znížte zaťaženie.",
        "cs": "Žádná kombinace z katalogu toto zatížení neunese. "
              "Zmenšete rozpětí, přidejte rámy nebo snižte zatížení.",
    },
    "best_reached": {"en": "best reached", "sk": "najlepšie dosiahnuté",
                     "cs": "nejlépe dosaženo"},
    "disclaimer": {
        "en": "Indicative Eurocode check. Not a substitute for a licensed "
              "structural engineer. Wind, connections and second-order effects "
              "are not covered.",
        "sk": "Orientačný posudok podľa Eurokódu. Nenahrádza autorizovaného "
              "statika. Vietor, spoje a teória II. rádu nie sú zahrnuté.",
        "cs": "Orientační posudek podle Eurokódu. Nenahrazuje autorizovaného "
              "statika. Vítr, spoje a teorie II. řádu nejsou zahrnuty.",
    },
}


def t(key: str, lang: str = "en") -> str:
    """Look up a label. Falls back to English, then to the key itself."""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    return entry.get(lang, entry.get("en", key))


def role(name: str, lang: str = "en") -> str:
    """Translate a component role. Anything unrecognised is passed through.

    Profile names arrive here when a member has no role tag (``IPE200`` for a
    plain beam), and those must not be touched.
    """
    entry = ROLES.get(name.lower())
    return entry.get(lang, entry["en"]) if entry else name


def translate_tag(tag: str, lang: str = "en") -> str:
    """Translate the role word at the front of a member tag.

    ``column R f1`` -> ``stĺp R f1``. The suffix is a position identifier and
    stays put so it still matches the model.
    """
    if not tag:
        return tag
    head, _, rest = tag.partition(" ")
    translated = role(head, lang)
    return f"{translated} {rest}".rstrip() if rest else translated


def snow_term(name: str, lang: str = "en") -> str:
    """Display form of a snow state or load arrangement; unknown names pass through."""
    return SNOW_TERMS.get(name, {}).get(lang, name)


def member_label(section: str, lang: str = "en") -> str:
    """Translate the role inside a member label: ``IPE300 [S235] rafter R f1``."""
    head, sep, rest = section.partition("] ")
    return f"{head}{sep}{translate_tag(rest, lang)}" if sep else section


def verdict(ok: bool, lang: str = "en") -> str:
    return t("passes" if ok else "fails", lang)
