# iNatur – fuglejakt med hund

Overvåker [inatur.no](https://www.inatur.no) og varsler om **ledige
småvilttilbud på fugl som tillater bruk av hund**. Lirype og fjellrype
prioriteres, men alle fuglearter tas med.

Bakgrunnen er enkel: ledige kort dukker opp uregelmessig – restsalg,
avbestillinger, nye tilbud – og forsvinner fort. Å sjekke søkesiden manuelt
flere ganger om dagen er ikke særlig gøy.

## Status

Ferdig og kalibrert mot det ekte nettstedet. 82 tester, hvorav flere kjører mot
lagrede svar fra inatur.no.

Klassifisereren er målt mot 120 ekte tilbud: **2 %** havner som «uklar», mot
33 % før kalibreringen. Se [`docs/API.md`](docs/API.md) for hva som ga mest.

## Kom i gang

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

inatur check --dry-run     # kjør uten å lagre tilstand
pytest -q                  # kjør testene
```

## Hvordan det virker

**1. Søk.** Søkesiden er en React-app uten innhold i HTML-en, men den henter
treffene fra et JSON-endepunkt, `/internal/search`, med samme spørrestreng som
står i adresselinjen. Derfra får vi strukturerte felter – blant annet `arter`
som `["Lirype","Fjellrype"]`, så artsfiltreringen er eksakt og ikke gjetting.

Vi henter *uten* `ledig=true`-filteret: med det forsvinner utsolgte tilbud helt
fra svaret, og da kan vi aldri oppdage at et kort blir ledig igjen.

Hundereglene står derimot ikke i søketreffet. De ligger i «Jaktregler» på
detaljsiden, som heldigvis er servergenerert HTML.

**2. Klassifiser.** Den vanskelige delen. Vilkårene er fritekst skrevet av
hundrevis av grunneiere og fjellstyrer, og formuleringene spriker:

```
"Jakt med hund er tillatt fra 20.09"          → betinget ja, fra 20.09
"Det er ikke tillatt å bruke hund"            → nei
"Ikkje tillete med hund"                      → nei      (nynorsk)
"ikkje lov å jakta med hund før 1. oktober"   → ja fra 1. oktober
"SMÅVILTJAKT med og uten hund"                → ja       (begge varianter)
"Jakthund må dokumentert være sauerein"       → betinget ja
"Kun stående fuglehund"                       → betinget ja
```

Nynorsk viste seg å være avgjørende: `ikkje`, `utan`, `tillete` og `lov` brukes
i store jaktområder som Aurland, Suldal og Voss, og sto for en stor del av
feilklassifiseringene før kalibreringen.

Nøkkelen er **negasjonshåndtering**: «hund» + «tillatt» i samme setning betyr
ingenting hvis det står «ikke» rett foran. Hver setning vurderes derfor for seg,
med et vindu rundt tillatelsesordet. Resultatet er én av fem statuser – og
alltid med *setningen som avgjorde* vedlagt, så du kan overprøve maskina.

Vi varsler bevisst også ved `unclear` og `no_mention`. Å gå glipp av et
lirypekort koster mer enn et varsel for mye.

**3. Utgått vs. utsolgt.** To ting som ser like ut, men ikke er det:

- **Utgått** – jaktperioden er over. Kommer aldri tilbake, og filtreres bort
  før detaljsidene hentes.
- **Utsolgt** – kan bli ledig igjen ved restsalg eller avbestilling. Vises
  ikke, men følges videre; det er nettopp dette verktøyet skal fange opp.

Vi stoler ikke på inatur sitt `utløpt`-flagg alene. Av 1733 tilbud hadde 673
flagget og 387 en jaktperiode som var over – og ingen av mengdene rommer den
andre. Noen tilbud lå der med jaktperiode helt tilbake til **2014**. Til sammen
var 779 av 1733 ikke aktuelle.

**4. Diff.** Alt lagres i SQLite, slik at du kun varsles om det som faktisk er
nytt:

- **NYTT** – aldri sett før
- **LEDIG IGJEN** – var utsolgt, er ledig nå *(den viktigste – restsalg og avbestillinger)*
- **ENDREDE VILKÅR** – vilkårsteksten er endret, f.eks. hundereglene

## Kommandoer

```bash
inatur check                  # søk, diff mot sist, skriv rapport
inatur check --dry-run        # samme, men uten å oppdatere tilstanden
inatur check --no-detail      # hopp over detaljsider (raskt, mindre presist)

inatur explain --text "Jakt med hund er tillatt fra 20.09"
inatur explain /jakt/<id>/<slug>

inatur stats                  # mål klassifisereren mot ekte tilbud
```

`explain` viser *hvorfor* noe ble klassifisert som det ble – nyttig når en
formulering blir feiltolket:

```
$ inatur explain --text "Jakt med hund er tillatt fra 20.09. Gjelder lirype."
Fuglearter:     lirype
Prioritert:     lirype
Hundestatus:    [JA*] HUND TILLATT MED FORBEHOLD
Hund fra:       20.09
Begrunnelse:
  - "Jakt med hund er tillatt fra 20 09"
```

## Konfigurasjon

Alt styres fra [`config.yaml`](config.yaml): hvilke hundestatuser som
rapporteres, om ikke-fugletilbud skal filtreres bort, kun li-/fjellrype,
om trekningstilbud skal hoppes over, prisgrense, fylker, og hvor forsiktig
scrapingen skal være.

**Fylke velges på selve siden.** Nedtrekksmenyen viser ett fylke om gangen,
med `Vestland` som standard (`site.default_fylke`). Alle hentede fylker ligger
allerede i siden, så du bytter uten at noe kjøres på nytt, og valget huskes til
neste besøk. Tilbud som krysser fylkesgrensa dukker opp under begge.

`filters.fylker` styrer hva som *hentes*. Tom liste = hele landet, som gir alle
fylker i menyen. Snevre den inn til f.eks. `["Vestland"]` for raskere kjøringer
og en kortere meny.

## Hvorfor kjøringene er raske

To ting gjør at en kjøring tar sekunder i stedet for et kvarter:

**Fylkefilter på tjenersiden.** API-et støtter `{"felt":"fylker"}`, så vi
henter bare tilbudene i regionen i stedet for å paginere gjennom alle 1732.

**Mellomlagrede vurderinger.** Søketreffet har `sistOppdatert`. Er tidsstempelet
uendret siden forrige kjøring, gjenbruker vi hundevurderingen og henter aldri
detaljsiden. Alle vurderte tilbud lagres – også de vi filtrerer bort – ellers
ville «hund ikke tillatt»-tilbudene blitt hentet på nytt hver eneste gang.

**Tak på detaljsider per kjøring.** Hele landet har ~1200 aktuelle tilbud, og
å hente alle på én gang tok over ti minutter. Nå hentes maks
`max_details_per_run` (250) per kjøring, og resten tas av de neste. Siden vokser
altså over den første timen i stedet for å låse én lang kjøring.

Et tilbud vises ikke før vilkårene faktisk er lest. Uten detaljsiden har vi bare
en gjetning fra tittelen, og den er ikke god nok til å vise fram som en
hundekonklusjon – den lagres derfor heller ikke i mellomlageret.

| | Tid |
|---|---|
| Hele landet, ett fylke konfigurert | ~90 s |
| Hele landet, alt hentet | ~200 s |
| Ingenting endret | **8–73 s** |

Til sammenligning brukte den første versjonen ~1150 forespørsler og nær 14
minutter – hvert kvarter. Det var verken hensynsfullt mot inatur.no eller
holdbart innenfor Actions-kvoten.

## Grensesnittet: nettsiden

Hver kjøring bygger en selvstendig HTML-side og publiserer den på **GitHub
Pages**. Det er den du bruker til daglig – åpne lenken på mobilen, filtrer, og
trykk videre til inatur.no.

Siden har søk på sted, tilbyder og art, filterknapper for hundestatus og for
kun li-/fjellrype, og viser sitatet som avgjorde hundevurderingen på hvert kort.
Alt ligger i én fil uten eksterne ressurser, så den kan ikke brekke fordi et
CDN er nede, og den følger lyst/mørkt tema fra telefonen.

### Førstegangsoppsett

To innstillinger må settes én gang i repoet:

1. **Settings → Pages → Source: GitHub Actions**
2. **Settings → General → Default branch: `main`**

Kjør deretter arbeidsflyten «Sjekk iNatur» én gang manuelt fra Actions-fanen.
GitHub starter ikke planlagte kjøringer i et helt nytt repo før arbeidsflyten
har kjørt minst én gang.

Merk at repoet er offentlig, så siden blir det også. Den inneholder kun
offentlig tilgjengelige tilbud fra inatur.no.

## Planlegging

GitHub Actions kjører sjekken hver 3. time. Tilstanden ligger i Actions-cachen,
tekstrapporten lastes opp som artifact, og nettsiden publiseres til Pages.

### Endre hvor ofte

Én linje i [`.github/workflows/check.yml`](.github/workflows/check.yml):

```yaml
- cron: "0 */3 * * *"
```

Vanlige verdier står som kommentar rett over. Tidene er UTC – norsk sommertid
er UTC+2, vintertid UTC+1.

| Cron | Hvor ofte |
|---|---|
| `0 */6 * * *` | hver 6. time |
| `0 */3 * * *` | hver 3. time ← nå |
| `0 * * * *` | hver time |
| `0 5,15 * * *` | kl. 07 og 17 norsk tid |
| `0 6 * * *` | én gang daglig, kl. 08 norsk tid |
| `*/20 * * * *` | hvert 20. minutt |

GitHub forsinker planlagte kjøringer i offentlige repo, ofte med 10–20 minutter,
så tettere enn hvert 20. minutt gir lite igjen.

### Skru av

Uten å endre kode: **Actions-fanen → «Sjekk iNatur» → «…» øverst til høyre →
Disable workflow.** Skrus på igjen samme sted. Du kan fortsatt kjøre manuelt med
**Run workflow** mens den er avslått.

Push-varsling er ikke satt opp ennå. `inatur/report.py` og `inatur/site.py` har
begge et smalt grensesnitt (`render` + `write`) nettopp for at Telegram eller
e-post kan legges til senere uten å røre resten.

## Folkeskikk

Verktøyet leser kun offentlig tilgjengelige sider, respekterer `robots.txt`
(som sperrer `/min-side/`, `/handlekurv/`, `/booking` og `/proxy.jsp` – ikke
det vi bruker), venter mellom hver forespørsel, kjører én forespørsel om gangen
og identifiserer seg med en ærlig User-Agent. Ikke sett `delay` under 0,5
sekund – en IP-blokkering setter en effektiv stopper for hele prosjektet.

Verktøyet kjøper ingenting og fyller ikke ut skjemaer. Det finner tilbud – du
tar avgjørelsen og kjøpet selv på inatur.no.
