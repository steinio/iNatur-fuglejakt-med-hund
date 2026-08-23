"""HTTP-klient mot inatur.no.

Vi opptrer høflig: én forespørsel om gangen, pause mellom hver, ærlig
User-Agent med kontaktinfo, og respekt for robots.txt. Et kvartersvis søk på en
offentlig søkeside er udramatisk - å hamre løs på den er det ikke, og en
IP-blokkering setter en effektiv stopper for hele prosjektet.

MERK: Søke-endepunktet er ikke kalibrert ennå. Kjør `inatur discover` for å
lagre rå HTML/JSON fra det ekte nettstedet - se docs/RECON.md.
"""

from __future__ import annotations

import json
import time
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlencode, urljoin

import httpx

BASE = "https://www.inatur.no"
SEARCH_PATH = "/sok/smaavilttilbud"

# Filteret nettstedet selv bruker: felt=type, sokeord=smaavilttilbud
DEFAULT_FILTER = [{"felt": "type", "sokeord": "smaavilttilbud"}]

USER_AGENT = (
    "iNatur-fuglejakt-med-hund/0.1 "
    "(+https://github.com/steinio/iNatur-fuglejakt-med-hund) "
    "personlig varsling om ledige jaktkort"
)


@dataclass
class FetchConfig:
    delay: float = 1.5  # sekunder mellom forespørsler
    timeout: float = 30.0
    max_pages: int = 40
    respect_robots: bool = True
    retries: int = 3


class Fetcher:
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

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.config.delay:
            time.sleep(self.config.delay - elapsed)
        self._last_request = time.monotonic()

    def _check_robots(self, url: str) -> bool:
        if not self.config.respect_robots:
            return True
        if self._robots is None:
            self._robots = urllib.robotparser.RobotFileParser()
            try:
                resp = self.client.get(urljoin(BASE, "/robots.txt"))
                self._robots.parse(resp.text.splitlines())
            except httpx.HTTPError:
                # Ingen robots.txt tilgjengelig - vi fortsetter forsiktig.
                self._robots.parse([])
        return self._robots.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> httpx.Response:
        """Henter en URL med throttling og eksponentiell backoff."""
        if not self._check_robots(url):
            raise PermissionError(f"robots.txt tillater ikke henting av {url}")

        last_error: Optional[Exception] = None
        for attempt in range(self.config.retries):
            self._throttle()
            try:
                resp = self.client.get(url)
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 2**attempt * 5))
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.config.retries - 1:
                    time.sleep(2**attempt)
        raise RuntimeError(f"klarte ikke å hente {url}: {last_error}")

    # ------------------------------------------------------------------

    def search_url(self, page: int = 0, only_available: bool = True) -> str:
        params = {
            "f": json.dumps(DEFAULT_FILTER, separators=(",", ":"), ensure_ascii=False),
            "p": str(page),
        }
        if only_available:
            params["ledig"] = "true"
        return f"{BASE}{SEARCH_PATH}?{urlencode(params)}"

    def search_pages(self, only_available: bool = True) -> Iterator[tuple[int, str]]:
        """Gir (sidenummer, HTML) for hver søkeside til vi går tom for treff."""
        from .parse import listing_looks_empty

        for page in range(self.config.max_pages):
            url = self.search_url(page, only_available)
            html = self.get(url).text
            if listing_looks_empty(html):
                return
            yield page, html

    def detail(self, url: str) -> str:
        return self.get(urljoin(BASE, url)).text

    # ------------------------------------------------------------------

    def discover(self, out_dir: str | Path = "fixtures/raw") -> dict[str, Any]:
        """Lagrer rå responser til kalibrering av parseren.

        Kjør denne først når www.inatur.no er tilgjengelig. Resultatet er
        utgangspunktet for å skrive presise selektorer - og for testfixtures.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        report: dict[str, Any] = {}

        robots = self.get(urljoin(BASE, "/robots.txt"))
        (out / "robots.txt").write_text(robots.text, encoding="utf-8")
        report["robots"] = robots.status_code

        for page in (0, 1):
            url = self.search_url(page)
            resp = self.get(url)
            target = out / f"search_p{page}.html"
            target.write_text(resp.text, encoding="utf-8")
            report[f"search_p{page}"] = {
                "url": url,
                "status": resp.status_code,
                "bytes": len(resp.text),
                "content_type": resp.headers.get("content-type"),
            }

        (out / "discover.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return report
