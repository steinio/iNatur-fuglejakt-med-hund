"""Regresjonstester mot ekte data fra inatur.no.

Fixturene er hentet fra det virkelige nettstedet under kalibreringen. Endrer
inatur.no formatet sitt, skal disse testene feile - i stedet for at varslene
stille slutter å komme.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from inatur.match import classify_dog
from inatur.models import DogStatus
from inatur.parse import detail_text, enrich_from_detail, offer_from_api, rules_text

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def search_page():
    return json.loads((FIXTURES / "search_page.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def detail_html():
    return (FIXTURES / "detail_ringvassoy.html").read_text(encoding="utf-8")


# ------------------------------------------------------- API-kontrakten


def test_api_response_shape(search_page):
    """Feltene vi er avhengige av må finnes i svaret."""
    assert "paginering" in search_page
    assert "resultat" in search_page
    record = search_page["resultat"][0]
    for felt in ("id", "url", "tittel", "arter", "utsolgt", "fylker", "harTrekning"):
        assert felt in record, f"API-et mangler feltet {felt}"


def test_pagination_shape(search_page):
    assert "harNesteSide" in search_page["paginering"]
    assert "totaltAntallElementer" in search_page["paginering"]


# --------------------------------------------------- omforming til Offer


def test_offer_from_api_ringvassoy(search_page):
    record = search_page["resultat"][0]
    offer = offer_from_api(record)

    assert offer.id == "55703df3e4b06b508ac2b37a"
    assert offer.title == "Småviltjakt Ringvassøy."
    assert offer.tilbyder == "Skarsfjord Utmarkslag"
    assert offer.fylke == "Troms"
    assert set(offer.priority_species) == {"Lirype", "Fjellrype"}
    assert offer.is_priority
    assert offer.available
    assert not offer.lottery
    assert offer.full_url.startswith("https://www.inatur.no/jakt/")


def test_offer_dates_parsed_from_epoch(search_page):
    offer = offer_from_api(search_page["resultat"][0])
    assert isinstance(offer.period_start, date)
    assert isinstance(offer.period_end, date)
    assert offer.period_start < offer.period_end


def test_offer_separates_birds_from_mammals(search_page):
    """Trysil-tilbudet har både fugl og hare."""
    offer = offer_from_api(search_page["resultat"][1])
    assert "Hare" in offer.other_game
    assert "Hare" not in offer.species
    assert offer.is_priority


def test_offer_without_priority_species(search_page):
    offer = offer_from_api(search_page["resultat"][2])
    assert not offer.is_priority
    assert offer.has_birds  # due/and/gjess er fortsatt fugl


def test_price_is_formatted(search_page):
    offer = offer_from_api(search_page["resultat"][0])
    assert offer.price and "kr" in offer.price


# ------------------------------------------------------- detaljsiden


def test_detail_text_extracts_rules(detail_html):
    text = detail_text(detail_html)
    assert "Jaktregler" in text
    assert "bufesertifikat" in text


def test_rules_text_starts_at_a_known_heading(detail_html):
    rules = rules_text(detail_text(detail_html))
    assert "Jaktregler" in rules or "Jaktkvoter" in rules


def test_rules_text_falls_back_to_full_text():
    """Ukjent overskrift skal ikke føre til at vi mister teksten."""
    text = "En helt ukjent overskrift\nJakt med hund er tillatt."
    assert rules_text(text) == text


def test_enrich_gives_dog_verdict(search_page, detail_html):
    """Hele kjeden: API-treff + detaljside -> hundevurdering med begrunnelse."""
    offer = offer_from_api(search_page["resultat"][0])
    enrich_from_detail(offer, detail_html)

    assert offer.dog.status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL)
    assert offer.dog.is_interesting
    assert any("hund" in e.lower() for e in offer.dog.evidence)


def test_real_rules_text_classifies_as_dog_allowed(detail_html):
    rules = rules_text(detail_text(detail_html))
    assert classify_dog(rules).status in (DogStatus.ALLOWED, DogStatus.CONDITIONAL)


# ------------------------------------------------- fylkefilter i API-et


def test_search_url_without_fylke():
    from inatur.api import Client

    with Client() as c:
        url = c.search_url(page=2)
    assert "smaavilttilbud" in url
    assert "p=2" in url
    assert "fylker" not in url


def test_search_url_with_fylke():
    """Tjenersiden filtrerer på feltet `fylker` - det sparer ~130 sider."""
    from inatur.api import Client

    with Client() as c:
        url = c.search_url(fylke="Vestland")
    assert "fylker" in url
    assert "Vestland" in url


def test_search_merges_and_dedupes_fylker(monkeypatch):
    """Ett søk per fylke, og et tilbud som ligger i to fylker skal kun telles én gang."""
    from inatur.api import Client

    pages = {
        "Vestland": [{"id": "a"}, {"id": "delt"}],
        "Rogaland": [{"id": "b"}, {"id": "delt"}],
    }

    with Client() as c:
        def fake(only_available, fylke):
            yield from pages[fylke]

        monkeypatch.setattr(c, "_search_one", fake)
        ids = [r["id"] for r in c.search(fylker=["Vestland", "Rogaland"])]

    assert ids == ["a", "delt", "b"]
