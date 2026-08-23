"""Tester for artsgjenkjenning og hundeklassifisering.

Formuleringene her er skrevet for å ligne på hvordan fjellstyrer og grunneiere
faktisk formulerer vilkårene sine. Negasjonstilfellene er de viktigste - det er
der en naiv "inneholder ordet hund og ordet tillatt"-sjekk går i baret.
"""

import pytest

from inatur.match import classify_dog, find_non_bird_game, find_species, split_sentences
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
    verdict = classify_dog("Hundefører må vise gyldig sauereinbevis.")
    assert verdict.status is DogStatus.UNCLEAR
    assert verdict.is_interesting  # vi varsler heller én gang for mye


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
