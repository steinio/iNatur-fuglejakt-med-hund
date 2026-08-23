# iNatur – fuglejakt med hund

Overvåker [inatur.no](https://www.inatur.no) og varsler om **ledige
småvilttilbud på fugl som tillater bruk av hund**. Lirype og fjellrype
prioriteres, men alle fuglearter tas med.

Bakgrunnen er enkel: ledige kort dukker opp uregelmessig – restsalg,
avbestillinger, nye tilbud – og forsvinner fort. Å sjekke søkesiden manuelt
flere ganger om dagen er ikke særlig gøy.

## Status

| Del | Status |
|---|---|
| Artsgjenkjenning (lirype, fjellrype, orrfugl …) | ✅ ferdig, testdekket |
| Hundeklassifisering med negasjonshåndtering | ✅ ferdig, testdekket |
| Tilstandslagring og diffing | ✅ ferdig, testdekket |
| Rapportering til konsoll/fil | ✅ ferdig |
| GitHub Actions-planlegging | ✅ ferdig |
| HTTP-henting og HTML-parsing | ⚠️ **må kalibreres mot ekte nettsted** |

Parseren er skrevet uten tilgang til www.inatur.no, så selektorene er
heuristiske. Se [`docs/RECON.md`](docs/RECON.md) for hvordan de strammes inn.

## Kom i gang

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

inatur check --dry-run     # kjør uten å lagre tilstand
pytest -q                  # kjør testene
```

## Hvordan det virker

**1. Søk.** Paginerer gjennom `/sok/smaavilttilbud?...&ledig=true&p=N` til
resultatene tar slutt, og henter deretter detaljsiden for hvert tilbud –
hundereglene står i vilkårsteksten, ikke i trefflista.

**2. Klassifiser.** Den vanskelige delen. Vilkårene er fritekst skrevet av
hundrevis av grunneiere og fjellstyrer, og formuleringene spriker:

```
"Jakt med hund er tillatt fra 20.09"      → betinget ja, fra 20.09
"Det er ikke tillatt å bruke hund"        → nei
"Kun stående fuglehund"                   → betinget ja
"Løs, halsende hund er forbudt"           → nei
```

Nøkkelen er **negasjonshåndtering**: «hund» + «tillatt» i samme setning betyr
ingenting hvis det står «ikke» rett foran. Hver setning vurderes derfor for seg,
med et vindu rundt tillatelsesordet. Resultatet er én av fem statuser – og
alltid med *setningen som avgjorde* vedlagt, så du kan overprøve maskina.

Vi varsler bevisst også ved `unclear` og `no_mention`. Å gå glipp av et
lirypekort koster mer enn et varsel for mye.

**3. Diff.** Alt lagres i SQLite, slik at du kun varsles om det som faktisk er
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
inatur explain https://www.inatur.no/jakt/<slug>

inatur discover               # lagre rå HTML for kalibrering
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
prisgrense, fylker, og hvor forsiktig scrapingen skal være.

## Planlegging

GitHub Actions kjører sjekken automatisk:

- **aug–okt** (sesong og restsalg): hvert 15. minutt, 05–22 norsk tid
- **resten av året**: hver time

Tilstanden ligger i Actions-cachen, og rapporten lastes opp som artifact.
Kan også kjøres fra `workflow_dispatch`.

Varsling er foreløpig konsoll/logg. `inatur/report.py` har et smalt grensesnitt
(`render` + `write`) nettopp for at Telegram eller e-post kan legges til senere
uten å røre resten.

## Folkeskikk

Verktøyet leser kun offentlig tilgjengelige sider, respekterer `robots.txt`,
venter 1,5 s mellom hver forespørsel, kjører én forespørsel om gangen og
identifiserer seg med en ærlig User-Agent. Ikke sett `delay` under 1 sekund –
en IP-blokkering setter en effektiv stopper for hele prosjektet.

Verktøyet kjøper ingenting og fyller ikke ut skjemaer. Det finner tilbud – du
tar avgjørelsen og kjøpet selv på inatur.no.
