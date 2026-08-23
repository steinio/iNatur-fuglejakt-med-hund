"""Tester for artsgjenkjenning og hundeklassifisering.

Formuleringene her er skrevet for å ligne på hvordan fjellstyrer og grunneiere
faktisk formulerer vilkårene sine. Negasjonstilfellene er de viktigste - det er
der en naiv "inneholder ordet hund og ordet tillatt"-sjekk går i baret.
"""

import pytest

from inatur.match import (
    classify_dog,
    find_non_bird_game,
    find_species,
    split_sentences,
)
from inatur.match import species_from_api as find_api
from inatur.models import DogStatus


# ---------------------------------------------------------------- hund: ja

@pytest.mark.parametrize(
    "text",
    [
        "Jakt med hund er tillatt.",
        "Det er tillatt å bruke hund under jakta.",
        "Bruk av stående fuglehund er lovlig i hele perioden.",
        "Løs, halsende hund tillates.",
        "Hund kan benyttes.",
        "Jakthund er tillatt på hele feltet.",
    ],
)
def test_dog_allowed(text):
    verdict = classify_dog(text)
    assert verdict.status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL)
    assert verdict.is_interesting
    assert verdict.evidence


# ---------------------------------------------------------------- hund: nei

@pytest.mark.parametrize(
    "text",
    [
        "Jakt med hund er ikke tillatt.",
        "Det er ikke tillatt å bruke hund på dette feltet.",
        "Bruk av hund er forbudt.",
        "Jakta foregår uten hund.",
        "Ingen hunder tillatt i reservatet.",
        "Hund er dessverre ikke tillatt her.",
        "Løs, halsende hund er forbudt i hele perioden.",
    ],
)
def test_dog_not_allowed(text):
    verdict = classify_dog(text)
    assert verdict.status is DogStatus.NOT_ALLOWED, verdict.evidence
    assert not verdict.is_interesting


# ------------------------------------------------------- hund: betinget

def test_dog_allowed_from_date():
    verdict = classify_dog("Jakt med hund er tillatt fra 20.09.")
    assert verdict.status is DogStatus.CONDITIONAL
    assert verdict.from_date == "20.09"


def test_dog_allowed_from_date_with_year():
    verdict = classify_dog("Hund kan benyttes fra og med 15.09.2026 i hele terrenget.")
    assert verdict.status is DogStatus.CONDITIONAL
    assert verdict.from_date == "15.09.2026"


def test_date_does_not_break_sentence_splitting():
    """20.09.2026 må ikke splittes i tre 'setninger'."""
    parts = split_sentences("Hund tillatt fra 20.09.2026 og ut sesongen")
    assert len(parts) == 1


def test_restriction_makes_it_conditional():
    verdict = classify_dog("Kun stående fuglehund er tillatt.")
    assert verdict.status is DogStatus.CONDITIONAL
    assert "kun" in verdict.restrictions


def test_mixed_signals_flagged_for_review():
    """Både ja og nei i teksten -> vi tar ikke sjansen, brukeren må lese."""
    text = "Jakt med hund er tillatt. Løs hund er likevel forbudt før 20.09."
    verdict = classify_dog(text)
    assert verdict.status is DogStatus.CONDITIONAL
    assert verdict.is_interesting


def test_double_negation_reads_as_positive():
    verdict = classify_dog("Bruk av hund er ikke forbudt.")
    assert verdict.status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL)


# --------------------------------------------------------- hund: uklart

def test_dog_mentioned_without_verdict_is_unclear():
    """Ren omtale uten noe krav eller tillatelse -> uklart."""
    verdict = classify_dog("Området er populært blant hundefolk.")
    assert verdict.status is DogStatus.UNCLEAR
    assert verdict.is_interesting  # vi varsler heller én gang for mye


def test_krav_til_hundefoerer_impliserer_at_hund_er_lov():
    """Kalibrert mot ekte tekst: et krav til fører forutsetter hund."""
    verdict = classify_dog("Hundefører må vise gyldig sauereinbevis.")
    assert verdict.status is DogStatus.CONDITIONAL
    assert verdict.is_interesting


def test_no_dog_mention():
    verdict = classify_dog("Jakt på lirype og fjellrype i Namsskogan.")
    assert verdict.status is DogStatus.NO_MENTION
    assert verdict.is_interesting


def test_hundre_is_not_a_dog():
    """'hundre' inneholder 'hund' - klassisk falsk positiv."""
    verdict = classify_dog("Terrenget er på to hundre tusen dekar.")
    assert verdict.status is DogStatus.NO_MENTION


def test_empty_text():
    assert classify_dog("").status is DogStatus.NO_MENTION


# ------------------------------------------------------------------ arter

def test_priority_species():
    all_species, priority = find_species("Jakt på lirype og fjellrype")
    assert set(priority) == {"lirype", "fjellrype"}
    assert "lirype" in all_species


def test_generic_rype_counts_as_priority():
    _, priority = find_species("Rypejakt i Trollheimen")
    assert priority == ["rype"]


def test_specific_rype_supersedes_generic():
    """Står det 'lirype', vil vi ikke også se den generiske 'rype'-treffen."""
    _, priority = find_species("Ryper: lirype er hovedarten her")
    assert "rype" not in priority
    assert "lirype" in priority


def test_other_birds():
    all_species, priority = find_species("Jakt på orrfugl, storfugl og rugde")
    assert priority == []
    assert {"orrfugl", "storfugl", "rugde"} <= set(all_species)


def test_non_bird_game_detected_separately():
    all_species, _ = find_species("Harejakt med drivende hund")
    assert all_species == []
    assert find_non_bird_game("Harejakt med drivende hund") == ["hare"]


def test_mixed_bird_and_mammal_offer():
    all_species, priority = find_species("Småviltkort: lirype, hare og rev")
    assert priority == ["lirype"]
    assert find_non_bird_game("Småviltkort: lirype, hare og rev") == ["hare", "rev"]


# ------------------------------------------------- realistisk sammensatt

# ------------------------------------------------- ekte tekst fra inatur.no
#
# Alle tilfellene under er hentet ordrett fra ekte tilbud på inatur.no under
# kalibreringen. Hver enkelt var opprinnelig feilklassifisert.


def test_ekte_bufesertifikat():
    v = classify_dog("Jakt med hund med gyldig bufesertifikat tillatt, 1 hund pr. jeger.")
    assert v.status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL)


def test_ekte_med_og_uten_hund_i_tittel():
    """'med og uten hund' tilbyr BEGGE varianter - ikke et nei."""
    v = classify_dog("UTENBYGDS, SMÅVILTJAKT med og uten hund i Heidal")
    assert v.status is not DogStatus.NOT_ALLOWED
    assert v.is_interesting


def test_ekte_med_og_utan_hund_nynorsk():
    v = classify_dog("Småviltjakt med og utan hund i Suldal")
    assert v.status is not DogStatus.NOT_ALLOWED


def test_ekte_nynorsk_ikkje_tillete():
    """Nynorsk: 'ikkje' + 'tillete' må leses som et nei."""
    v = classify_dog("Ikkje tillete med hund.")
    assert v.status is DogStatus.NOT_ALLOWED


def test_ekte_nynorsk_utan_hund():
    v = classify_dog("Det er fritt kortsal for småviltjakt utan hund.")
    assert v.status is DogStatus.NOT_ALLOWED


def test_ekte_nynorsk_ikkje_lov_foer_dato():
    """'ikkje lov ... før 1. oktober' betyr lov FRA 1. oktober."""
    v = classify_dog(
        "I Aurland statsallmenning er det ikkje lov å jakta med hund før 1. oktober."
    )
    assert v.status is DogStatus.CONDITIONAL
    assert v.from_date is not None
    assert "oktober" in v.from_date
    assert v.is_interesting


def test_ekte_rett_til_aa_bruke_hund():
    v = classify_dog("Et jaktkort hos oss gir også rett til å bruke en hund.")
    assert v.status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL)


def test_ekte_treningskort_med_avgrenset_forbud():
    """Et treningskort for fuglehund er ikke et nei fordi ett område er unntatt."""
    v = classify_dog(
        "Det er ikke tillatt å trene hund i Middagsfjellet hundeforbudsområde "
        "i perioden fra og med 1. desember til og med 31. mars.",
        title="Treningskort for stående fuglehund",
    )
    assert v.status is DogStatus.CONDITIONAL
    assert v.is_interesting


def test_ekte_unntak_for_saerskilte_omraader():
    v = classify_dog(
        "Jakt med hund er tillatt, med unntak av i særskilte områder og tidsrom "
        "som fastsettes nærmere i fjellstyrets forvaltningsplan."
    )
    assert v.status is DogStatus.CONDITIONAL


@pytest.mark.parametrize(
    "text",
    [
        "Hund skal ha sauerenhetsbevis ikke eldre enn 2 år.",
        "Jakthund må dokumentert være sauerein.",
        "Kortet benyttes til trening av fuglehund i den tildelte perioden.",
    ],
)
def test_ekte_krav_til_hunden_betyr_at_hund_er_lov(text):
    """Et krav *til* hunden forutsetter at hund i det hele tatt er tillatt."""
    v = classify_dog(text)
    assert v.status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL), v.evidence
    assert v.is_interesting


def test_krav_med_negasjon_er_fortsatt_nei():
    """'hund må ikke brukes' er et krav i formen, men et nei i innholdet."""
    v = classify_dog("Hund må ikke brukes under jakta.")
    assert v.status is DogStatus.NOT_ALLOWED


@pytest.mark.parametrize(
    "text",
    [
        "Alle jaktkort tilbys som «jakt med hund», jegerne velger selv om de vil "
        "benytte hund under jakten.",
        "Området egner seg godt for småviltjakt, både som støkkjakt og jakt med hund.",
    ],
)
def test_ekte_uttrykket_jakt_med_hund_er_positivt(text):
    v = classify_dog(text)
    assert v.status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL), v.evidence


def test_med_fuglehund_om_takstering_teller_ikke():
    """'linjetakst utført med fuglehund' er ikke en hunderegel."""
    v = classify_dog(
        "Kvotene fastsettes ca 25. august etter at linjetakst er utført med "
        "fuglehund for å finne produksjonen."
    )
    assert v.status is DogStatus.UNCLEAR


def test_negert_setning_utloeser_ikke_uttrykksregelen():
    v = classify_dog("Det er ikke anledning til jakt med hund her.")
    assert v.status is DogStatus.NOT_ALLOWED


def test_tittel_loefter_uklar_til_betinget():
    v = classify_dog("Hundefører må vise gyldig sauereinbevis.", title="Rypejakt med hund")
    assert v.status is DogStatus.CONDITIONAL


def test_tittel_overstyrer_ikke_klart_nei():
    """Sier teksten tydelig nei, skal ikke tittelen overprøve det."""
    v = classify_dog("Jakt med hund er ikke tillatt.", title="Rypejakt")
    assert v.status is DogStatus.NOT_ALLOWED


# ------------------------------------------------------- arter fra API-et


def test_api_species_priority():
    birds, priority, other = find_api(["Lirype", "Fjellrype", "Hare"])
    assert priority == ["Fjellrype", "Lirype"]
    assert "Lirype" in birds
    assert other == ["Hare"]


def test_api_species_non_bird_only():
    birds, priority, other = find_api(["Hare", "Rødrev", "Mår"])
    assert birds == []
    assert priority == []
    assert other == ["Hare", "Mår", "Rødrev"]


def test_api_smaavilt_counts_as_possible_bird():
    """'Småvilt' er upresist, men omfatter i praksis nesten alltid rype."""
    birds, priority, _ = find_api(["Småvilt"])
    assert birds == ["Småvilt"]
    assert priority == []


def test_api_unknown_species_is_kept():
    """Nye artsnavn skal ikke stille filtrere bort tilbud."""
    birds, _, _ = find_api(["Fjellrype", "Kattugle"])
    assert "Kattugle" in birds


def test_api_empty():
    assert find_api([]) == ([], [], [])
    assert find_api(None) == ([], [], [])


REALISTIC = """
Småviltjakt i Namsskogan statsallmenning.
Arter: lirype, fjellrype og orrfugl.
Jaktperiode: 20.09.2026 - 23.12.2026.
Jakt med hund er tillatt fra 20.09. Båndtvang gjelder fram til 20.08.
Kortet gir rett til felling av inntil 2 ryper per dag.
"""


def test_realistic_offer():
    all_species, priority = find_species(REALISTIC)
    verdict = classify_dog(REALISTIC)

    assert set(priority) == {"lirype", "fjellrype"}
    assert "orrfugl" in all_species
    assert verdict.status is DogStatus.CONDITIONAL
    assert verdict.from_date == "20.09"
    assert verdict.is_interesting
