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

from .api import Client, FetchConfig
from .config import Config
from .match import classify_dog, find_non_bird_game, find_species
from .models import Offer
from .parse import detail_text, enrich_from_detail, offer_from_api, rules_text
from .report import render, write
from .site import write_site
from .store import Store


def _prefilter(offer: Offer, config: Config) -> bool:
    """Billige filtre som kan avgjøres fra søketreffet alene.

    Dette avgjør hvor mange detaljsider vi må hente, så det er her vi sparer
    mest tid - og belaster nettstedet minst.
    """
    if config.require_birds and not offer.has_birds:
        return False
    if config.priority_only and not offer.is_priority:
        return False
    if config.fylker and not any(f in (offer.fylke or "") for f in config.fylker):
        return False
    if config.skip_lottery and offer.lottery:
        return False
    return True


def _keep(offer: Offer, config: Config) -> bool:
    """Endelig filter, etter at hundereglene er lest fra detaljsiden."""
    if not _prefilter(offer, config):
        return False
    if offer.dog.status not in config.dog_statuses:
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
    with Client(fetch_config) as client:
        # Hentes uten ledig-filter: med det forsvinner utsolgte tilbud helt, og
        # da kan vi aldri oppdage at et kort blir ledig igjen.
        for record in client.search(only_available=False):
            offers.append(offer_from_api(record))
        print(f"  {len(offers)} tilbud hentet fra API-et", file=sys.stderr)

        # Detaljsidene er dyre, så vi henter dem kun for tilbud som allerede
        # har passert art- og tilgjengelighetsfiltrene.
        candidates = [o for o in offers if _prefilter(o, config)]
        print(f"  {len(candidates)} aktuelle - henter vilkår", file=sys.stderr)

        if not args.no_detail:
            for i, offer in enumerate(candidates, 1):
                try:
                    enrich_from_detail(offer, client.detail_html(offer.url))
                except Exception as exc:  # noqa: BLE001 - én dårlig side stopper ikke kjøringen
                    print(f"  advarsel: {offer.url}: {exc}", file=sys.stderr)
                if i % 25 == 0:
                    print(f"    {i}/{len(candidates)}", file=sys.stderr)

    relevant = [o for o in candidates if _keep(o, config)]

    with Store(config.db_path) as store:
        first_run = store.is_empty()
        changes = store.diff(relevant)
        report = render(changes, total_scanned=len(offers), first_run=first_run)
        print(report)

        target = write(report, config.report_path)
        print(f"Rapport lagret: {target}", file=sys.stderr)

        # Nettsiden viser alt som er aktuelt nå - ikke bare det som er nytt.
        page = write_site(relevant, config.site_path)
        print(f"Nettside lagret: {page}", file=sys.stderr)

        if args.dry_run:
            print("(dry-run: tilstanden er ikke oppdatert)", file=sys.stderr)
        else:
            store.record(relevant, mark_notified=[c.offer.id for c in changes])

    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    title = args.title or ""
    if args.text:
        text = args.text
    else:
        with Client() as client:
            text = rules_text(detail_text(client.detail_html(args.url)))

    all_species, priority = find_species(text)
    verdict = classify_dog(text, title=title)

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


def cmd_stats(args: argparse.Namespace) -> int:
    """Måler hvordan klassifisereren treffer på ekte tilbud.

    Brukes til kalibrering: en høy andel 'uklar' betyr at det finnes
    formuleringer vi ennå ikke forstår. De hører hjemme som nye testtilfeller.
    """
    import collections

    config = Config.load(args.config)
    counts: collections.Counter = collections.Counter()
    unclear: list[tuple[str, str]] = []

    with Client() as client:
        offers = [offer_from_api(r) for r in client.search()]
        candidates = [o for o in offers if _prefilter(o, config)][: args.limit]
        print(f"{len(offers)} tilbud, vurderer {len(candidates)} detaljsider\n",
              file=sys.stderr)

        for offer in candidates:
            try:
                enrich_from_detail(offer, client.detail_html(offer.url))
            except Exception:  # noqa: BLE001
                counts["feil"] += 1
                continue
            counts[offer.dog.status.value] += 1
            if offer.dog.status.value == "unclear" and len(unclear) < 10:
                unclear.append(
                    (offer.title[:40], offer.dog.evidence[0][:110] if offer.dog.evidence else "-")
                )

    total = sum(counts.values())
    print("=== HUNDESTATUS ===")
    for status, n in counts.most_common():
        print(f"{n:5d}  {status:<12} {n / max(total, 1):5.0%}")

    interesting = total - counts["not_allowed"] - counts["feil"]
    print(f"\n{interesting}/{total} tilbud er verdt å se på")

    if unclear:
        print("\n=== UKLARE (kandidater til nye testtilfeller) ===")
        for title, evidence in unclear:
            print(f'  {title}\n    "{evidence}"')
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
    p_explain.add_argument("--title", help="tittel, brukes som ekstra signal")
    p_explain.set_defaults(func=cmd_explain)

    p_stats = sub.add_parser("stats", help="fordeling av hundestatus over alle tilbud")
    p_stats.add_argument("--limit", type=int, default=80, help="antall detaljsider")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
