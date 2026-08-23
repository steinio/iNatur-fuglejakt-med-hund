"""Klassifisering av norsk vilkårstekst: hvilke fugler, og er hund tillatt?

Dette er hjertet i verktøyet. Vilkårene på inatur.no er fritekst skrevet av
hundrevis av ulike grunneiere og fjellstyrer, så formuleringene varierer mye:

    "Jakt med hund er tillatt fra 20.09"
    "Det er ikke tillatt å bruke hund"
    "Kun stående fuglehund"
    "Løs, halsende hund er forbudt i perioden"

Nøkkelen er negasjonshåndtering. "hund" + "tillatt" i samme setning betyr
ingenting hvis det står "ikke" foran "tillatt". Vi vurderer derfor hver setning
for seg, med et vindu rundt tillatelsesordet.

Vi returnerer alltid *begrunnelsen* (setningen som avgjorde) sammen med
konklusjonen, slik at brukeren kan overprøve oss.
"""

from __future__ import annotations

import re
import unicodedata

from .models import DogStatus, DogVerdict

# --------------------------------------------------------------------------
# Arter
# --------------------------------------------------------------------------

# De to viktigste. "rype"/"ryper" alene teller som prioritet - i praksis er et
# rypetilbud alltid li- og/eller fjellrype.
PRIORITY_SPECIES = {
    "lirype": r"\blirype\w*|\bli-?ryper?\b",
    "fjellrype": r"\bfjellrype\w*|\bfjell-?ryper?\b",
    "rype": r"\bryper?\b|\brypejakt\w*|\brypeterreng\w*",
}

OTHER_BIRDS = {
    "orrfugl": r"\borrfugl\w*|\borrhane\w*|\borrhøne\w*",
    "storfugl": r"\bstorfugl\w*|\btiur\w*|\brøy\b",
    "skogsfugl": r"\bskogsfugl\w*",
    "jerpe": r"\bjerpe\w*",
    "rugde": r"\brugde\w*",
    "bekkasin": r"\bbekkasin\w*|\benkeltbekkasin\w*",
    "due": r"\bringdue\w*|\bskogsdue\w*",
    "and": r"\bstokkand\w*|\bender\b|\bandejakt\w*",
    "gås": r"\bgrågås\w*|\bgjess\b|\bgåsejakt\w*",
    "kråkefugl": r"\bkråke\w*|\bskjære\w*|\bnøtteskrike\w*",
}

# Ikke fugl - brukes til å skille rene harejakt-/rovvilttilbud fra fugletilbud.
NON_BIRD_GAME = {
    "hare": r"\bhare\w*",
    "rev": r"\brev\b|\brevejakt\w*",
    "bever": r"\bbever\w*",
    "mår": r"\bmår\b|\bmårjakt\w*",
    "mink": r"\bmink\w*",
    "grevling": r"\bgrevling\w*",
    "ekorn": r"\bekorn\w*",
}

_PRIORITY_RE = {k: re.compile(v, re.I) for k, v in PRIORITY_SPECIES.items()}
_OTHER_RE = {k: re.compile(v, re.I) for k, v in OTHER_BIRDS.items()}
_NONBIRD_RE = {k: re.compile(v, re.I) for k, v in NON_BIRD_GAME.items()}


# --------------------------------------------------------------------------
# Hundetermer
# --------------------------------------------------------------------------

# Matcher hund, hunden, hunder, fuglehund, harehund, jakthund, hundejakt ...
# men IKKE "hundre"/"hundrevis" - derav negativ lookahead på "re".
DOG_TERM = re.compile(r"\w*hund(?!re)\w*", re.I)

# Hunderelaterte uttrykk som ikke inneholder ordet "hund".
DOG_CONTEXT = re.compile(
    r"\bløs\s+på\s+drevet\b|\bhalsende\b|\bbåndtvang\b|\bapport\w*", re.I
)

# Ord som uttrykker at noe er lov.
PERMIT = re.compile(
    r"\btillat\w*|\btillates\b|\blovlig\w*|\blov\s+(?:å|til)\b|\btilltatt\b"
    r"|\bpåbud\w*|\bkrav\b|\bkreves\b|\banbefal\w*|\båpne[nt]?\s+for\b"
    r"|\bkan\s+(?:brukes|benyttes|nyttes|medbringes)\b",
    re.I,
)

# Ord som uttrykker at noe ikke er lov.
FORBID = re.compile(r"\bforbud\w*|\bnekte\w*|\bfrabe\w*", re.I)

# Ren negasjon som snur et tillatelsesord.
NEGATION = re.compile(r"\bikke\b|\baldri\b|\bei\b|\buten\b|\bingen\b", re.I)

# Direkte negasjon av selve hundeordet: "uten hund", "ingen hunder".
NEG_BEFORE_DOG = re.compile(r"\b(?:uten|ingen)\b\W+(?:\w+\W+){0,2}?\w*hund(?!re)\w*", re.I)

# "fra 20.09", "fra og med 15.9", "etter 20.09.2026"
FROM_DATE = re.compile(
    r"\b(?:fra(?:\s+og\s+med)?|etter|f\.o\.m\.?)\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)",
    re.I,
)

# Innskrenkninger som gjør et "ja" betinget.
RESTRICTION = re.compile(
    r"\bkun\b|\bbare\b|\bmaks\w*|\bbegrense[tn]?\b|\bstående\s+fuglehund\b"
    r"|\bbåndtvang\b|\better\s+avtale\b|\bsøkna\w*|\bgodkjen\w*",
    re.I,
)

# Deler setninger, men IKKE på punktum mellom siffer (datoer som 20.09.2026).
SENTENCE_SPLIT = re.compile(r"(?<!\d)[.!?;:](?!\d)|\n+|\r+|•")

# Hvor mange tegn før et tillatelsesord vi leter etter negasjon.
# "er ikke tillatt" -> 4 tegn. "er dessverre ikke tillatt" -> 15.
NEGATION_WINDOW = 35


def normalize(text: str) -> str:
    """Slår sammen whitespace og normaliserer unicode-varianter."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ")
    # Ulike bindestreker/anførselstegn -> ASCII
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts = SENTENCE_SPLIT.split(normalize(text))
    return [p.strip() for p in parts if p and p.strip()]


# --------------------------------------------------------------------------
# Artsmatching
# --------------------------------------------------------------------------


def find_species(text: str) -> tuple[list[str], list[str]]:
    """Returnerer (alle fuglearter, prioriterte arter) funnet i teksten."""
    text = normalize(text)
    priority = [name for name, rx in _PRIORITY_RE.items() if rx.search(text)]

    # Hvis vi fant en spesifikk rype, er den generiske "rype"-treffen overflødig.
    if "rype" in priority and len(priority) > 1:
        priority.remove("rype")

    others = [name for name, rx in _OTHER_RE.items() if rx.search(text)]

    # "storfugl" impliserer skogsfugl - unngå dobbeltføring i visning.
    if "skogsfugl" in others and ("storfugl" in others or "orrfugl" in others):
        others.remove("skogsfugl")

    return sorted(set(priority + others)), sorted(set(priority))


def find_non_bird_game(text: str) -> list[str]:
    text = normalize(text)
    return sorted(name for name, rx in _NONBIRD_RE.items() if rx.search(text))


# --------------------------------------------------------------------------
# Hundeklassifisering
# --------------------------------------------------------------------------


def _sentence_polarity(sentence: str) -> str:
    """Vurderer én setning: 'pos', 'neg', 'mixed' eller 'mention'."""
    # Direkte negasjon av hundeordet: "uten hund", "ingen hunder"
    if NEG_BEFORE_DOG.search(sentence):
        return "neg"

    saw_pos = False
    saw_neg = False

    # Et forbudsord er negativt i seg selv - med mindre det selv er negert
    # ("ikke forbudt"), som vi da regner som positivt.
    for m in FORBID.finditer(sentence):
        window = sentence[max(0, m.start() - NEGATION_WINDOW) : m.start()]
        if NEGATION.search(window):
            saw_pos = True
        else:
            saw_neg = True

    # Et tillatelsesord er positivt - med mindre det er negert ("ikke tillatt").
    for m in PERMIT.finditer(sentence):
        window = sentence[max(0, m.start() - NEGATION_WINDOW) : m.start()]
        if NEGATION.search(window):
            saw_neg = True
        else:
            saw_pos = True

    if saw_pos and saw_neg:
        return "mixed"
    if saw_neg:
        return "neg"
    if saw_pos:
        return "pos"
    return "mention"


def classify_dog(text: str) -> DogVerdict:
    """Avgjør om et tilbud tillater hund, med begrunnelse.

    Vi er bevisst forsiktige: alt som ikke er et *klart* nei ender opp som noe
    brukeren får se. Å gå glipp av et lirypekort koster mer enn en falsk positiv.
    """
    text = normalize(text)
    if not text:
        return DogVerdict(DogStatus.NO_MENTION)

    dog_sentences = [
        s for s in split_sentences(text) if DOG_TERM.search(s) or DOG_CONTEXT.search(s)
    ]

    if not dog_sentences:
        return DogVerdict(DogStatus.NO_MENTION)

    pos_ev: list[str] = []
    neg_ev: list[str] = []
    mixed_ev: list[str] = []
    mention_ev: list[str] = []

    for sentence in dog_sentences:
        polarity = _sentence_polarity(sentence)
        {"pos": pos_ev, "neg": neg_ev, "mixed": mixed_ev, "mention": mention_ev}[
            polarity
        ].append(sentence)

    from_date = None
    restrictions: list[str] = []
    for sentence in pos_ev + mixed_ev + mention_ev:
        if from_date is None:
            m = FROM_DATE.search(sentence)
            if m:
                from_date = m.group(1)
        for m in RESTRICTION.finditer(sentence):
            token = m.group(0).lower()
            if token not in restrictions:
                restrictions.append(token)

    # Konklusjon
    if mixed_ev or (pos_ev and neg_ev):
        status = DogStatus.CONDITIONAL
        evidence = mixed_ev + pos_ev + neg_ev
    elif pos_ev:
        status = DogStatus.CONDITIONAL if (from_date or restrictions) else DogStatus.ALLOWED
        evidence = pos_ev
    elif neg_ev:
        status = DogStatus.NOT_ALLOWED
        evidence = neg_ev
    else:
        status = DogStatus.UNCLEAR
        evidence = mention_ev

    return DogVerdict(
        status=status,
        evidence=evidence[:3],
        from_date=from_date,
        restrictions=restrictions[:4],
    )
