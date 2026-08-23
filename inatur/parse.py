"""Parsing av søkeresultater og detaljsider fra inatur.no.

STATUS: ikke kalibrert mot ekte HTML ennå (www.inatur.no er ikke tilgjengelig
fra utviklingsmiljøet). Parseren er derfor skrevet *strukturagnostisk*: den
leter etter lenker som ser ut som tilbudslenker, og henter tekstinnholdet fra
kortet rundt dem, i stedet for å låse seg til CSS-klasser som garantert endrer
seg ved neste designoppdatering.

Når `inatur discover` har lagret ekte HTML i fixtures/raw/, strammes
selektorene inn her - og fixturene blir regresjonstester.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from .match import classify_dog, find_species
from .models import Offer

# Tilbudslenker på inatur.no har typisk form /jakt/<slug> eller /smaavilttilbud/<id>
OFFER_HREF = re.compile(
    r"/(?:jakt|smaavilttilbud|smavilttilbud|tilbud|produkt)/[\w\-æøåÆØÅ%]+", re.I
)

# "Utsolgt", "Ikke ledig", "0 ledige" -> ikke tilgjengelig
SOLD_OUT = re.compile(r"\butsolgt\b|\bikke\s+ledig\b|\b0\s+ledige?\b|\bfullteg\w*", re.I)

PRICE = re.compile(r"(\d[\d\s.]*)\s*(?:kr|NOK|,-)", re.I)
QUOTA = re.compile(r"(\d+)\s*ledige?\b", re.I)

EMPTY_MARKERS = re.compile(
    r"ingen\s+treff|ingen\s+resultat|fant\s+ingen|0\s+treff", re.I
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def listing_looks_empty(html: str) -> bool:
    """Sant når søkesiden ikke har flere treff - stoppkriterium for paginering."""
    if not html or not html.strip():
        return True
    if EMPTY_MARKERS.search(html):
        return True
    return not find_offer_links(html)


def find_offer_links(html: str) -> list[str]:
    """Alle unike tilbudslenker på en søkeside, i dokumentrekkefølge."""
    seen: list[str] = []
    for a in _soup(html).find_all("a", href=True):
        href = a["href"]
        if OFFER_HREF.search(href) and href not in seen:
            seen.append(href)
    return seen


def _card_for(link: Tag) -> Tag:
    """Finner det nærmeste elementet som ser ut som et 'kort' rundt lenka."""
    node: Optional[Tag] = link
    for _ in range(4):
        parent = node.parent if node else None
        if not isinstance(parent, Tag):
            break
        node = parent
        if parent.name in ("article", "li") or "card" in " ".join(
            parent.get("class", [])
        ).lower():
            return parent
    return node or link


def offer_id_from_url(url: str) -> str:
    """Stabil id utledet av URL-en - overlever tittelendringer."""
    path = url.split("?")[0].rstrip("/")
    return path.rsplit("/", 1)[-1] or path


def parse_listing(html: str) -> list[Offer]:
    """Trekker ut tilbud fra en søkeside.

    Gir grunnleggende felter. Hunderegler og arter ligger som regel i
    vilkårsteksten på detaljsiden, så `enrich_from_detail` bør kjøres etterpå.
    """
    soup = _soup(html)
    offers: list[Offer] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not OFFER_HREF.search(href):
            continue

        oid = offer_id_from_url(href)
        if oid in seen:
            continue
        seen.add(oid)

        card = _card_for(link)
        text = card.get_text(" ", strip=True)
        title = link.get_text(" ", strip=True) or text[:80]

        price_match = PRICE.search(text)
        quota_match = QUOTA.search(text)
        all_species, priority = find_species(text)

        offers.append(
            Offer(
                id=oid,
                url=href,
                title=title,
                species=all_species,
                priority_species=priority,
                price=price_match.group(0) if price_match else None,
                quota=quota_match.group(0) if quota_match else None,
                available=not SOLD_OUT.search(text),
                dog=classify_dog(text),
                raw_text=text,
            )
        )

    return offers


def enrich_from_detail(offer: Offer, html: str) -> Offer:
    """Oppdaterer et tilbud med arter og hunderegler fra detaljsiden."""
    soup = _soup(html)

    for junk in soup(["script", "style", "nav", "header", "footer"]):
        junk.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True)

    all_species, priority = find_species(text)
    offer.species = sorted(set(offer.species) | set(all_species))
    offer.priority_species = sorted(set(offer.priority_species) | set(priority))
    offer.dog = classify_dog(text)
    offer.raw_text = text

    if SOLD_OUT.search(text):
        offer.available = False

    return offer
