"""Report labels in English, Slovak and Czech.

Only user-facing report text is translated. Eurocode clause numbers, profile
names and check names stay as they are -- they are the same in every language
and an engineer looking for "6.3.3 eq 6.62" wants exactly that string.
"""

from __future__ import annotations

LANGUAGES = ("en", "sk", "cs")

MESSAGES: dict[str, dict[str, str]] = {
    # -- material list columns
    "role": {"en": "role", "sk": "prvok", "cs": "prvek"},
    "profile": {"en": "profile", "sk": "profil", "cs": "profil"},
    "grade": {"en": "grade", "sk": "akost", "cs": "jakost"},
    "qty": {"en": "qty", "sk": "ks", "cs": "ks"},
    "length_each": {"en": "length [m]", "sk": "dlzka [m]", "cs": "delka [m]"},
    "total_length": {"en": "total [m]", "sk": "spolu [m]", "cs": "celkem [m]"},
    "mass_each": {"en": "mass [kg]", "sk": "hmotn [kg]", "cs": "hmotn [kg]"},
    "total_mass": {"en": "total [kg]", "sk": "spolu [kg]", "cs": "celkem [kg]"},
    "rate": {"en": "rate", "sk": "cena", "cs": "cena"},
    "cost": {"en": "cost", "sk": "naklady", "cs": "naklady"},
    "total": {"en": "total", "sk": "spolu", "cs": "celkem"},
    # -- money
    "subtotal": {"en": "material, ex VAT", "sk": "material bez DPH",
                 "cs": "material bez DPH"},
    "vat": {"en": "VAT", "sk": "DPH", "cs": "DPH"},
    "total_incl_vat": {"en": "total incl. VAT", "sk": "spolu s DPH",
                       "cs": "celkem s DPH"},
    "incl_waste": {"en": "includes off-cut allowance of",
                   "sk": "vratane odpadu", "cs": "vcetne odpadu"},
    "price_warning": {
        "en": "INDICATIVE PRICES - published list rates, not a quote. "
              "Confirm with your supplier before ordering.",
        "sk": "ORIENTACNE CENY - zverejnene cenniky, nie ponuka. "
              "Pred objednanim overte u dodavatela.",
        "cs": "ORIENTACNI CENY - zverejnene ceniky, nikoli nabidka. "
              "Pred objednanim overte u dodavatele.",
    },
    "converted_rates": {
        "en": "rates published in {origin}, converted for {country} "
              "at the exchange rate above - a {country} supplier may quote differently",
        "sk": "ceny zverejnene v {origin}, prepocitane pre {country} kurzom vyssie - "
              "dodavatel v {country} moze ponuknut inu cenu",
        "cs": "ceny zverejnene v {origin}, prepoctene pro {country} kurzem vyse - "
              "dodavatel v {country} muze nabidnout jinou cenu",
    },
    "rates_read": {"en": "rates read on", "sk": "ceny zistene dna",
                   "cs": "ceny zjisteny dne"},
    "assumed_rates": {"en": "estimated, no published list found for",
                      "sk": "odhadnute, bez zverejneneho cennika pre",
                      "cs": "odhadnute, bez zverejneneho ceniku pro"},
    # -- verdict
    "passes": {"en": "PASSES", "sk": "VYHOVUJE", "cs": "VYHOVUJE"},
    "fails": {"en": "FAILS", "sk": "NEVYHOVUJE", "cs": "NEVYHOVUJE"},
    "utilisation": {"en": "utilisation", "sk": "vyuzitie", "cs": "vyuziti"},
    "governing": {"en": "governing check", "sk": "rozhodujuci posudok",
                  "cs": "rozhodujici posudek"},
    "deflection": {"en": "deflection", "sk": "priehyb", "cs": "pruhyb"},
    "members": {"en": "members", "sk": "prvkov", "cs": "prvku"},
    "worst_members": {"en": "worst members", "sk": "najviac zatazene prvky",
                      "cs": "nejvice zatizene prvky"},
    "material_list": {"en": "MATERIAL LIST", "sk": "VYKAZ MATERIALU",
                      "cs": "VYKAZ MATERIALU"},
    # -- design solver
    "proposal": {"en": "PROPOSED CONSTRUCTION", "sk": "NAVRHNUTA KONSTRUKCIA",
                 "cs": "NAVRZENA KONSTRUKCE"},
    "searched": {"en": "sections tried", "sk": "skusenych variantov",
                 "cs": "zkousenych variant"},
    "infeasible": {
        "en": "No combination in the catalogue carries this load. "
              "Reduce the span, add frames, or lower the load.",
        "sk": "Ziadna kombinacia z katalogu toto zatazenie neunesie. "
              "Zmenste rozpatie, pridajte ramy alebo znizte zatazenie.",
        "cs": "Zadna kombinace z katalogu toto zatizeni neunese. "
              "Zmenste rozpeti, pridejte ramy nebo snizte zatizeni.",
    },
    "disclaimer": {
        "en": "Indicative Eurocode check. Not a substitute for a licensed "
              "structural engineer. Wind, connections and second-order effects "
              "are not covered.",
        "sk": "Orientacny posudok podla Eurokodu. Nenahradza autorizovaneho "
              "statika. Vietor, spoje a teoria II. radu nie su zahrnute.",
        "cs": "Orientacni posudek podle Eurokodu. Nenahrazuje autorizovaneho "
              "statika. Vitr, spoje a teorie II. radu nejsou zahrnuty.",
    },
}


def t(key: str, lang: str = "en") -> str:
    """Look up a label. Falls back to English, then to the key itself."""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    return entry.get(lang, entry.get("en", key))


def verdict(ok: bool, lang: str = "en") -> str:
    return t("passes" if ok else "fails", lang)
