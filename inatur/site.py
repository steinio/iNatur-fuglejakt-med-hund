"""Bygger en selvstendig HTML-side over aktuelle tilbud.

Siden publiseres på GitHub Pages av arbeidsflyten, og er ment å åpnes på
mobilen: ett trykk, se hva som er ledig, trykk videre til inatur.no.

Alt ligger i én fil - ingen eksterne stilark, skript eller bilder. Da virker
den like godt fra Pages som fra en lokal fil, og den kan ikke brekke fordi et
CDN er nede.

Kortene rendres i HTML på forhånd; JavaScript brukes bare til å filtrere dem.
Uten JavaScript ser du fortsatt alle tilbudene.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import DogStatus, Offer

STATUS_ORDER = [
    DogStatus.ALLOWED,
    DogStatus.CONDITIONAL,
    DogStatus.UNCLEAR,
    DogStatus.NO_MENTION,
    DogStatus.NOT_ALLOWED,
]

STATUS_TEXT = {
    DogStatus.ALLOWED: "Hund tillatt",
    DogStatus.CONDITIONAL: "Hund med forbehold",
    DogStatus.UNCLEAR: "Usikker",
    DogStatus.NO_MENTION: "Hund ikke nevnt",
    DogStatus.NOT_ALLOWED: "Hund ikke tillatt",
}

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#f6f7f5; --panel:#fff; --ink:#1a1d1a; --muted:#5f6b60; --line:#dde2dc;
  --accent:#2f6b3f; --accent-soft:#e8f1e9;
  --ja:#1f7a3f; --ja-bg:#e6f4ea;
  --forbehold:#8a5a00; --forbehold-bg:#fdf1d9;
  --usikker:#2a5f86; --usikker-bg:#e4eff7;
  --ingen:#5b5f5b; --ingen-bg:#eceeeb;
  --nei:#a32b2b; --nei-bg:#fbe6e6;
  --shadow:0 1px 2px rgba(0,0,0,.05),0 4px 12px rgba(0,0,0,.04);
}
:root:not([data-theme=light]){}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#141815; --panel:#1c211d; --ink:#e8ece7; --muted:#9aa79c; --line:#2c332e;
  --accent:#7fc08f; --accent-soft:#1f2c22;
  --ja:#7fc08f; --ja-bg:#1b2f21;
  --forbehold:#e3b866; --forbehold-bg:#2f2717;
  --usikker:#8ab6d8; --usikker-bg:#1a2731;
  --ingen:#9aa79c; --ingen-bg:#242926;
  --nei:#e08585; --nei-bg:#2f1e1e;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 14px rgba(0,0,0,.25);
}}
[data-theme=dark]{
  --bg:#141815; --panel:#1c211d; --ink:#e8ece7; --muted:#9aa79c; --line:#2c332e;
  --accent:#7fc08f; --accent-soft:#1f2c22;
  --ja:#7fc08f; --ja-bg:#1b2f21;
  --forbehold:#e3b866; --forbehold-bg:#2f2717;
  --usikker:#8ab6d8; --usikker-bg:#1a2731;
  --ingen:#9aa79c; --ingen-bg:#242926;
  --nei:#e08585; --nei-bg:#2f1e1e;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 14px rgba(0,0,0,.25);
}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-text-size-adjust:100%}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px 64px}
header h1{margin:0 0 4px;font-size:1.5rem;letter-spacing:-.01em}
header p{margin:0;color:var(--muted);font-size:.9rem}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 6px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:10px 14px;box-shadow:var(--shadow);min-width:96px}
.stat b{display:block;font-size:1.4rem;line-height:1.1}
.stat span{font-size:.76rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.controls{position:sticky;top:0;z-index:5;background:var(--bg);
  padding:14px 0 10px;border-bottom:1px solid var(--line);margin-bottom:18px}
.row{display:flex;gap:8px;flex-wrap:wrap}
#q{flex:1 1 220px;min-width:0;padding:11px 14px;border:1px solid var(--line);
  border-radius:10px;background:var(--panel);color:var(--ink);font-size:1rem}
#fylke{flex:0 0 auto;padding:11px 34px 11px 14px;border:1px solid var(--line);
  border-radius:10px;background:var(--panel);color:var(--ink);font-size:1rem;
  font-family:inherit;font-weight:600;cursor:pointer;appearance:none;
  background-image:linear-gradient(45deg,transparent 50%,currentColor 50%),
    linear-gradient(135deg,currentColor 50%,transparent 50%);
  background-position:calc(100% - 18px) 51%,calc(100% - 13px) 51%;
  background-size:5px 5px,5px 5px;background-repeat:no-repeat}
#fylke:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
#q::placeholder{color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--muted);
  border-radius:999px;padding:6px 13px;font-size:.83rem;cursor:pointer;
  font-family:inherit;transition:.12s}
.chip:hover{border-color:var(--accent)}
.chip[aria-pressed=true]{background:var(--accent-soft);border-color:var(--accent);
  color:var(--accent);font-weight:600}
.count{color:var(--muted);font-size:.85rem;margin:0 0 14px}
.cards{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--line);
  border-radius:12px;padding:16px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:9px}
.card.prio{border-left-color:var(--accent)}
/* Må stå her: [hidden] fra nettleserens stilark har samme spesifisitet som
   .card, og vårt eget stilark kommer sist - uten denne blir .card{display:flex}
   stående og filtrerte kort vises likevel. */
.card[hidden]{display:none}
.card h2{margin:0;font-size:1.02rem;line-height:1.35;letter-spacing:-.005em}
.badge{align-self:flex-start;font-size:.76rem;font-weight:600;padding:3px 9px;
  border-radius:6px;letter-spacing:.01em}
.badge.allowed{color:var(--ja);background:var(--ja-bg)}
.badge.conditional{color:var(--forbehold);background:var(--forbehold-bg)}
.badge.unclear{color:var(--usikker);background:var(--usikker-bg)}
.badge.no_mention{color:var(--ingen);background:var(--ingen-bg)}
.badge.not_allowed{color:var(--nei);background:var(--nei-bg)}
.arter{display:flex;flex-wrap:wrap;gap:5px}
.art{font-size:.75rem;padding:2px 8px;border-radius:5px;background:var(--ingen-bg);color:var(--muted)}
.art.p{background:var(--accent-soft);color:var(--accent);font-weight:600}
blockquote{margin:0;padding:9px 12px;border-left:2px solid var(--line);
  background:var(--bg);border-radius:0 7px 7px 0;font-size:.85rem;color:var(--muted);
  font-style:italic;overflow-wrap:anywhere}
dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:.85rem}
dt{color:var(--muted)}
dd{margin:0}
.go{margin-top:auto;padding-top:4px}
.go a{display:inline-block;color:var(--accent);text-decoration:none;font-weight:600;font-size:.88rem}
.go a:hover{text-decoration:underline}
.empty{padding:40px 16px;text-align:center;color:var(--muted)}
footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);
  color:var(--muted);font-size:.83rem}
footer a{color:var(--accent)}
@media(max-width:520px){.cards{grid-template-columns:1fr}.wrap{padding:16px 12px 48px}}
"""

JS = """
(function(){
  var q=document.getElementById('q'),
      chips=Array.prototype.slice.call(document.querySelectorAll('.chip')),
      cards=Array.prototype.slice.call(document.querySelectorAll('.card')),
      fy=document.getElementById('fylke'),
      out=document.getElementById('count'),
      none=document.getElementById('empty');
  function active(group){
    return chips.filter(function(c){
      return c.dataset.group===group && c.getAttribute('aria-pressed')==='true';
    }).map(function(c){return c.dataset.value;});
  }
  function apply(){
    var text=(q.value||'').toLowerCase().trim(),
        st=active('status'), prio=active('prio').length>0,
        fylke=fy?fy.value:'', n=0;
    cards.forEach(function(c){
      var ok=true;
      // Et tilbud kan ligge i flere fylker (grensetilfeller) - da holder
      // det at ett av dem er det valgte.
      if(fylke && (c.dataset.fylker||'').split('|').indexOf(fylke)<0) ok=false;
      if(ok && st.length && st.indexOf(c.dataset.status)<0) ok=false;
      if(ok && prio && c.dataset.prio!=='1') ok=false;
      if(ok && text && c.dataset.search.indexOf(text)<0) ok=false;
      c.hidden=!ok; if(ok) n++;
    });
    out.textContent=n+' tilbud'+(fylke?' i '+fylke:'');
    none.hidden=n>0;
  }
  chips.forEach(function(c){
    c.addEventListener('click',function(){
      c.setAttribute('aria-pressed', c.getAttribute('aria-pressed')==='true'?'false':'true');
      apply();
    });
  });
  if(fy){
    // Husk valget til neste besøk. Nettleseren kan nekte oss lagring
    // (privat vindu, blokkerte informasjonskapsler), så alt pakkes inn.
    try{
      var saved=localStorage.getItem('inatur.fylke');
      if(saved!==null){
        for(var i=0;i<fy.options.length;i++){
          if(fy.options[i].value===saved){ fy.value=saved; break; }
        }
      }
    }catch(e){}
    fy.addEventListener('change',function(){
      try{ localStorage.setItem('inatur.fylke', fy.value); }catch(e){}
      apply();
    });
  }
  q.addEventListener('input',apply);
  apply();
})();
"""


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _card(offer: Offer) -> str:
    status = offer.dog.status
    searchable = " ".join(
        [offer.title, offer.fylke or "", offer.kommune or "", offer.tilbyder or ""]
        + offer.species
    ).lower()

    arter = "".join(
        f'<span class="art{" p" if a in offer.priority_species else ""}">{_esc(a)}</span>'
        for a in offer.species
    )

    badge = STATUS_TEXT[status]
    if offer.dog.from_date:
        badge += f" fra {_esc(offer.dog.from_date)}"

    quote = ""
    if offer.dog.evidence:
        first = offer.dog.evidence[0]
        if len(first) > 190:
            first = first[:187] + "…"
        quote = f"<blockquote>{_esc(first)}</blockquote>"

    rows = []
    where = ", ".join(x for x in (offer.kommune, offer.fylke) if x)
    if where:
        rows.append(f"<dt>Sted</dt><dd>{_esc(where)}</dd>")
    if offer.period_start and offer.period_end:
        rows.append(
            f"<dt>Periode</dt><dd>{offer.period_start:%d.%m.%y}–{offer.period_end:%d.%m.%y}</dd>"
        )
    if offer.price:
        rows.append(f"<dt>Pris</dt><dd>{_esc(offer.price)}</dd>")
    if offer.lottery:
        frist = (
            f"{offer.application_deadline:%d.%m.%Y}"
            if offer.application_deadline
            else "ukjent"
        )
        rows.append(f"<dt>Trekning</dt><dd>søknadsfrist {frist}</dd>")
    elif offer.sales_start:
        rows.append(f"<dt>Salgsstart</dt><dd>{offer.sales_start:%d.%m.%Y}</dd>")
    if offer.tilbyder:
        rows.append(f"<dt>Tilbyder</dt><dd>{_esc(offer.tilbyder)}</dd>")

    fylker = "|".join(offer.fylker)

    return f"""<article class="card{' prio' if offer.is_priority else ''}"
 data-status="{status.value}" data-prio="{1 if offer.is_priority else 0}"
 data-fylker="{_esc(fylker)}" data-search="{_esc(searchable)}">
<span class="badge {status.value}">{_esc(badge)}</span>
<h2>{'★ ' if offer.is_priority else ''}{_esc(offer.title)}</h2>
<div class="arter">{arter}</div>
{quote}
<dl>{''.join(rows)}</dl>
<div class="go"><a href="{_esc(offer.full_url)}" target="_blank" rel="noopener">Åpne på inatur.no →</a></div>
</article>"""


def render_site(
    offers: list[Offer],
    generated: datetime | None = None,
    default_fylke: str = "Vestland",
) -> str:
    """Bygger hele siden. `offers` er allerede filtrert av konfigurasjonen.

    Alle hentede fylker legges i siden, og nedtrekksmenyen velger ett av dem.
    Da kan du bytte fylke uten at noe må kjøres på nytt.
    """
    generated = generated or datetime.now(timezone.utc).astimezone()

    ranked = sorted(
        offers,
        key=lambda o: (
            not o.is_priority,
            STATUS_ORDER.index(o.dog.status),
            o.title.lower(),
        ),
    )

    fylke_counts: dict[str, int] = {}
    for offer in ranked:
        for f in offer.fylker:
            fylke_counts[f] = fylke_counts.get(f, 0) + 1

    # Er standardfylket tomt for tilbud, ville siden sett ødelagt ut ved
    # åpning. Da faller vi tilbake på det fylket som har flest.
    selected = default_fylke if fylke_counts.get(default_fylke) else ""
    if not selected and fylke_counts:
        selected = max(fylke_counts, key=lambda f: fylke_counts[f])

    fylke_html = "".join(
        [
            f'<option value=""{" selected" if not selected else ""}>'
            f"Hele landet ({len(ranked)})</option>"
        ]
        + [
            f'<option value="{_esc(f)}"{" selected" if f == selected else ""}>'
            f"{_esc(f)} ({n})</option>"
            for f, n in sorted(fylke_counts.items())
        ]
    )

    counts = {s: sum(1 for o in ranked if o.dog.status is s) for s in STATUS_ORDER}
    priority = sum(1 for o in ranked if o.is_priority)

    # Tallene gjelder fylket som vises ved åpning.
    shown = [o for o in ranked if not selected or selected in o.fylker]
    stats = [
        ("Tilbud", len(shown)),
        ("Li-/fjellrype", sum(1 for o in shown if o.is_priority)),
        ("Hund tillatt", sum(1 for o in shown if o.dog.status is DogStatus.ALLOWED)),
        ("Med forbehold", sum(1 for o in shown if o.dog.status is DogStatus.CONDITIONAL)),
    ]
    stat_html = "".join(
        f"<div class='stat'><b>{n}</b><span>{_esc(label)}</span></div>" for label, n in stats
    )

    chips = [("prio", "1", "★ Kun li-/fjellrype")]
    chips += [
        (
            "status",
            s.value,
            f"{STATUS_TEXT[s]} ({counts[s]})",
        )
        for s in STATUS_ORDER
        if counts[s]
    ]
    chip_html = "".join(
        f'<button class="chip" data-group="{g}" data-value="{_esc(v)}" '
        f'aria-pressed="false" type="button">{_esc(label)}</button>'
        for g, v, label in chips
    )

    cards = "\n".join(_card(o) for o in ranked)

    return f"""<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Fuglejakt med hund – iNatur</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Fuglejakt med hund</h1>
  <p>Ledige småvilttilbud på inatur.no · oppdatert {generated:%d.%m.%Y kl. %H:%M}</p>
</header>

<div class="stats">{stat_html}</div>

<div class="controls">
  <div class="row">
    <select id="fylke" aria-label="Velg fylke">{fylke_html}</select>
    <input id="q" type="search" placeholder="Søk på sted, tilbyder eller art…"
           autocomplete="off" aria-label="Søk">
  </div>
  <div class="chips">{chip_html}</div>
</div>

<p class="count" id="count"></p>
<div class="cards">
{cards}
</div>
<p class="empty" id="empty" hidden>Ingen tilbud passer filtrene.</p>

<footer>
  <p><strong>Hundestatus</strong> er utledet av vilkårsteksten på hvert tilbud.
  Sitatet på kortet er setningen som avgjorde – les den, og sjekk alltid på
  inatur.no før du kjøper.</p>
  <p>«Usikker» og «hund ikke nevnt» vises med vilje: å gå glipp av et lirypekort
  koster mer enn et varsel for mye.</p>
  <p>Bygget av <a href="https://github.com/steinio/iNatur-fuglejakt-med-hund">iNatur-fuglejakt-med-hund</a>.
  Data fra <a href="https://www.inatur.no">inatur.no</a>.</p>
</footer>
</div>
<script>{JS}</script>
</body>
</html>"""


def write_site(
    offers: list[Offer],
    path: str | Path = "site/index.html",
    default_fylke: str = "Vestland",
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_site(offers, default_fylke=default_fylke), encoding="utf-8")
    return target
