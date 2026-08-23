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

# Ord som uttrykker at noe er lov. Dekker både bokmål og nynorsk:
# tillatt/tillate/tillete, lov/løyve, "rett til".
PERMIT = re.compile(
    r"\btillat\w*|\btillet\w*|\btilltatt\b|\blovlig\w*|\blov\b|\bløyve\w*"
    r"|\brett\s+til\b|\bhøve\s+til\b|\banledning\b|\badgang\b|\bhøve\b"
    r"|\bpåbud\w*|\bkrav\b|\bkreves\b|\banbefal\w*|\båpne[nt]?\s+for\b"
    r"|\bkan\s+(?:brukes|benyttes|nyttes|nytte|medbringes|ha\s+med)\b",
    re.I,
)

# Ord som uttrykker at noe ikke er lov.
FORBID = re.compile(r"\bforbud\w*|\bforbode\w*|\bnekte\w*|\bfrabe\w*", re.I)

# Ren negasjon som snur et tillatelsesord. Nynorsk: ikkje, inkje, utan.
NEGATION = re.compile(
    r"\bikke\b|\bikkje\b|\binkje\b|\baldri\b|\bei\b|\buten\b|\butan\b|\bingen\b", re.I
)

# Direkte negasjon av selve hundeordet: "uten hund", "utan hund", "ingen hunder".
NEG_BEFORE_DOG = re.compile(
    r"\b(?:uten|utan|ingen)\b\W+(?:\w+\W+){0,2}?\w*hund(?!re)\w*", re.I
)

# Negert modalverb rett på hunden: "hund må ikke brukes", "hund kan ikkje nyttast".
DOG_NEGATED_MODAL = re.compile(
    r"\w*hund\w*\W+(?:skal|må|kan|bør|får|kunne)\s+(?:ikke|ikkje|inkje|aldri)\b", re.I
)

# "med og uten hund" betyr at BEGGE varianter tilbys - altså er hund lov.
# Uten denne regelen slår "uten hund" inn og gir falskt negativ.
BOTH_VARIANTS = re.compile(
    r"\bmed\s+og\s+ut[ae]n\s+\w*hund|\but[ae]n\s+og\s+med\s+\w*hund"
    r"|\bmed\s*/\s*ut[ae]n\s+\w*hund|\bmed\s+ut[ae]n\s*/\s*med\s+\w*hund",
    re.I,
)

_MONTH = (
    r"jan(?:uar)?|feb(?:ruar)?|mars|april|mai|juni|juli|aug(?:ust)?"
    r"|sep(?:t|tember)?|okt(?:ober)?|nov(?:ember)?|des(?:ember)?"
)
_DATE = rf"\d{{1,2}}[./]\s*\d{{1,2}}(?:[./]\d{{2,4}})?|\d{{1,2}}\.?\s+(?:{_MONTH})"

# "fra 20.09", "fra og med 15.9", "etter 20.09.2026", "frå 1. oktober"
FROM_DATE = re.compile(
    rf"\b(?:fra(?:\s+og\s+med)?|frå(?:\s+og\s+med)?|etter|f\.o\.m\.?)\s+({_DATE})", re.I
)

# "ikke lov før 1. oktober" -> altså lov FRA 1. oktober.
BEFORE_DATE = re.compile(rf"\bfør\s+({_DATE})", re.I)

# Forbud som bare gjelder deler av området eller deler av sesongen.
# Da er det ikke et blankt nei, men et forbehold.
SCOPED_BAN = re.compile(
    r"\bsærskilte\s+område\w*|\bhundeforbudsområde\w*|\bvisse\s+område\w*"
    r"|\benkelte\s+område\w*|\bdeler\s+av\s+(?:område\w*|terreng\w*|felt\w*)"
    r"|\bi\s+perioden\b|\bmed\s+unntak\s+av\b|\bunnateke\b",
    re.I,
)

# Tittelen er ofte det tydeligste signalet: "Rypejakt med hund",
# "Treningskort for stående fuglehund", "Hundekort".
TITLE_POSITIVE = re.compile(
    r"\bmed\s+hund\b|\bfuglehund\w*|\bhundekort\w*|\btreningskort\w*"
    r"|\bhundetrening\w*|\bhundeprøve\w*",
    re.I,
)

# Innskrenkninger som gjør et "ja" betinget.
RESTRICTION = re.compile(
    r"\bkun\b|\bbare\b|\bmaks\w*|\bbegrense[tn]?\b|\bstående\s+fuglehund\b"
    r"|\bbåndtvang\b|\better\s+avtale\b|\bsøkna\w*|\bgodkjen\w*|\bforbeholdt\b"
    r"|\bsaueren\w*|\bsauerein\w*|\bbufesertifikat\w*|\bdokumenter\w*",
    re.I,
)

# Et krav *til* hunden forutsetter at hund i det hele tatt er lov:
# "Hund skal ha sauerenhetsbevis", "Jakthund må være sauerein",
# "Kortet benyttes til trening av fuglehund".
# Selve uttrykket «jakt med hund» beskriver et tilbud der hund inngår.
# Krever "jakt"-ordet foran - "utført med fuglehund" (om linjetaksering) skal
# ikke telle som en hunderegel.
DOG_HUNT_PHRASE = re.compile(r"\bjakt\w*\s+med\s+\w*hund(?!re)\w*", re.I)

# Modalverbet må ikke være negert - "hund må ikke brukes" er et nei, ikke et krav.
DOG_REQUIREMENT = re.compile(
    r"\w*hund\w*\W+(?:skal|må|bør)(?:\s+(?:ha|vere|være))?"
    r"(?!\s*(?:ikke|ikkje|inkje|aldri))\b"
    r"|\btrening\s+av\s+\w*hund|\b\w*hundtrening\w*|\btrening\s+med\s+\w*hund",
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
# Arter fra API-et
# --------------------------------------------------------------------------

# Den fullstendige verdilista fra `arter`-feltet i /internal/search, hentet ved
# å telle opp alle 948 ledige småvilttilbud. Dette er fasit - langt sikrere enn
# å lete etter artsnavn i fritekst.
API_PRIORITY = {"Lirype", "Fjellrype"}

API_BIRDS = {
    "Lirype",
    "Fjellrype",
    "Orrfugl",
    "Orrhane",
    "Orrhøne",
    "Tiur",
    "Røy",
    "Jerpe",
    "And",
    "Gjess",
    "Ringdue",
    "Vadefugler",
    "Spurvefugler",
    "Skarv",
}

# "Småvilt" og "Andre" er upresise samlekategorier. Småviltjakt omfatter i
# praksis nesten alltid rype, så vi regner dem som mulige fugletilbud i stedet
# for å filtrere dem bort.
API_AMBIGUOUS = {"Småvilt", "Andre"}

API_NON_BIRD = {
    "Hare",
    "Rødrev",
    "Mår",
    "Rådyr",
    "Røyskatt",
    "Grevling",
    "Villsvin",
    "Bever",
    "Gaupe",
    "Sel",
}


def species_from_api(arter: list[str] | None) -> tuple[list[str], list[str], list[str]]:
    """Deler `arter`-lista fra API-et i (fugler, prioriterte, annet vilt).

    Ukjente verdier - nettstedet kan innføre nye - regnes som mulige fugler,
    slik at et nytt artsnavn ikke stille filtrerer bort tilbud.
    """
    values = [a for a in (arter or []) if a]
    birds = [a for a in values if a in API_BIRDS]
    priority = [a for a in values if a in API_PRIORITY]
    other = [a for a in values if a in API_NON_BIRD]
    maybe = [a for a in values if a in API_AMBIGUOUS or a not in API_BIRDS | API_NON_BIRD]
    return sorted(set(birds + maybe)), sorted(set(priority)), sorted(set(other))


# --------------------------------------------------------------------------
# Hundeklassifisering
# --------------------------------------------------------------------------


def _sentence_polarity(sentence: str) -> str:
    """Vurderer én setning: 'pos', 'neg', 'mixed' eller 'mention'."""
    # "med og uten hund" tilbyr begge deler - sjekkes før negasjonsregelen,
    # ellers slår "uten hund" inn og gir falskt negativ.
    if BOTH_VARIANTS.search(sentence):
        return "pos"

    # Direkte negasjon av hundeordet: "uten hund", "utan hund", "ingen hunder",
    # eller negert modalverb: "hund må ikke brukes".
    if NEG_BEFORE_DOG.search(sentence) or DOG_NEGATED_MODAL.search(sentence):
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

    # Ingen eksplisitt tillatelse, men et krav til hunden forutsetter at hund
    # er lov: "Jakthund må dokumentert være sauerein".
    if DOG_REQUIREMENT.search(sentence):
        return "pos"

    # "Alle jaktkort tilbys som jakt med hund", "både som støkkjakt og jakt med
    # hund" - selve uttrykket «jakt med hund» beskriver et tilbud der hund
    # inngår. Krever at setningen ikke er negert i det hele tatt.
    if DOG_HUNT_PHRASE.search(sentence) and not NEGATION.search(sentence):
        return "pos"

    return "mention"


def classify_dog(text: str, title: str = "") -> DogVerdict:
    """Avgjør om et tilbud tillater hund, med begrunnelse.

    Vi er bevisst forsiktige: alt som ikke er et *klart* nei ender opp som noe
    brukeren får se. Å gå glipp av et lirypekort koster mer enn en falsk positiv.

    `title` brukes som et ekstra signal - et tilbud som heter "Rypejakt med
    hund" eller "Treningskort for stående fuglehund" blir aldri et blankt nei
    fordi én setning nevner et avgrenset forbudsområde.
    """
    text = normalize(text)
    title = normalize(title)
    if not text and not title:
        return DogVerdict(DogStatus.NO_MENTION)

    title_says_dog = bool(title) and bool(TITLE_POSITIVE.search(title))

    dog_sentences = [
        s for s in split_sentences(text) if DOG_TERM.search(s) or DOG_CONTEXT.search(s)
    ]

    if not dog_sentences:
        if title_says_dog:
            return DogVerdict(DogStatus.CONDITIONAL, evidence=[f"Tittel: {title}"])
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

    # "ikke lov å jakte med hund før 1. oktober" er et *ja fra 1. oktober*,
    # ikke et nei. Flytt slike setninger over til betinget-bøtta.
    from_date = None
    for sentence in list(neg_ev):
        m = BEFORE_DATE.search(sentence)
        if m:
            neg_ev.remove(sentence)
            mixed_ev.append(sentence)
            if from_date is None:
                from_date = m.group(1)

    # Et forbud som bare gjelder deler av området eller sesongen er et
    # forbehold, ikke et blankt nei.
    scoped = [s for s in neg_ev if SCOPED_BAN.search(s)]

    restrictions: list[str] = []
    for sentence in pos_ev + mixed_ev + mention_ev:
        if from_date is None:
            m = FROM_DATE.search(sentence)
            if m:
                from_date = m.group(1)
        # Et "ja" med et innbakt unntak ("tillatt, med unntak av særskilte
        # områder") er et betinget ja, ikke et blankt ja.
        for rx in (RESTRICTION, SCOPED_BAN):
            for m in rx.finditer(sentence):
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
        # Tittelen eller et avgrenset forbud demper et ellers klart nei.
        status = (
            DogStatus.CONDITIONAL
            if (title_says_dog or (scoped and len(scoped) == len(neg_ev)))
            else DogStatus.NOT_ALLOWED
        )
        evidence = neg_ev
    else:
        status = DogStatus.CONDITIONAL if title_says_dog else DogStatus.UNCLEAR
        evidence = mention_ev

    if title_says_dog and status is not DogStatus.NOT_ALLOWED:
        evidence = evidence + [f"Tittel: {title}"]

    return DogVerdict(
        status=status,
        evidence=evidence[:3],
        from_date=from_date,
        restrictions=restrictions[:4],
    )
