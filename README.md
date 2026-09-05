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
