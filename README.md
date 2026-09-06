<h1 align="center">Serato Migrator</h1>

<p align="center">
  <img src="assets/logo.png" alt="Serato Migrator" width="140">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.7.1-blue?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/platform-macOS-000000?style=for-the-badge&logo=apple" alt="macOS">
  <img src="https://img.shields.io/badge/UI-AppKit%20%2F%20PyObjC-1f6feb?style=for-the-badge&logo=apple&logoColor=white" alt="AppKit">
  <img src="https://img.shields.io/badge/python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.13">
  <img src="https://img.shields.io/badge/status-neoficial-lightgrey?style=for-the-badge" alt="Neoficial">
</p>

<p align="center">
  Unealtă personală pentru administrarea unei biblioteci <strong>Serato DJ Pro</strong>: găsește
  bibliotecile de pe disc, verifică ce track-uri există efectiv, găsește fișiere orfane și
  <strong>migrează / reorganizează</strong> track-urile pe un disc nou (în foldere numite după
  crate-uri), cu tot cu baza de date — noua locație e utilizabilă fără „Locate Missing Files" manual.
</p>

---

## 🖥️ Interfață nativă macOS

De la **0.7.0**, UI-ul e rescris complet în **AppKit / PyObjC** (HIG Tahoe): bară laterală
grupată în stil „source list", toolbar unificat cu titlul, layout pe trei coloane
(bară laterală · conținut · inspector contextual), ecran **Prezentare**, **Migrare** ca flux
ghidat în 7 pași (Sursă → Destinație → Opțiuni → Verificare → Migrare → Verificare-post →
Complet) cu backup înainte de copiere și verificare read-only după, **Jurnal** cu vederi
Activitate + Raw, meniuri contextuale, drag & drop, paletă de comenzi (⌘K), Setări (⌘,),
mod întunecat + accent de sistem. Vechiul UI Tkinter e păstrat la
[`legacy/gui_tk.py`](legacy/gui_tk.py); logica (`serato_db` / `scanner` / `copier` /
`metadata_editor`) e neschimbată. Detalii: [`docs/UI_REDESIGN_2026.md`](docs/UI_REDESIGN_2026.md).

---

## ✨ Ce face

| | |
|---|---|
| 📚 **Biblioteci** | Detectează automat toate bibliotecile Serato (`_Serato_`) de pe disc (locală + volume externe montate) și arată câte track-uri sunt cunoscute / prezente / lipsă. |
| 🗂️ **Crate-uri** | Navighează arborele de crate-uri și vezi ce track-uri lipsesc de pe disc. |
| 🔎 **Fișiere orfane** | Găsește fișiere audio de pe disc care nu sunt cunoscute de nicio bibliotecă Serato. |
| 🚚 **Migrare / Reorganizare** | Copiază track-urile într-o structură de foldere după crate, copiază folderul `_Serato_`, **rescrie căile** din baza de date copiată și normalizează numele scrise complet cu MAJUSCULE. Originalele nu sunt niciodată șterse sau modificate. |
| 📏 **Verificare spațiu** | La previzualizare calculează cât spațiu îi trebuie pe destinație (copii + hardlink-uri cross-volum + folderul `_Serato_`) și **avertizează dacă nu încape**, cu confirmare explicită. |
| ✅ **Selecție crate-uri** | Alegi exact ce crate-uri migrezi (arbore cu bife, mărime per crate + total live) — util când biblioteca întreagă nu încape pe discul destinație. |
| 🏷️ **Metadata** | Găsește track-uri unde artistul lipsește (sau e îngropat în titlu, gen „Artist - Titlu"), permite revizuirea și corecția, plus editare individuală sau de grup a Artist / Titlu / Album / Gen. Scrie atât în baza de date Serato cât și în tag-urile ID3 (`mutagen`). |
| ✏️ **Redenumire** | Normalizează în bloc numele fișierelor (elimină `_`, numere de la început, etichete `(official video)` / `[www…]`, MAJUSCULE → Title Case) și **rescrie căile** din `database V2` și din crate-uri, cu backup înainte. Preview obligatoriu. |
| 🛡️ **Siguranță** | Blochează scrierile cât timp Serato DJ Pro rulează; cere confirmare la închidere și nu se închide în timpul unei operațiuni. |

---

## 🚀 Rulare din sursă

```bash
python3 main.py
```

Necesită Python 3.13, `mutagen` și `pyobjc` (`pip3 install mutagen pyobjc-framework-Cocoa`).

---

## 📦 Build ca aplicație `.app` (macOS)

```bash
pip3 install py2app mutagen
python3 build_icon.py
python3 setup.py py2app
```

Rezultatul apare în `dist/Serato Migrator.app`.

---

## 🔧 Cum funcționează

Formatul binar al Serato (`database V2` și fișierele `.crate`) e **reverse-engineered de comunitate**
(nu există o librărie oficială Serato) — vezi [`serato_db.py`](serato_db.py) pentru parser / serializer
TLV. Același format e folosit și de Mixxx, `serato-tags` etc.

Migrarea nu atinge niciodată biblioteca sursă: copiază fișierele, copiază `_Serato_` la rădăcina
destinației și rescrie **doar copia** bazei de date, ca Serato să vadă track-urile la noua locație
fără relocare manuală.

---

## ⚠️ Disclaimer

Unealtă **neoficială**, fără legătură cu Serato. Operează pe copii — fișierele și baza de date
originale nu sunt șterse sau modificate — dar rămâne responsabilitatea ta să ai un backup înainte
de o migrare mare.
