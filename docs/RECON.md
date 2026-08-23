# Kalibrering av parseren

Parseren i `inatur/parse.py` er skrevet strukturagnostisk fordi nettstedet ikke
var tilgjengelig fra utviklingsmiljøet. Dette dokumentet beskriver hvordan den
strammes inn mot ekte HTML.

## 1. Finn søke-endepunktet (viktigst)

URL-en brukeren søker med er:

```
https://www.inatur.no/sok/smaavilttilbud?f=[{"felt":"type","sokeord":"smaavilttilbud"}]&ledig=true&p=0
```

`felt`/`sokeord` og `p` (side) tyder sterkt på at frontenden serialiserer
filtre inn i URL-en og sender dem videre til et **JSON-endepunkt**. Finner vi
det, slipper vi HTML-parsing helt - og får rene felter for art, periode, kvote
og pris i stedet for å grave dem ut av fritekst.

Slik finner du det:

1. Åpne søke-URL-en i Chrome.
2. DevTools (F12) → fanen **Network** → filtrer på **Fetch/XHR**.
3. Klikk deg til neste side i søkeresultatet.
4. Se hvilken forespørsel som fyrer av. Noter:
   - full URL og HTTP-metode
   - request headers (spesielt `Content-Type`, evt. API-nøkler)
   - request body hvis det er en POST
   - hele response-bodyen (høyreklikk → Copy → Copy response)

Lagre responsen som `fixtures/raw/search_api.json`.

## 2. Eventuelt: lagre rå HTML

Hvis det ikke finnes noe JSON-endepunkt, faller vi tilbake på HTML:

```bash
inatur discover
```

Dette lagrer `robots.txt` og de to første søkesidene i `fixtures/raw/`.

Sjekk om treffene faktisk ligger i HTML-en:

```bash
grep -c "smaavilttilbud" fixtures/raw/search_p0.html
```

Er den tom for treff, rendres lista med JavaScript, og vi må bruke den
forhåndsinstallerte Chromium-en via Playwright i stedet.

## 3. Stram inn selektorene

Med ekte HTML på plass:

- juster `OFFER_HREF` i `parse.py` til det faktiske lenkemønsteret
- erstatt `_card_for`-heuristikken med den ekte kortselektoren
- legg til uttrekk av `kommune`, `fylke`, `tilbyder`, `period_start`, `period_end`

## 4. Gjør fixturene til regresjonstester

Legg en nedbarbert søkeside i `tests/fixtures/` og skriv en test som fastslår
at `parse_listing` finner riktig antall tilbud med riktige felter. Da fanger vi
opp neste designendring på nettstedet i stedet for å oppdage den ved at
varslene stille slutter å komme.

## 5. Verifiser hundeklassifiseringen mot ekte tekst

Kjør klassifisereren mot ekte vilkårstekster:

```bash
inatur explain https://www.inatur.no/jakt/<slug>
```

Hver formulering som blir feilklassifisert skal legges inn som en ny case i
`tests/test_match.py` før regelen justeres. Testfila er fasiten på hvilke
norske formuleringer verktøyet forstår.
