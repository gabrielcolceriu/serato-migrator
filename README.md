# Serato Migrator

Unealta personala pentru administrarea unei biblioteci Serato DJ Pro: gaseste
bibliotecile Serato de pe disk (locala sau pe volume externe), verifica ce
track-uri exista efectiv pe disk, gaseste fisiere orfane, si copiaza/reorganizeaza
track-urile pe un disk nou (in foldere numite dupa crate-uri), inclusiv baza de
date Serato, astfel incat noua locatie sa fie utilizabila fara "Locate Missing
Files" manual.

## Ce face

- **Biblioteci** – detecteaza automat toate bibliotecile Serato (`_Serato_`)
  de pe disk si arata cate track-uri sunt cunoscute / prezente / lipsa.
- **Crate-uri** – navigheaza arborele de crate-uri si vezi ce track-uri
  lipsesc de pe disk.
- **Fisiere orfane** – gaseste fisiere audio de pe disk care nu sunt
  cunoscute de nicio biblioteca Serato.
- **Migrare / Reorganizare** – copiaza track-urile intr-o structura de
  foldere dupa crate, copiaza folderul `_Serato_`, rescrie caile din baza de
  date copiata, si normalizeaza numele de fisiere scrise complet cu
  majuscule. Fisierele originale nu sunt niciodata sterse sau modificate.
  La previzualizare calculeaza cat spatiu ii trebuie pe destinatie (copii +
  hardlink-uri care ajung pe alt volum + folderul `_Serato_`) si compara cu
  spatiul liber - daca **nu incape**, avertizeaza inainte si cere confirmare
  explicita ca sa nu ramai cu o copiere oprita la jumatate. Poti alege exact
  **ce crate-uri** migrezi (arbore cu bife, marime per crate + total live),
  util cand biblioteca intreaga nu incape pe discul destinatie.
- **Metadata** – gaseste track-uri unde artistul lipseste (sau e ingropat in
  titlu, gen "Artist - Titlu") si permite revizuirea si aplicarea corectiei,
  plus editare individuala sau de grup a Artist/Titlu/Album/Gen. Scrie atat
  in baza de date Serato cat si in tag-urile ID3 ale fisierelor (`mutagen`).

## Cum functioneaza

Formatul binar al Serato (`database V2` si fisierele `.crate`) e reverse
engineered de comunitate (nu exista o libraria oficiala) - vezi `serato_db.py`
pentru parser/serializer.

## Rulare

```
python3 main.py
```

## Build ca aplicatie .app (macOS)

```
pip3 install py2app
python3 build_icon.py
python3 setup.py py2app
```

Rezultatul apare in `dist/Serato Migrator.app`.
