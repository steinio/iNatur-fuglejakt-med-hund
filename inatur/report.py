"""Rapportering til konsoll og fil.

Brukeren har valgt konsoll/logg foreløpig. Grensesnittet her er bevisst smalt
(`render` + `write`) slik at en Telegram- eller e-postvarsler senere kan legges
til uten å røre resten av koden.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import Change, ChangeKind, DogStatus, Offer

KIND_LABEL = {
    ChangeKind.NEW: "NYTT",
    ChangeKind.BACK_IN_STOCK: "LEDIG IGJEN",
    ChangeKind.TERMS_CHANGED: "ENDREDE VILKÅR",
}

RULE = "=" * 72


def _offer_block(offer: Offer, prefix: str = "") -> list[str]:
    star = " *" if offer.is_priority else ""
    lines = [f"{prefix}{offer.title}{star}"]

    if offer.species:
        lines.append(f"   Arter:   {', '.join(offer.species)}")

    dog = offer.dog
    dog_line = f"   Hund:    {dog.status.icon} {dog.status.label}"
    if dog.from_date:
        dog_line += f" (fra {dog.from_date})"
    lines.append(dog_line)

    if dog.restrictions:
        lines.append(f"   Forbehold: {', '.join(dog.restrictions)}")

    for ev in dog.evidence:
        snippet = ev if len(ev) <= 100 else ev[:97] + "..."
        lines.append(f'            "{snippet}"')

    where = ", ".join(x for x in (offer.kommune, offer.fylke) if x)
    if where:
        lines.append(f"   Sted:    {where}")

    meta = " | ".join(x for x in (offer.price, offer.quota) if x)
    if meta:
        lines.append(f"   Info:    {meta}")

    lines.append(f"   Lenke:   {offer.url}")
    return lines


def render(changes: list[Change], total_scanned: int, first_run: bool = False) -> str:
    """Bygger rapporten som vises i terminalen og lagres til fil."""
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    out = [RULE, f"iNatur fuglejakt med hund - {stamp}", RULE]

    if first_run:
        out += [
            "",
            "Første kjøring: lagrer utgangspunktet. Fra neste kjøring vises",
            "kun det som er nytt eller har blitt ledig igjen.",
            "",
        ]

    if not changes:
        out += ["", f"Ingen endringer. {total_scanned} tilbud gjennomgått.", ""]
        return "\n".join(out)

    # Prioriterte arter (li-/fjellrype) først, deretter sikreste hundestatus.
    order = {
        DogStatus.ALLOWED: 0,
        DogStatus.CONDITIONAL: 1,
        DogStatus.UNCLEAR: 2,
        DogStatus.NO_MENTION: 3,
        DogStatus.NOT_ALLOWED: 4,
    }
    ranked = sorted(
        changes,
        key=lambda c: (not c.offer.is_priority, order[c.offer.dog.status]),
    )

    priority_count = sum(1 for c in ranked if c.offer.is_priority)
    out += [
        "",
        f"{len(ranked)} endring(er) - {priority_count} med li-/fjellrype",
        f"({total_scanned} tilbud gjennomgått)",
        "",
    ]

    current_kind = None
    for change in ranked:
        if change.kind is not current_kind:
            current_kind = change.kind
            out += [f"--- {KIND_LABEL[change.kind]} " + "-" * (68 - len(KIND_LABEL[change.kind]))]
        out += _offer_block(change.offer)
        if change.detail:
            out.append(f"   Merk:    {change.detail}")
        out.append("")

    out += ["", "* = lirype eller fjellrype", RULE]
    return "\n".join(out)


def write(report: str, path: str | Path = "reports/latest.txt") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return target
