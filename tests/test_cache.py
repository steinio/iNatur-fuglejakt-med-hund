"""Tester for mellomlagring av hundevurderinger.

Uten dette hentet hver kjøring ~1000 detaljsider - hvert kvarter. Med det
hentes kun tilbud som er nye eller faktisk endret, målt på API-feltet
`sistOppdatert`.

Det farlige med en slik optimalisering er at den kan gjøre verktøyet *stille*
feil: gjenbruker vi en vurdering for lenge, går vi glipp av endrede
hunderegler. Testene her passer på begge retninger.
"""

import pytest

from inatur.models import DogStatus, DogVerdict, Offer
from inatur.store import Store


def make(oid="1", updated=1000, status=DogStatus.ALLOWED, text="Hund tillatt"):
    return Offer(
        id=oid,
        url=f"/jakt/{oid}/x",
        title=f"Rypejakt {oid}",
        species=["Lirype"],
        priority_species=["Lirype"],
        dog=DogVerdict(status, evidence=["Jakt med hund er tillatt"], from_date="20.09"),
        raw_text=text,
        last_updated=updated,
    )


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "c.db") as s:
        yield s


def test_verdict_survives_roundtrip(store):
    store.record([make()])
    cached = store.cached_verdicts()

    assert "1" in cached
    last_updated, text_hash, verdict = cached["1"]
    assert last_updated == 1000
    assert verdict.status is DogStatus.ALLOWED
    assert verdict.from_date == "20.09"
    assert verdict.evidence == ["Jakt med hund er tillatt"]


def test_text_hash_is_cached_so_diff_stays_stable(store):
    """Gjenbruker vi vurderingen, må hashen følge med - ellers rapporteres
    tilbudet som «endrede vilkår» hver eneste kjøring."""
    original = make()
    store.record([original])
    _, cached_hash, _ = store.cached_verdicts()["1"]

    # Ny kjøring: samme tilbud, men vi henter aldri teksten.
    fresh = Offer(id="1", url="/jakt/1/x", title="Rypejakt 1", last_updated=1000)
    fresh.text_hash = cached_hash

    assert store.diff([fresh]) == []


def test_changed_last_updated_is_not_reused(store):
    """Endret sistOppdatert betyr at detaljsiden må hentes på nytt."""
    store.record([make(updated=1000)])
    cached = store.cached_verdicts()

    incoming = make(updated=2000)
    hit = cached.get(incoming.id)
    assert hit is not None
    assert hit[0] != incoming.last_updated  # -> skal regnes som utdatert


def test_missing_last_updated_is_never_reused(store):
    """Mangler API-et sistOppdatert, tør vi ikke gjenbruke noe."""
    store.record([make(updated=None)])
    last_updated, _, _ = store.cached_verdicts()["1"]
    assert last_updated is None


def test_offer_without_verdict_is_not_in_cache(store):
    """Bare tilbud vi faktisk har vurdert skal kunne gjenbrukes."""
    store.record([make()])
    store.conn.execute("UPDATE offers SET dog_json = NULL WHERE id = '1'")
    store.conn.commit()
    assert store.cached_verdicts() == {}


def test_corrupt_cache_entry_is_skipped(store):
    store.record([make()])
    store.conn.execute("UPDATE offers SET dog_json = 'ikke json' WHERE id = '1'")
    store.conn.commit()
    assert store.cached_verdicts() == {}  # skal ikke krasje


def test_schema_migrates_from_old_database(tmp_path):
    """Databaser fra før mellomlagringen skal oppgraderes, ikke krasje."""
    path = tmp_path / "old.db"
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE offers (
            id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
            available INTEGER NOT NULL, text_hash TEXT NOT NULL,
            dog_status TEXT NOT NULL, species TEXT NOT NULL DEFAULT '',
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, notified_at TEXT
        );
        INSERT INTO offers VALUES ('1','/x','T',1,'abc','allowed','Lirype','n','n',NULL);
        """
    )
    conn.commit()
    conn.close()

    with Store(path) as s:
        assert s.count() == 1
        assert s.cached_verdicts() == {}  # ingen lagrede vurderinger ennå
        s.record([make()])
        assert "1" in s.cached_verdicts()


def test_hash_recomputes_when_text_changes():
    offer = make(text="gammel tekst")
    first = offer.text_hash
    offer.raw_text = "ny tekst"
    offer.refresh_hash()
    assert offer.text_hash != first
