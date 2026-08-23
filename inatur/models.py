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

    period_start: Optional[date] = None
    period_end: Optional[date] = None

    price: Optional[str] = None
    quota: Optional[str] = None
    available: bool = True

    dog: DogVerdict = field(default_factory=lambda: DogVerdict(DogStatus.NO_MENTION))
    raw_text: str = ""

    @property
    def text_hash(self) -> str:
        """Endres når vilkårsteksten endres - brukes til å oppdage stille endringer."""
        return hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()[:16]

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
