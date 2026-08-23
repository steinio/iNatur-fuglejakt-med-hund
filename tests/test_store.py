"""Tester for tilstandslagring og diffing."""

import pytest

from inatur.models import ChangeKind, DogStatus, DogVerdict, Offer
from inatur.store import Store


def make_offer(oid="1", available=True, text="Jakt med hund er tillatt"):
    return Offer(
        id=oid,
        url=f"https://www.inatur.no/jakt/{oid}",
        title=f"Rypejakt {oid}",
        species=["lirype"],
        priority_species=["lirype"],
        available=available,
        dog=DogVerdict(DogStatus.ALLOWED),
        raw_text=text,
    )


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def test_first_run_everything_is_new(store):
    changes = store.diff([make_offer("1"), make_offer("2")])
    assert len(changes) == 2
    assert all(c.kind is ChangeKind.NEW for c in changes)
    assert store.is_empty()


def test_known_offer_is_not_reported_again(store):
    offers = [make_offer("1")]
    store.record(offers)
    assert store.diff(offers) == []


def test_back_in_stock_is_detected(store):
    """Den viktigste hendelsen: restsalg og avbestillinger."""
    store.record([make_offer("1", available=False)])
    changes = store.diff([make_offer("1", available=True)])

    assert len(changes) == 1
    assert changes[0].kind is ChangeKind.BACK_IN_STOCK


def test_going_out_of_stock_is_not_reported(store):
    store.record([make_offer("1", available=True)])
    assert store.diff([make_offer("1", available=False)]) == []


def test_changed_terms_are_detected(store):
    store.record([make_offer("1", text="Hund er ikke tillatt")])
    changes = store.diff([make_offer("1", text="Jakt med hund er tillatt fra 20.09")])

    assert len(changes) == 1
    assert changes[0].kind is ChangeKind.TERMS_CHANGED


def test_terms_change_on_sold_out_offer_is_ignored(store):
    """Endret tekst på et utsolgt kort er ikke noe å vekke brukeren for."""
    store.record([make_offer("1", available=False, text="gammel tekst")])
    assert store.diff([make_offer("1", available=False, text="ny tekst")]) == []


def test_record_is_idempotent(store):
    offers = [make_offer("1")]
    store.record(offers)
    store.record(offers)
    assert store.count() == 1


def test_state_survives_reopen(tmp_path):
    path = tmp_path / "state.db"
    with Store(path) as s:
        s.record([make_offer("1")])

    with Store(path) as s:
        assert s.count() == 1
        assert s.diff([make_offer("1")]) == []
