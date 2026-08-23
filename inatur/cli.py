"""Kommandolinjegrensesnitt.

    inatur check              # kjør, diff mot sist, skriv rapport
    inatur check --dry-run    # kjør uten å oppdatere tilstanden
    inatur explain <url>      # vis hvorfor et tilbud ble klassifisert som det ble
    inatur explain --text "…" # test klassifisereren på en tekstbit
    inatur discover           # lagre rå HTML for kalibrering av parseren
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config
from .fetch import FetchConfig, Fetcher
from .match import classify_dog, find_non_bird_game, find_species
from .models import Offer
from .parse import enrich_from_detail, parse_listing
from .report import render, write
from .store import Store


def _keep(offer: Offer, config: Config) -> bool:
    if offer.dog.status not in config.dog_statuses:
        return False
    if config.priority_only and not offer.is_priority:
        return False
    if config.require_birds and not offer.has_birds:
        return False
    if config.fylker and (offer.fylke or "") not in config.fylker:
        return False
    return True


def cmd_check(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    fetch_config = FetchConfig(
        delay=config.delay,
        max_pages=config.max_pages,
        respect_robots=config.respect_robots,
    )

    offers: list[Offer] = []
    with Fetcher(fetch_config) as fetcher:
        for page, html in fetcher.search_pages():
            found = parse_listing(html)
            print(f"  side {page}: {len(found)} tilbud", file=sys.stderr)
            offers.extend(found)

        if not args.no_detail:
            for offer in offers:
                try:
                    enrich_from_detail(offer, fetcher.detail(offer.url))
                except Exception as exc:  # noqa: BLE001 - én dårlig side stopper ikke kjøringen
                    print(f"  advarsel: {offer.url}: {exc}", file=sys.stderr)

    relevant = [o for o in offers if _keep(o, config)]

    with Store(config.db_path) as store:
        first_run = store.is_empty()
        changes = store.diff(relevant)
        report = render(changes, total_scanned=len(offers), first_run=first_run)
        print(report)

        target = write(report, config.report_path)
        print(f"Rapport lagret: {target}", file=sys.stderr)

        if args.dry_run:
            print("(dry-run: tilstanden er ikke oppdatert)", file=sys.stderr)
        else:
            store.record(relevant, mark_notified=[c.offer.id for c in changes])

    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    if args.text:
        text = args.text
    else:
        with Fetcher() as fetcher:
            text = fetcher.detail(args.url)
        from .parse import enrich_from_detail as _e
        offer = Offer(id="x", url=args.url, title="")
        _e(offer, text)
        text = offer.raw_text

    all_species, priority = find_species(text)
    verdict = classify_dog(text)

    print(f"Fuglearter:     {', '.join(all_species) or '(ingen)'}")
    print(f"Prioritert:     {', '.join(priority) or '(ingen)'}")
    print(f"Annet vilt:     {', '.join(find_non_bird_game(text)) or '(ingen)'}")
    print(f"Hundestatus:    {verdict.status.icon} {verdict.status.label}")
    if verdict.from_date:
        print(f"Hund fra:       {verdict.from_date}")
    if verdict.restrictions:
        print(f"Forbehold:      {', '.join(verdict.restrictions)}")
    print("Begrunnelse:")
    for ev in verdict.evidence or ["(ingen hundeomtale funnet)"]:
        print(f'  - "{ev}"')
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    with Fetcher() as fetcher:
        report = fetcher.discover(args.out)
    print(f"Lagret rådata i {args.out}:")
    for key, value in report.items():
        print(f"  {key}: {value}")
    print("\nNeste steg: se docs/RECON.md for hvordan parseren kalibreres.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inatur",
        description="Finn ledige fuglejaktkort på inatur.no som tillater hund.",
    )
    parser.add_argument("--config", default="config.yaml", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="søk og rapporter endringer")
    p_check.add_argument("--dry-run", action="store_true", help="ikke lagre tilstand")
    p_check.add_argument(
        "--no-detail", action="store_true", help="hopp over detaljsider (raskere)"
    )
    p_check.set_defaults(func=cmd_check)

    p_explain = sub.add_parser("explain", help="vis klassifisering med begrunnelse")
    group = p_explain.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="URL til et tilbud")
    group.add_argument("--text", help="klassifiser en tekstbit direkte")
    p_explain.set_defaults(func=cmd_explain)

    p_discover = sub.add_parser("discover", help="lagre rå HTML for kalibrering")
    p_discover.add_argument("--out", default="fixtures/raw", type=Path)
    p_discover.set_defaults(func=cmd_discover)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
