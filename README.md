# OVHcloud-laskuraportti

Työkalu lukee hakemiston OVHcloudin PDF-laskut, täsmäyttää niiden summat ja muodostaa kuukausittaisen palveluraportin. Palvelumaksut jaetaan palvelujakson päivien mukaan kalenterikuukausille. Samaan dedikoituun palvelimeen liittyvät vuokra-, laitteisto-, kaista-, asennus- ja alennusrivit esitetään yhtenä kustannusryhmänä.

Raportti toimii kokonaan paikallisesti. Se ei lähetä laskuja tai niiden tietoja verkkoon.

Palvelimet ryhmitellään pysyvällä OVH-resurssitunnuksella. Raportissa ryhmän otsikkona näytetään viimeisin laskulta löytyvä käyttäjän antama hostname. Verollisen ja verottoman näkymän voi vaihtaa raportin yläreunan kytkimestä. Suomen yleisen ALV-kannan muutos 24 prosentista 25,5 prosenttiin tarkistetaan 1.9.2024 alkaen; laskusummat säilytetään aina laskulle merkityn todellisen verokannan mukaisina ja mahdollinen poikkeama näytetään vain kyseisen laskun rivillä täsmäytetyissä lähteissä.

## Ennen ensimmäistä ajoa

Työkalu vaatii Python 3.11:n tai uudemman. Kopioi käsiteltävät PDF-laskut projektin `input`-hakemistoon. Hakemiston alla saa olla myös alihakemistoja.

Ensimmäinen asennus tarvitsee verkkoyhteyden Pythonin ja riippuvuuksien lataamiseen. Varsinainen raportin muodostaminen käsittelee laskut paikallisesti eikä lähetä niitä verkkoon.

## Windows (suositeltu tapa: uv)

Suorita seuraavat komennot PowerShellissä projektihakemistossa.

1. Asenna `uv` Windowsin paketinhallinnalla:

   ```powershell
   winget install --id=astral-sh.uv -e
   ```

   Sulje PowerShell asennuksen jälkeen, avaa se uudelleen projektihakemistossa ja varmista asennus:

   ```powershell
   uv --version
   ```

2. Asenna projektin riippuvuudet. `uv` hankkii tarvittaessa myös sopivan Python-version:

   ```powershell
   uv sync
   ```

3. Lisää laskut `input`-hakemistoon ja muodosta raportti:

   ```powershell
   uv run ovh-report
   ```

4. Avaa valmis raportti oletusselaimessa:

   ```powershell
   Start-Process .\output\index.html
   ```

Kun lisäät tai poistat laskuja, raportin voi rakentaa uudelleen pelkällä `uv run ovh-report` -komennolla. Ohjelma lukee kaikki PDF:t uudelleen ja korvaa aiemman `output`-hakemiston vasta onnistuneen ajon lopuksi.

### Windows ilman uv:ta

Jos koneessa on jo Python 3.11 tai uudempi, voit käyttää Pythonin omaa virtuaaliympäristöä. Virtuaaliympäristöä ei tarvitse aktivoida, koska alla olevat komennot kutsuvat sen ohjelmia suoraan.

PowerShell:

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\ovh-report.exe
Start-Process .\output\index.html
```

Perinteinen komentokehote (`cmd.exe`):

```bat
py --version
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\ovh-report.exe
start "" output\index.html
```

Varmista `py --version` -tulosteesta, että käytössä on vähintään Python 3.11. Jos `py`-komentoa tai sopivaa Pythonia ei löydy, asenna vähintään Python 3.11 tai käytä yllä olevaa `uv`-tapaa. Jos juuri asennettua `uv`-komentoa ei löydy, avaa uusi PowerShell-ikkuna, jotta päivittynyt `PATH` tulee käyttöön.

## Linux ja macOS (uv)

```bash
uv sync
uv run ovh-report
```

## Linux ja macOS (venv)

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/ovh-report
```

Onnistuneen ajon jälkeen avaa `output/index.html` selaimessa. HTTP-palvelinta tai verkkoyhteyttä ei tarvita. `output/report.json` sisältää saman raporttiaineiston koneluettavassa muodossa. Raporttiin valittu lähde-PDF kopioidaan muuttamattomana polkuun `output/pdfs/VUOSI/LASKUNUMERO.pdf`, jotta laskulinkit toimivat koko output-hakemistoa siirrettäessä.

Oletuksena työkalu etsii rekursiivisesti kaikki PDF-tiedostot `input/`-hakemistosta ja kirjoittaa raportin `output/`-hakemistoon. PDF:n nimellä tai alihakemiston nimellä ei ole merkitystä: laskutunnus ja muut tiedot luetaan aina PDF:n sisällöstä. Jos sama laskunumero löytyy useasti täysin samalla parsitulla sisällöllä, ensimmäinen säilytetään ja muista tulostetaan konsolivaroitus. Jos saman laskunumeron sisältö poikkeaa, ajo keskeytetään ja erot ilmoitetaan. Polut voi edelleen antaa erikseen komennolla `ovh-report MUU_INPUT --output MUU_OUTPUT`. Syöte ja output eivät saa sijaita sisäkkäin. Työkalu ei käytä tietokantaa tai aiemman ajon tilaa: jokainen ajo lukee kaikki PDF:t ja rakentaa koko raportin tyhjästä. Vanha output korvataan vasta, kun kaikki laskut on parsittu ja validoitu. Virhetilanteessa komento palauttaa virhekoodin ja ilmoittaa laskun sekä mahdollisuuksien mukaan sivun ja epäonnistuneen kohdan.

## Tarkistukset

```bash
uv sync --extra test
uv run pytest
```

Testit käsittelevät myös tämän hakemiston koko PDF-aineiston, jos laskut ovat saatavilla.
