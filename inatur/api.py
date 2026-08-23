"""Klient mot inatur.no sitt søke-API.

Nettstedet er en React-app: søkesiden er et tomt skall, og treffene hentes fra
`/internal/search`. Det er samme spørrestreng som i adresselinjen, så URL-en du
søker med i nettleseren fungerer direkte mot API-et:

    /internal/search?f=[{"felt":"type","sokeord":"smaavilttilbud"}]&ledig=true&p=0

Responsen er ren JSON med `paginering` og `resultat`. Viktigst er at hvert
treff har et strukturert `arter`-felt (["Lirype","Fjellrype"]) - vi slipper å
lete etter artsnavn i fritekst.

Hundereglene ligger derimot ikke i søkeresultatet. De står i «Jaktregler» på
detaljsiden, som heldigvis er servergenerert HTML.

Vi henter *uten* `ledig=true`. Med filteret forsvinner utsolgte tilbud helt fra
svaret, og da kan vi aldri se at et kort blir ledig igjen - som er nettopp det
vi er ute etter. I stedet henter vi alt og filtrerer på `utsolgt` selv.
"""

from __future__ import annotations

import json
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator, Optional
from urllib.parse import urlencode, urljoin

import httpx

BASE = "https://www.inatur.no"
SEARCH_ENDPOINT = "/internal/search"

# Samme filter som nettstedet selv sender.
DEFAULT_FILTER = [{"felt": "type", "sokeord": "smaavilttilbud"}]

# Sidestørrelsen er låst til 12 på tjenersiden; parametere som
# sideStorrelse/size/antall blir ignorert.
PAGE_SIZE = 12

USER_AGENT = (
    "iNatur-fuglejakt-med-hund/0.1 "
    "(+https://github.com/steinio/iNatur-fuglejakt-med-hund) "
    "personlig varsling om ledige jaktkort"
)


@dataclass
class FetchConfig:
    delay: float = 0.6
    timeout: float = 30.0
    max_pages: int = 200
    respect_robots: bool = True
    retries: int = 3


def _epoch_to_date(value: Any) -> Optional[date]:
    """Datoer kommer som millisekunder siden epoch."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000).date()
    except (ValueError, OSError, TypeError):
        return None


class Client:
    def __init__(self, config: Optional[FetchConfig] = None):
        self.config = config or FetchConfig()
        self.client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8",
            },
            timeout=self.config.timeout,
            follow_redirects=True,
        )
        self._robots: Optional[urllib.robotparser.RobotFileParser] = None
        self._last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.config.delay:
            time.sleep(self.config.delay - elapsed)
        self._last_request = time.monotonic()

    def _allowed(self, url: str) -> bool:
        """robots.txt sperrer /min-side/, /handlekurv/, /booking og /proxy.jsp.
        Verken /internal/search eller /jakt/ er sperret."""
        if not self.config.respect_robots:
            return True
        if self._robots is None:
            self._robots = urllib.robotparser.RobotFileParser()
            try:
                self._robots.parse(
                    self.client.get(urljoin(BASE, "/robots.txt")).text.splitlines()
                )
            except httpx.HTTPError:
                self._robots.parse([])
        return self._robots.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> httpx.Response:
        if not self._allowed(url):
            raise PermissionError(f"robots.txt tillater ikke henting av {url}")

        last_error: Optional[Exception] = None
        for attempt in range(self.config.retries):
            self._throttle()
            try:
                resp = self.client.get(url)
                if resp.status_code == 429:
                    time.sleep(float(resp.headers.get("Retry-After", 2**attempt * 5)))
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.config.retries - 1:
                    time.sleep(2**attempt)
        raise RuntimeError(f"klarte ikke å hente {url}: {last_error}")

    # ------------------------------------------------------------------

    def search_url(
        self, page: int = 0, only_available: bool = False, fylke: str | None = None
    ) -> str:
        filters = list(DEFAULT_FILTER)
        if fylke:
            # Tjenersiden filtrerer på fylke via feltet `fylker`. Det sparer oss
            # for å paginere gjennom alle 1732 tilbud for å finne de ~100 som
            # ligger i vår region.
            filters.append({"felt": "fylker", "sokeord": fylke})
        params = {
            "f": json.dumps(filters, separators=(",", ":"), ensure_ascii=False),
            "p": str(page),
        }
        if only_available:
            params["ledig"] = "true"
        return f"{BASE}{SEARCH_ENDPOINT}?{urlencode(params)}"

    def _search_one(
        self, only_available: bool, fylke: str | None
    ) -> Iterator[dict[str, Any]]:
        for page in range(self.config.max_pages):
            data = self.get(self.search_url(page, only_available, fylke)).json()
            yield from data.get("resultat", [])
            if not data.get("paginering", {}).get("harNesteSide"):
                return

    def search(
        self, only_available: bool = False, fylker: list[str] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Gir hvert søketreff som rå dict.

        Med `fylker` kjøres ett søk per fylke og treffene slås sammen. Flere
        fylkefiltre i samme spørring ANDes av tjeneren og gir null treff, så
        det må gjøres slik.
        """
        if not fylker:
            yield from self._search_one(only_available, None)
            return

        seen: set[str] = set()
        for fylke in fylker:
            for record in self._search_one(only_available, fylke):
                oid = str(record.get("id") or "")
                if oid and oid not in seen:
                    seen.add(oid)
                    yield record

    def total_count(self, only_available: bool = False) -> int:
        data = self.get(self.search_url(0, only_available)).json()
        return data.get("paginering", {}).get("totaltAntallElementer", 0)

    def detail_html(self, url: str) -> str:
        return self.get(urljoin(BASE, url)).text
