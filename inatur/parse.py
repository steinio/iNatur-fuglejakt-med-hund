"""Omforming av API-treff og detaljsider til Offer-objekter.

Søke-API-et gir strukturerte felter (arter, utsolgt, fylker, priser, datoer).
Det eneste vi må hente fra HTML er vilkårsteksten - «Jaktregler» og
«Mer detaljert beskrivelse» - der hundereglene står.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .api import _epoch_to_date
from .match import classify_dog, species_from_api
from .models import Offer

# Overskriftene på detaljsiden der hundereglene erfaringsmessig står.
RULE_SECTIONS = (
    "jaktregler",
    "mer detaljert beskrivelse",
    "jaktkvoter",
    "viktige datoer",
    "vilkår",
    "praktisk informasjon",
)


def offer_from_api(record: dict[str, Any]) -> Offer:
    """Bygger et Offer fra ett søketreff. Hundestatus settes først etter at
    detaljsiden er hentet - søketreffet sier ingenting om hund."""
    birds, priority, other_game = species_from_api(record.get("arter"))

    price = record.get("fraPris")
    fylker = record.get("fylkerFormatert") or ", ".join(record.get("fylker") or [])
    kommuner = record.get("kommunerFormatert") or ", ".join(record.get("kommuner") or [])

    offer = Offer(
        id=str(record.get("id") or ""),
        url=record.get("url") or "",
        title=(record.get("tittel") or "").strip(),
        tilbyder=record.get("tilbydernavn"),
        kommune=kommuner or None,
        fylke=fylker or None,
        fylker=[f for f in (record.get("fylker") or []) if f],
        species=birds,
        priority_species=priority,
        other_game=other_game,
        period_start=_epoch_to_date(record.get("fra")),
        period_end=_epoch_to_date(record.get("til")),
        sales_start=_epoch_to_date(record.get("salgsstart")),
        application_deadline=_epoch_to_date(record.get("soknadsfrist")),
        price=f"fra {int(price)} kr" if price else None,
        # Utsolgt kan bli ledig igjen; utløpt kan ikke. De holdes derfor
        # fra hverandre - vi følger fortsatt med på utsolgte tilbud.
        available=not record.get("utsolgt", False),
        flagged_expired=bool(record.get("utlopt")),
        lottery=bool(record.get("harTrekning")),
        last_updated=record.get("sistOppdatert"),
        short_description=(record.get("kortBeskrivelse") or "").strip(),
    )

    # Foreløpig vurdering basert på tittel og ingress. Overskrives av
    # enrich_from_detail så snart vi har vilkårsteksten.
    offer.dog = classify_dog(offer.short_description, title=offer.title)
    return offer


def detail_text(html: str) -> str:
    """Trekker ut lesbar tekst fra en detaljside."""
    soup = BeautifulSoup(html, "lxml")
    for junk in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        junk.decompose()

    main = soup.find("main") or soup.body or soup
    text = main.get_text("\n", strip=True)
    return re.sub(r"\n\s*\n+", "\n", text)


def rules_text(text: str) -> str:
    """Isolerer regeldelen av siden hvis vi kjenner igjen overskriftene.

    Faller tilbake på hele teksten - bedre å vurdere for mye enn å gå glipp av
    en hunderegel som står under en overskrift vi ikke har sett før.
    """
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() in RULE_SECTIONS:
            start = i
            break
    if start is None:
        return text
    return "\n".join(lines[start:])


def enrich_from_detail(offer: Offer, html: str) -> Offer:
    """Fyller inn vilkårstekst og endelig hundevurdering fra detaljsiden."""
    text = detail_text(html)
    offer.raw_text = rules_text(text)
    offer.refresh_hash()
    offer.dog = classify_dog(offer.raw_text, title=offer.title)
    offer.classified = True
    return offer
