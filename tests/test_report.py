"""Tester for rapportgenerering."""

from inatur.match import classify_dog
from inatur.models import Change, ChangeKind, DogStatus, DogVerdict, Offer
from inatur.report import render


def offer(oid, title, text, species, priority):
    return Offer(
        id=oid,
        url=f"https://www.inatur.no/jakt/{oid}",
        title=title,
        species=species,
        priority_species=priority,
        dog=classify_dog(text),
        raw_text=text,
    )


def test_no_changes():
    out = render([], total_scanned=42)
    assert "Ingen endringer" in out
    assert "42" in out


def test_first_run_explains_itself():
    out = render([], total_scanned=10, first_run=True)
    assert "Første kjøring" in out


def test_report_contains_offer_details():
    o = offer("1", "Rypejakt Namsskogan", "Jakt med hund er tillatt.", ["lirype"], ["lirype"])
    out = render([Change(ChangeKind.NEW, o)], total_scanned=1)

    assert "Rypejakt Namsskogan" in out
    assert "lirype" in out
    assert "HUND TILLATT" in out
    assert o.url in out
    assert "NYTT" in out


def test_evidence_is_shown():
    """Brukeren skal alltid kunne se hvorfor vi konkluderte som vi gjorde."""
    o = offer("1", "Test", "Jakt med hund er tillatt.", ["lirype"], ["lirype"])
    out = render([Change(ChangeKind.NEW, o)], total_scanned=1)
    assert "Jakt med hund er tillatt" in out


def test_priority_offers_sort_first():
    plain = offer("2", "Orrfugljakt", "Hund er tillatt.", ["orrfugl"], [])
    prio = offer("1", "Lirypejakt", "Hund er tillatt.", ["lirype"], ["lirype"])

    out = render(
        [Change(ChangeKind.NEW, plain), Change(ChangeKind.NEW, prio)], total_scanned=2
    )
    assert out.index("Lirypejakt") < out.index("Orrfugljakt")
    assert "1 med li-/fjellrype" in out


def test_back_in_stock_labelled():
    o = offer("1", "Rypejakt", "Hund tillatt.", ["lirype"], ["lirype"])
    out = render(
        [Change(ChangeKind.BACK_IN_STOCK, o, "var utsolgt, er ledig igjen")],
        total_scanned=1,
    )
    assert "LEDIG IGJEN" in out
    assert "var utsolgt" in out


def test_unclear_status_still_rendered():
    o = Offer(
        id="1",
        url="https://www.inatur.no/jakt/1",
        title="Uklart tilbud",
        species=["lirype"],
        priority_species=["lirype"],
        dog=DogVerdict(DogStatus.UNCLEAR, evidence=["Hundefører må vise bevis"]),
    )
    out = render([Change(ChangeKind.NEW, o)], total_scanned=1)
    assert "USIKKER" in out
