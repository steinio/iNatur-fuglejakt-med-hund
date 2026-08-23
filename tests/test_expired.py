"""Tester for utgåtte og utsolgte tilbud.

Skillet er viktig: utsolgt kan bli ledig igjen (restsalg, avbestillinger) og
er nettopp det verktøyet skal fange opp. Utgått kommer aldri tilbake.

I det ekte datasettet var 779 av 1733 tilbud utsolgte, utløpte eller ferdige -
noen med jaktperiode helt tilbake til 2014.
"""

from datetime import date, timedelta

import pytest

from inatur.cli import _keep, _prefilter
from inatur.config import Config
from inatur.models import DogStatus, DogVerdict, Offer

I_GAR = date.today() - timedelta(days=1)
I_MORGEN = date.today() + timedelta(days=1)


def make(**kw):
    base = dict(
        id="1",
        url="/jakt/1/x",
        title="Rypejakt",
        species=["Lirype"],
        priority_species=["Lirype"],
        fylker=["Vestland"],
        dog=DogVerdict(DogStatus.ALLOWED, evidence=["Hund tillatt"]),
        classified=True,
    )
    base.update(kw)
    return Offer(**base)


@pytest.fixture
def config():
    return Config(fylker=[])


# ------------------------------------------------------------- utgått


def test_flagged_expired_is_expired():
    assert make(flagged_expired=True).expired


def test_past_period_is_expired_even_without_flag():
    """673 hadde flagget, 387 hadde periode i fortida - mengdene overlapper
    ikke, så begge må sjekkes."""
    offer = make(flagged_expired=False, period_end=I_GAR)
    assert offer.expired


def test_future_period_is_not_expired():
    assert not make(period_end=I_MORGEN).expired


def test_period_ending_today_is_not_expired():
    """Siste jaktdag teller fortsatt."""
    assert not make(period_end=date.today()).expired


def test_offer_without_period_is_not_expired():
    assert not make(period_end=None).expired


def test_expired_offers_are_dropped_before_fetching_details(config):
    """Filtreres i prefilter, ikke i keep - da slipper vi ~700 forespørsler."""
    assert not _prefilter(make(flagged_expired=True), config)
    assert not _prefilter(make(period_end=I_GAR), config)
    assert _prefilter(make(period_end=I_MORGEN), config)


# ------------------------------------------------------------ utsolgt


def test_sold_out_is_not_shown(config):
    assert not _keep(make(available=False), config)


def test_sold_out_is_still_followed(config):
    """Utsolgte må gjennom prefilter, ellers hentes de aldri og vi kan aldri
    se at de blir ledige igjen."""
    assert _prefilter(make(available=False), config)


def test_available_offer_is_shown(config):
    assert _keep(make(available=True), config)


def test_sold_out_and_expired_are_different_things():
    offer = make(available=False, period_end=I_MORGEN)
    assert not offer.available
    assert not offer.expired
