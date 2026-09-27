# OVHcloud-laskuraportti

Työkalu lukee hakemiston OVHcloudin PDF-laskut, täsmäyttää niiden summat ja muodostaa kuukausittaisen palveluraportin. Palvelumaksut jaetaan palvelujakson päivien mukaan kalenterikuukausille. Samaan dedikoituun palvelimeen liittyvät vuokra-, laitteisto-, kaista-, asennus- ja alennusrivit esitetään yhtenä kustannusryhmänä.

Raportti toimii kokonaan paikallisesti. Se ei lähetä laskuja tai niiden tietoja verkkoon.

Palvelimet ryhmitellään pysyvällä OVH-resurssitunnuksella. Raportissa ryhmän otsikkona näytetään viimeisin laskulta löytyvä käyttäjän antama hostname. Verollisen ja verottoman näkymän voi vaihtaa raportin yläreunan kytkimestä. Suomen yleisen ALV-kannan muutos 24 prosentista 25,5 prosenttiin tarkistetaan 1.9.2024 alkaen; laskusummat säilytetään aina laskulle merkityn todellisen verokannan mukaisina ja mahdollinen poikkeama näytetään vain kyseisen laskun rivillä täsmäytetyissä lähteissä.

## Asennus ja ajo uv:lla

```bash
uv sync
uv run ovh-report
```

## Asennus ja ajo venvillä

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/ovh-report
```

Windowsin komentokehotteessa viimeinen komento on `.venv\Scripts\ovh-report.exe`.

Onnistuneen ajon jälkeen avaa `output/index.html` selaimessa. HTTP-palvelinta tai verkkoyhteyttä ei tarvita. `output/report.json` sisältää saman raporttiaineiston koneluettavassa muodossa. Raporttiin valittu lähde-PDF kopioidaan muuttamattomana polkuun `output/pdfs/VUOSI/LASKUNUMERO.pdf`, jotta laskulinkit toimivat koko output-hakemistoa siirrettäessä.

Oletuksena työkalu etsii rekursiivisesti kaikki PDF-tiedostot `input/`-hakemistosta ja kirjoittaa raportin `output/`-hakemistoon. PDF:n nimellä tai alihakemiston nimellä ei ole merkitystä: laskutunnus ja muut tiedot luetaan aina PDF:n sisällöstä. Jos sama laskunumero löytyy useasti täysin samalla parsitulla sisällöllä, ensimmäinen säilytetään ja muista tulostetaan konsolivaroitus. Jos saman laskunumeron sisältö poikkeaa, ajo keskeytetään ja erot ilmoitetaan. Polut voi edelleen antaa erikseen komennolla `ovh-report MUU_INPUT --output MUU_OUTPUT`. Syöte ja output eivät saa sijaita sisäkkäin. Työkalu ei käytä tietokantaa tai aiemman ajon tilaa: jokainen ajo lukee kaikki PDF:t ja rakentaa koko raportin tyhjästä. Vanha output korvataan vasta, kun kaikki laskut on parsittu ja validoitu. Virhetilanteessa komento palauttaa virhekoodin ja ilmoittaa laskun sekä mahdollisuuksien mukaan sivun ja epäonnistuneen kohdan.

## Tarkistukset

```bash
uv sync --extra test
uv run pytest
```

Testit käsittelevät myös tämän hakemiston koko PDF-aineiston, jos laskut ovat saatavilla.
