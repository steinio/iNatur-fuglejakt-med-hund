# inatur.no – hvordan datene hentes

Notater fra kartleggingen av nettstedet, slik at neste person (eller neste
kjøring om et år) slipper å finne ut av dette på nytt.

## Søkesiden er et tomt skall

`/sok/smaavilttilbud` er en React-app. HTML-en er 3,5 kB og inneholder bare
`<main id="webshop"></main>` – ingen treff. Å parse den siden gir ingenting.

## Søke-API-et

Endepunktet ble funnet ved å søke etter API-stier i JS-bunten:

```bash
curl -s https://www.inatur.no/resources-build/javascripts/webshop.<hash>.js \
  | grep -oE '"/[a-zA-Z0-9_/.-]{3,60}"' | sort -u | grep -i 'api\|sok\|search'
```

Kallet i bunten er `Z.get("/internal/search".concat(e))` – altså GET med
spørrestrengen lagt rett på. **Det er samme spørrestreng som i adresselinjen**,
så URL-en du søker med i nettleseren virker direkte mot API-et:

```
GET https://www.inatur.no/internal/search?f=[{"felt":"type","sokeord":"smaavilttilbud"}]&ledig=true&p=0
```

Svaret er JSON:

```json
{
  "paginering": { "side": 0, "sideStørrelse": 12, "harNesteSide": true,
                  "totaltAntallSider": 145, "totaltAntallElementer": 1732 },
  "resultat": [ { "id": "...", "tittel": "...", "arter": ["Lirype","Fjellrype"], ... } ]
}
```

### Felter vi bruker

| Felt | Innhold |
|---|---|
| `id` | Stabil id – overlever tittelendringer |
| `url` | `/jakt/<id>/<slug>` |
| `arter` | **Strukturert artsliste**, f.eks. `["Lirype","Fjellrype"]` |
| `utsolgt`, `utlopt` | Tilgjengelighet |
| `harTrekning` | Trekning i stedet for direktesalg |
| `fra`, `til`, `salgsstart`, `soknadsfrist` | Millisekunder siden epoch |
| `fraPris` | Laveste pris |
| `fylkerFormatert`, `kommunerFormatert`, `tilbydernavn` | Sted og tilbyder |
| `kortBeskrivelse` | Ingress |

`arter` er den store gevinsten: vi slipper å lete etter artsnavn i fritekst.

### Sidestørrelsen er låst

12 per side. `sideStorrelse`, `size`, `antall` og `s` blir alle ignorert.
1732 tilbud = 145 sider.

### Hent uten `ledig=true`

| Spørring | Antall |
|---|---|
| `ledig=true` | 948 |
| uten filter | 1732 |

Med `ledig=true` forsvinner utsolgte tilbud **helt** fra svaret. Da kan vi
aldri se at et kort går fra utsolgt til ledig – som er nettopp det vi er ute
etter. Derfor henter vi alt og filtrerer på `utsolgt` selv.

## Hundereglene ligger på detaljsiden

Søketreffet sier ingenting om hund. Detaljsiden (`/jakt/<id>/<slug>`) er
derimot servergenerert HTML, og har en **«Jaktregler»**-seksjon:

> JAKTKORT SKAL MEDBRINGES UNDER JAKTA! … Jaktbare arter er lirype og
> fjellrype, orrfugl er fredet. **Jakt med hund med gyldig bufesertifikat
> tillatt, 1 hund pr. jeger.**

Andre relevante overskrifter: «Mer detaljert beskrivelse», «Jaktkvoter»,
«Viktige datoer». `rules_text()` starter ved første kjente overskrift og faller
tilbake på hele teksten hvis ingen kjennes igjen.

## robots.txt

```
Disallow: /min-side/  /handlekurv/  /proxy.jsp  /booking
```

Verken `/internal/search` eller `/jakt/` er sperret. Vi respekterer likevel
robots.txt i klienten, og venter mellom hver forespørsel.

## Artsverdier

Full verdiliste for `arter`, talt opp over alle 948 ledige småvilttilbud:

**Fugl:** Lirype (280), Fjellrype (223), Tiur (282), Røy (232), Orrfugl (215),
Orrhane (93), Orrhøne (83), Jerpe (212), And (152), Ringdue (101), Gjess (97),
Vadefugler (30), Skarv (26), Spurvefugler (21)

**Ikke fugl:** Hare (390), Rødrev (339), Mår (242), Rådyr (237), Røyskatt (209),
Grevling (178), Villsvin (18), Bever (13), Gaupe (8), Sel (1)

**Upresist:** Småvilt (307), Andre (47) – regnes som mulige fugletilbud.

Ukjente verdier regnes også som mulig fugl, slik at et nytt artsnavn ikke
stille filtrerer bort tilbud.

## Kalibrering av hundeklassifisereren

`inatur stats` kjører klassifisereren mot ekte detaljsider og viser fordelingen
pluss de uklare tilfellene. Utviklingen under kalibreringen:

| | Før | Etter |
|---|---|---|
| uklar | 33 % | **2 %** |
| klart ja | 12 % | 18 % |
| betinget ja | 18 % | 40 % |

Det som ga mest:

1. **Nynorsk.** `ikkje`, `utan`, `tillete`, `lov`, `løyve`. Brukes i store
   jaktområder (Aurland, Suldal, Voss) og sto for en stor del av de uklare.
2. **«med og uten hund»** i titler – betyr at *begge* varianter tilbys, men
   traff «uten hund»-regelen og ga falskt nei.
3. **Krav til hunden** («Jakthund må dokumentert være sauerein») forutsetter at
   hund er lov.
4. **«ikkje lov … før 1. oktober»** er et *ja fra 1. oktober*, ikke et nei.
5. **Uttrykket «jakt med hund»** brukt som beskrivelse av tilbudet.

Hver av dem ligger som et eget testtilfelle i `tests/test_match.py`, med den
ekte setningen som utløste det.

Når du finner en feilklassifisering: legg setningen inn som en ny test
**først**, og juster regelen etterpå.
