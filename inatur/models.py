"""Kjernemodeller for tilbud hentet fra inatur.no."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class DogStatus(str, Enum):
    """Om et tilbud tillater bruk av hund.

    Rekkefølgen er bevisst: ALLOWED er sterkest, NO_MENTION svakest.
    """

    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    NOT_ALLOWED = "not_allowed"
    UNCLEAR = "unclear"
    NO_MENTION = "no_mention"

    @property
    def label(self) -> str:
        return {
            DogStatus.ALLOWED: "HUND TILLATT",
            DogStatus.CONDITIONAL: "HUND TILLATT MED FORBEHOLD",
            DogStatus.NOT_ALLOWED: "HUND IKKE TILLATT",
            DogStatus.UNCLEAR: "USIKKER - LES SELV",
            DogStatus.NO_MENTION: "HUND IKKE NEVNT",
        }[self]

    @property
    def icon(self) -> str:
        return {
            DogStatus.ALLOWED: "[JA]",
            DogStatus.CONDITIONAL: "[JA*]",
            DogStatus.NOT_ALLOWED: "[NEI]",
            DogStatus.UNCLEAR: "[?]",
            DogStatus.NO_MENTION: "[-]",
        }[self]


@dataclass
class DogVerdict:
    """Resultatet av hundeklassifiseringen, med begrunnelse."""

    status: DogStatus
    evidence: list[str] = field(default_factory=list)
    from_date: Optional[str] = None
    restrictions: list[str] = field(default_factory=list)

    @property
    def is_interesting(self) -> bool:
        """Alt utenom et klart nei er verdt å se på."""
        return self.status is not DogStatus.NOT_ALLOWED

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "evidence": self.evidence,
            "from_date": self.from_date,
            "restrictions": self.restrictions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DogVerdict":
        return cls(
            status=DogStatus(data["status"]),
            evidence=list(data.get("evidence") or []),
            from_date=data.get("from_date"),
            restrictions=list(data.get("restrictions") or []),
        )


@dataclass
class Offer:
    """Et småvilttilbud fra inatur.no."""

    id: str
    url: str
    title: str

    tilbyder: Optional[str] = None
    kommune: Optional[str] = None
    fylke: Optional[str] = None

    species: list[str] = field(default_factory=list)
    priority_species: list[str] = field(default_factory=list)
    other_game: list[str] = field(default_factory=list)

    period_start: Optional[date] = None
    period_end: Optional[date] = None
    sales_start: Optional[date] = None
    application_deadline: Optional[date] = None

    price: Optional[str] = None
    quota: Optional[str] = None
    available: bool = True

    # Trekning i stedet for direktesalg - da gjelder søknadsfrist, ikke
    # "førstemann til mølla".
    lottery: bool = False

    short_description: str = ""
    dog: DogVerdict = field(default_factory=lambda: DogVerdict(DogStatus.NO_MENTION))
    raw_text: str = ""

    # Millisekunder siden epoch, fra API-feltet `sistOppdatert`. Nøkkelen til å
    # slippe å hente detaljsiden på nytt for tilbud som ikke er endret.
    last_updated: Optional[int] = None

    # Utledes av raw_text, men kan settes direkte når vi gjenbruker en
    # mellomlagret vurdering og dermed aldri henter teksten.
    text_hash: str = ""

    def __post_init__(self) -> None:
        if not self.text_hash and self.raw_text:
            self.refresh_hash()

    def refresh_hash(self) -> None:
        self.text_hash = hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()[:16]

    @property
    def full_url(self) -> str:
        return f"https://www.inatur.no{self.url}" if self.url.startswith("/") else self.url

    @property
    def has_birds(self) -> bool:
        return bool(self.species)

    @property
    def is_priority(self) -> bool:
        """Lirype eller fjellrype - det brukeren bryr seg mest om."""
        return bool(self.priority_species)


class ChangeKind(str, Enum):
    NEW = "new"
    BACK_IN_STOCK = "back_in_stock"
    TERMS_CHANGED = "terms_changed"


@dataclass
class Change:
    kind: ChangeKind
    offer: Offer
    detail: str = ""
