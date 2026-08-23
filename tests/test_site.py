"""Tester for HTML-siden.

Siden publiseres offentlig på GitHub Pages, så det viktigste her er at
tekst fra inatur.no blir escapet - titler og vilkårstekst er innhold vi ikke
kontrollerer selv.
"""

from datetime import date

from inatur.models import DogStatus, DogVerdict, Offer
from inatur.site import render_site


def make(oid="1", title="Rypejakt", status=DogStatus.ALLOWED, prio=True, **kw):
    return Offer(
        id=oid,
        url=f"/jakt/{oid}/rypejakt",
        title=title,
        species=["Lirype", "Fjellrype"] if prio else ["Orrfugl"],
        priority_species=["Lirype", "Fjellrype"] if prio else [],
        dog=DogVerdict(status, evidence=["Jakt med hund er tillatt"]),
        **kw,
    )


def test_page_is_self_contained():
    """Ingen eksterne ressurser - siden skal virke uansett hvor den ligger."""
    page = render_site([make()])
    for forbidden in ("http://", "cdn.", "<link rel=\"stylesheet\""):
        assert forbidden not in page
    assert "<style>" in page and "<script>" in page


def test_page_links_to_inatur():
    page = render_site([make()])
    assert "https://www.inatur.no/jakt/1/rypejakt" in page


def test_html_in_title_is_escaped():
    """Titler kommer fra inatur.no og må ikke kunne injisere markup."""
    page = render_site([make(title='<img src=x onerror="alert(1)">')])
    assert "<img src=x" not in page
    assert "&lt;img" in page


def test_html_in_evidence_is_escaped():
    offer = make()
    offer.dog = DogVerdict(DogStatus.ALLOWED, evidence=["<script>alert(1)</script>"])
    page = render_site([offer])
    assert "<script>alert(1)</script>" not in page


def test_priority_offers_come_first():
    page = render_site([make("2", "Orrfugljakt", prio=False), make("1", "Lirypejakt")])
    assert page.index("Lirypejakt") < page.index("Orrfugljakt")


def test_priority_is_marked():
    assert "prio" in render_site([make()])


def test_status_becomes_filter_chip():
    page = render_site([make(status=DogStatus.ALLOWED), make("2", status=DogStatus.UNCLEAR)])
    assert 'data-value="allowed"' in page
    assert 'data-value="unclear"' in page


def test_absent_status_has_no_chip():
    page = render_site([make(status=DogStatus.ALLOWED)])
    assert 'data-value="not_allowed"' not in page


def test_lottery_shows_deadline():
    offer = make(lottery=True, application_deadline=date(2026, 9, 15))
    assert "15.09.2026" in render_site([offer])
    assert "Trekning" in render_site([offer])


def test_period_is_rendered():
    offer = make(period_start=date(2026, 9, 20), period_end=date(2026, 12, 23))
    page = render_site([offer])
    assert "20.09.26" in page and "23.12.26" in page


def test_empty_list_still_renders():
    page = render_site([])
    assert "<!doctype html>" in page
    assert "Ingen tilbud passer filtrene" in page


def test_dark_mode_tokens_present():
    page = render_site([make()])
    assert "prefers-color-scheme:dark" in page
    assert "[data-theme=dark]" in page


def test_search_index_is_lowercased():
    offer = make(title="Rypejakt NAMSSKOGAN", fylke="Trøndelag")
    page = render_site([offer])
    assert "namsskogan" in page
