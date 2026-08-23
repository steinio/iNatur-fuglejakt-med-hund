"""SQLite-lagring av sette tilbud, og diffing mot forrige kjøring.

Uten dette ville verktøyet varslet om de samme 40 tilbudene hvert kvarter.
Poenget er å svare på ett spørsmål: *hva er nytt siden sist?*

Tre endringer er interessante:
  NEW            - tilbudet har vi aldri sett før
  BACK_IN_STOCK  - var utsolgt, er ledig igjen (restsalg/avbestillinger)
  TERMS_CHANGED  - vilkårsteksten er endret (kan bety endrede hunderegler)
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .models import Change, ChangeKind, Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id           TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    available    INTEGER NOT NULL,
    text_hash    TEXT NOT NULL,
    dog_status   TEXT NOT NULL,
    species      TEXT NOT NULL DEFAULT '',
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    notified_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_offers_available ON offers(available);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = "state.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        with closing(self.conn.cursor()) as cur:
            cur.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------

    def diff(self, offers: list[Offer]) -> list[Change]:
        """Sammenligner nye tilbud mot lagret tilstand. Muterer ikke basen."""
        changes: list[Change] = []
        with closing(self.conn.cursor()) as cur:
            for offer in offers:
                cur.execute(
                    "SELECT available, text_hash FROM offers WHERE id = ?", (offer.id,)
                )
                row = cur.fetchone()

                if row is None:
                    changes.append(Change(ChangeKind.NEW, offer))
                    continue

                was_available = bool(row["available"])
                if offer.available and not was_available:
                    changes.append(
                        Change(
                            ChangeKind.BACK_IN_STOCK,
                            offer,
                            "var utsolgt, er ledig igjen",
                        )
                    )
                elif offer.available and row["text_hash"] != offer.text_hash:
                    changes.append(
                        Change(ChangeKind.TERMS_CHANGED, offer, "vilkårsteksten er endret")
                    )
        return changes

    def record(self, offers: list[Offer], mark_notified: list[str] | None = None) -> None:
        """Skriver gjeldende tilstand. Kall etter at varsling er gjort."""
        now = _now()
        notified = set(mark_notified or [])
        with closing(self.conn.cursor()) as cur:
            for offer in offers:
                cur.execute(
                    """
                    INSERT INTO offers (id, url, title, available, text_hash,
                                        dog_status, species, first_seen, last_seen,
                                        notified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        url         = excluded.url,
                        title       = excluded.title,
                        available   = excluded.available,
                        text_hash   = excluded.text_hash,
                        dog_status  = excluded.dog_status,
                        species     = excluded.species,
                        last_seen   = excluded.last_seen,
                        notified_at = COALESCE(excluded.notified_at, offers.notified_at)
                    """,
                    (
                        offer.id,
                        offer.url,
                        offer.title,
                        int(offer.available),
                        offer.text_hash,
                        offer.dog.status.value,
                        ",".join(offer.species),
                        now,
                        now,
                        now if offer.id in notified else None,
                    ),
                )
        self.conn.commit()

    def count(self) -> int:
        with closing(self.conn.cursor()) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM offers")
            return cur.fetchone()["n"]

    def is_empty(self) -> bool:
        """Første kjøring - da er *alt* 'nytt', og vi vil ikke spamme."""
        return self.count() == 0
