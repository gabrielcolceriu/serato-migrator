"""Planificare si executie pentru reorganizarea/copierea track-urilor Serato
in foldere pe disk numite dupa crate-uri.

Track-urile care apar in mai multe crate-uri sunt copiate o singura data fizic;
pentru celelalte crate-uri se creeaza hard link (daca destinatia e pe acelasi
volum) - fara consum suplimentar de spatiu.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from scanner import SeratoLibrary, crate_abs_paths
import serato_db

UNSORTED_FOLDER_NAME = "Ne-incadrate in crate-uri"

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def normalize_caps_filename(name: str) -> str:
    """Daca numele (fara extensie) e SCRIS COMPLET CU MAJUSCULE, il converteste
    in Title Case normal. Numele deja cu litere mici raman neatinse."""
    stem, ext = os.path.splitext(name)
    letters = [c for c in stem if c.isalpha()]
    if not letters or any(c.islower() for c in letters):
        return name
    new_stem = _WORD_RE.sub(lambda m: m.group(0).capitalize(), stem)
    return new_stem + ext


@dataclass
class CopyOperation:
    source_path: Path
    dest_path: Path
    is_primary: bool   # True = copiere reala, False = hardlink catre primary
    library_name: str = ""
    raw_path: str = ""            # calea originala Serato (relativa la volume_root)
    crate_key: str | None = None  # cheie unica a crate-ului (calea fisierului .crate), sau None daca e "ne-incadrat"


@dataclass
class CopyPlan:
    operations: list[CopyOperation]
    skipped_missing: list[Path]   # track-uri din crate-uri care lipsesc de pe disk

    @property
    def total_bytes(self) -> int:
        total = 0
        for op in self.operations:
            if op.is_primary:
                try:
                    total += op.source_path.stat().st_size
                except OSError:
                    pass
        return total

    @property
    def link_bytes(self) -> int:
        """Spatiul ocupat de hardlink-uri DACA ajung pe alt volum si devin copii
        reale (vezi execute_plan). Pe acelasi volum raman hardlink-uri = 0 spatiu."""
        total = 0
        for op in self.operations:
            if not op.is_primary:
                try:
                    total += op.source_path.stat().st_size
                except OSError:
                    pass
        return total

    @property
    def primary_count(self) -> int:
        return sum(1 for op in self.operations if op.is_primary)

    @property
    def link_count(self) -> int:
        return sum(1 for op in self.operations if not op.is_primary)


def _unique_dest(dest_dir: Path, filename: str, used: set[Path]) -> Path:
    candidate = dest_dir / filename
    if candidate not in used:
        return candidate
    stem, ext = os.path.splitext(filename)
    n = 2
    while True:
        candidate = dest_dir / f"{stem} ({n}){ext}"
        if candidate not in used:
            return candidate
        n += 1


def copy_serato_folder(lib: SeratoLibrary, dest_root: Path) -> Path:
    """Copiaza folderul _Serato_ (database V2 + Subcrates) la radacina destinatiei,
    ca noul disk sa fie o biblioteca Serato de sine statatoare (dupa un 'Locate
    Missing Files' facut manual in Serato pe noua locatie)."""
    dest_root = Path(dest_root)
    dest_serato = dest_root / "_Serato_"
    shutil.copytree(lib.serato_dir, dest_serato, dirs_exist_ok=True)
    return dest_serato


def plan_copy(
    libraries: list[SeratoLibrary],
    dest_root: Path,
    normalize_names: bool = True,
    selected_crate_keys: set[str] | None = None,
    include_unsorted: bool = True,
) -> CopyPlan:
    """selected_crate_keys: daca e dat, se migreaza doar crate-urile a caror cheie
    (str(crate.file_path)) e in set; restul sunt ignorate complet.
    include_unsorted: daca e False, track-urile care nu apar in niciun crate
    (migrat) nu sunt copiate in folderul "Ne-incadrate in crate-uri"."""
    dest_root = Path(dest_root)
    operations: list[CopyOperation] = []
    skipped_missing: list[Path] = []
    seen_source_to_dest: dict[Path, Path] = {}   # abs source -> primary dest (dedup)
    used_dest_paths: set[Path] = set()
    tracks_placed: set[Path] = set()   # ce surse au fost deja plasate intr-un folder de crate

    def dest_filename(src: Path) -> str:
        return normalize_caps_filename(src.name) if normalize_names else src.name

    for lib in libraries:
        for crate in lib.crates:
            crate_key = str(crate.file_path)
            if selected_crate_keys is not None and crate_key not in selected_crate_keys:
                continue
            crate_dir = dest_root.joinpath(*crate.hierarchy)
            for raw_path in crate.raw_paths:
                src = Path(lib.volume_root) / raw_path
                if not src.exists():
                    skipped_missing.append(src)
                    continue
                dest = _unique_dest(crate_dir, dest_filename(src), used_dest_paths)
                used_dest_paths.add(dest)
                tracks_placed.add(src)

                is_primary = src not in seen_source_to_dest
                if is_primary:
                    seen_source_to_dest[src] = dest
                operations.append(CopyOperation(src, dest, is_primary=is_primary,
                                                 library_name=lib.name, raw_path=raw_path,
                                                 crate_key=crate_key))

        # track-uri cunoscute de biblioteca dar care nu apar in niciun crate
        if not include_unsorted:
            continue
        unsorted_dir = dest_root / UNSORTED_FOLDER_NAME / lib.name
        for raw_path, track in lib.tracks.items():
            src = Path(track.abs_path)
            if src in tracks_placed:
                continue
            if not src.exists():
                continue  # deja raportat separat ca "missing" la nivel de biblioteca
            dest = _unique_dest(unsorted_dir, dest_filename(src), used_dest_paths)
            used_dest_paths.add(dest)
            tracks_placed.add(src)

            is_primary = src not in seen_source_to_dest
            if is_primary:
                seen_source_to_dest[src] = dest
            operations.append(CopyOperation(src, dest, is_primary=is_primary,
                                             library_name=lib.name, raw_path=raw_path,
                                             crate_key=None))

    return CopyPlan(operations=operations, skipped_missing=skipped_missing)


def rewrite_serato_database(lib: SeratoLibrary, plan: CopyPlan, dest_serato_dir: Path, dest_root: Path):
    """Rescrie caile din copia database V2 si din fiecare .crate copiat, ca sa
    reflecte noua locatie a fisierelor - Serato le va vedea direct, fara
    'Locate Missing Files' manual. Modifica DOAR copia din dest_serato_dir,
    niciodata biblioteca originala."""
    dest_root = Path(dest_root)
    dest_serato_dir = Path(dest_serato_dir)
    my_ops = [op for op in plan.operations if op.library_name == lib.name]

    # database V2: fiecare track apare o singura data - folosim locatia primary
    primary_by_raw: dict[str, str] = {}
    for op in my_ops:
        if op.is_primary:
            primary_by_raw[op.raw_path] = op.dest_path.relative_to(dest_root).as_posix()

    db_path = dest_serato_dir / "database V2"
    entries = serato_db.parse_tlv(db_path.read_bytes())
    entries = serato_db.rewrite_paths(entries, "pfil", primary_by_raw)
    db_path.write_bytes(serato_db.serialize_tlv(entries))

    # fiecare .crate: track-urile pot fi in alta locatie (hardlink) fata de primary
    ops_by_crate: dict[str, list[CopyOperation]] = {}
    for op in my_ops:
        if op.crate_key is not None:
            ops_by_crate.setdefault(op.crate_key, []).append(op)

    for crate in lib.crates:
        crate_key = str(crate.file_path)
        crate_ops = ops_by_crate.get(crate_key)
        if not crate_ops:
            continue
        new_by_raw = {op.raw_path: op.dest_path.relative_to(dest_root).as_posix() for op in crate_ops}
        crate_dest_path = dest_serato_dir / "Subcrates" / crate.file_path.name
        if not crate_dest_path.exists():
            continue
        entries = serato_db.parse_tlv(crate_dest_path.read_bytes())
        entries = serato_db.rewrite_paths(entries, "ptrk", new_by_raw)
        crate_dest_path.write_bytes(serato_db.serialize_tlv(entries))


def write_fresh_serato(
    libraries: list[SeratoLibrary], plan: CopyPlan, dest_serato_dir: Path, dest_root: Path
):
    """Construieste un `_Serato_` NOU la destinatie, de la zero:
      - `database V2` nou, doar cu track-urile efectiv migrate (o intrare per
        fisier fizic), cu caile catre noua locatie; metadata fiecarui track e
        clonata din otrk-ul original (BPM, key, bitrate, an, comentarii...),
        sau minimala daca track-ul nu era in baza sursa.
      - doar fisierele `.crate` ale crate-urilor migrate, cu antetul original
        (coloane + sortare) pastrat si lista de track-uri inlocuita.
    Folderul `_Serato_` sursa NU e citit decat pentru metadata si NU e copiat.
    Suporta mai multe biblioteci - se imbina intr-o singura baza noua.
    """
    dest_root = Path(dest_root)
    dest_serato_dir = Path(dest_serato_dir)
    (dest_serato_dir / "Subcrates").mkdir(parents=True, exist_ok=True)

    otrk_list: list[list] = []
    vrsn_value: bytes | None = None

    for lib in libraries:
        my_ops = [op for op in plan.operations if op.library_name == lib.name]
        if not my_ops:
            continue

        src_db = lib.serato_dir / "database V2"
        src_idx: dict[str, list] = {}
        if src_db.is_file():
            v, src_idx = serato_db.index_otrk_by_path(src_db.read_bytes())
            if vrsn_value is None and v:
                vrsn_value = v

        for op in my_ops:
            if not op.is_primary:
                continue
            new_rel = op.dest_path.relative_to(dest_root).as_posix()
            src_fields = src_idx.get(op.raw_path)
            if src_fields is not None:
                otrk_list.append(serato_db.otrk_with_path(src_fields, new_rel))
            else:
                ext = op.dest_path.suffix.lower().lstrip(".")
                otrk_list.append(serato_db.minimal_otrk(new_rel, ext or None))

        # crate-urile migrate ale acestei biblioteci
        ops_by_crate: dict[str, list[CopyOperation]] = {}
        for op in my_ops:
            if op.crate_key is not None:
                ops_by_crate.setdefault(op.crate_key, []).append(op)

        crate_by_key = {str(c.file_path): c for c in lib.crates}
        for crate_key, crate_ops in ops_by_crate.items():
            crate = crate_by_key.get(crate_key)
            if crate is None:
                continue
            rel_by_raw = {
                op.raw_path: op.dest_path.relative_to(dest_root).as_posix()
                for op in crate_ops
            }
            # pastreaza ordinea originala a track-urilor in crate
            ordered = [rel_by_raw[rp] for rp in crate.raw_paths if rp in rel_by_raw]
            src_bytes = crate.file_path.read_bytes() if crate.file_path.is_file() else None
            out = serato_db.build_crate(ordered, source_crate_bytes=src_bytes)
            (dest_serato_dir / "Subcrates" / crate.file_path.name).write_bytes(out)

    (dest_serato_dir / "database V2").write_bytes(
        serato_db.build_database(otrk_list, vrsn_value)
    )


_DB_ESSENTIAL_FILES = ("database V2", "neworder.pref", "collapsed.pref")
_DB_ESSENTIAL_DIRS = ("Subcrates", "SmartCrates", "Smart Crates")


def add_orphans_to_crate(
    library: SeratoLibrary, orphan_abs_paths, crate_name: str = "Orfane"
) -> tuple[int, int]:
    """Adauga fisierele orfane (cai absolute pe volumul bibliotecii) intr-un crate
    `crate_name` si in `database V2`, ca Serato sa le vada. Backup la database V2
    intai. Returneaza (adaugate in crate, adaugate in baza)."""
    serato_dir = Path(library.serato_dir)
    vol = Path(library.volume_root)

    rels: list[str] = []
    for p in orphan_abs_paths:
        p = Path(p)
        try:
            rels.append(p.relative_to(vol).as_posix())
        except ValueError:
            continue  # nu e pe volumul bibliotecii

    subcrates = serato_dir / "Subcrates"
    subcrates.mkdir(parents=True, exist_ok=True)
    crate_path = subcrates / f"{crate_name}.crate"

    existing_bytes = crate_path.read_bytes() if crate_path.is_file() else None
    existing = serato_db.parse_crate(crate_path) if existing_bytes else []
    seen = set(existing)
    merged = list(existing)
    added_crate = 0
    for r in rels:
        if r not in seen:
            merged.append(r)
            seen.add(r)
            added_crate += 1
    crate_path.write_bytes(serato_db.build_crate(merged, source_crate_bytes=existing_bytes))

    db_path = serato_dir / "database V2"
    added_db = 0
    if db_path.is_file():
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        shutil.copy2(db_path, db_path.with_name(f"database V2 (orfane backup {stamp})"))
        vrsn, idx = serato_db.index_otrk_by_path(db_path.read_bytes())
        otrk_list = list(idx.values())
        for r in rels:
            if r not in idx:
                ext = Path(r).suffix.lower().lstrip(".")
                otrk_list.append(serato_db.minimal_otrk(r, ext or None))
                idx[r] = True
                added_db += 1
        if added_db:
            db_path.write_bytes(serato_db.build_database(otrk_list, vrsn))

    return added_crate, added_db


def export_database(library: SeratoLibrary, dest_zip: Path) -> int:
    """Salveaza baza de date a bibliotecii (database V2 + crate-uri + pref-uri de
    ordonare) intr-un .zip la `dest_zip`. Returneaza numarul de intrari scrise.
    Nu include Metadata/ (waveform-uri regenerabile) sau database V2.backup."""
    import zipfile

    serato_dir = Path(library.serato_dir)
    dest_zip = Path(dest_zip)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in _DB_ESSENTIAL_FILES:
            f = serato_dir / name
            if f.is_file():
                zf.write(f, f"_Serato_/{name}")
                n += 1
        for folder in _DB_ESSENTIAL_DIRS:
            d = serato_dir / folder
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    zf.write(f, f"_Serato_/{folder}/{f.relative_to(d).as_posix()}")
                    n += 1
    return n


@dataclass
class RebuildResult:
    backup_dir: Path
    tracks_kept: int
    tracks_dropped: int
    crates_kept: int
    crates_dropped: int


def rebuild_database_from_disk(
    library: SeratoLibrary, include_unknown_audio: bool = False
) -> RebuildResult:
    """Reconstruieste PE LOC `_Serato_/database V2` + fisierele `.crate` ale unei
    biblioteci, pastrand DOAR track-urile al caror fisier exista fizic pe disc
    (adica cele efectiv puse pe acest volum). Face intai un backup complet al
    folderului `_Serato_`. Metadata per track e clonata din baza veche.

    include_unknown_audio: daca True, adauga in baza si fisierele audio gasite
    pe volum care nu apar in nicio intrare - Serato le completeaza la scanare.
    """
    serato_dir = Path(library.serato_dir)
    vol = Path(library.volume_root)

    # backup DOAR fisierele esentiale ale bibliotecii (nu si Metadata/ cu
    # waveform-urile regenerabile, nici Export Backups/ - alea faceau backup-uri
    # de sute de MB fiecare).
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    backup_dir = serato_dir.with_name(f"_Serato_ (backup {stamp})")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in _DB_ESSENTIAL_FILES:   # fara database V2.backup (auto Serato, uneori sute de MB)
        src = serato_dir / name
        if src.is_file():
            shutil.copy2(src, backup_dir / name)
    for folder in _DB_ESSENTIAL_DIRS:
        src = serato_dir / folder
        if src.is_dir():
            shutil.copytree(src, backup_dir / folder)

    db_path = serato_dir / "database V2"
    vrsn_value, src_idx = (None, {})
    if db_path.is_file():
        vrsn_value, src_idx = serato_db.index_otrk_by_path(db_path.read_bytes())

    def present(raw_path: str) -> bool:
        return (vol / raw_path).is_file()

    # --- crate-uri: filtreaza track-urile lipsa, arunca crate-urile goale ---
    crates_kept = crates_dropped = 0
    kept_raw: set[str] = set()
    subcrates = serato_dir / "Subcrates"
    if subcrates.is_dir():
        for cf in sorted(subcrates.glob("*.crate")):
            raw_paths = serato_db.parse_crate(cf)
            keep = [rp for rp in raw_paths if present(rp)]
            if not keep:
                cf.unlink()
                crates_dropped += 1
                continue
            cf.write_bytes(serato_db.build_crate(keep, source_crate_bytes=cf.read_bytes()))
            kept_raw.update(keep)
            crates_kept += 1

    # --- database V2 nou ---
    all_present = [rp for rp in src_idx if present(rp)]
    dropped = len(src_idx) - len(all_present)

    if include_unknown_audio:
        from scanner import AUDIO_EXTENSIONS, _walk_audio_files
        known = set(all_present)
        for p in _walk_audio_files(vol):
            rel = p.relative_to(vol).as_posix()
            if rel not in known and p.suffix.lower() in AUDIO_EXTENSIONS:
                all_present.append(rel)
                known.add(rel)

    otrk_list = []
    for rp in all_present:
        fields = src_idx.get(rp)
        if fields is not None:
            otrk_list.append(list(fields))
        else:
            ext = Path(rp).suffix.lower().lstrip(".")
            otrk_list.append(serato_db.minimal_otrk(rp, ext or None))

    db_path.write_bytes(serato_db.build_database(otrk_list, vrsn_value))

    return RebuildResult(
        backup_dir=backup_dir,
        tracks_kept=len(otrk_list),
        tracks_dropped=dropped,
        crates_kept=crates_kept,
        crates_dropped=crates_dropped,
    )


def crate_stats(lib: SeratoLibrary, crate) -> tuple[int, int, int]:
    """(track-uri prezente, track-uri lipsa, bytes prezenti) pentru un crate.
    Bytes-ii numara fiecare fisier fizic o singura data chiar daca apare de mai
    multe ori in crate."""
    present = missing = 0
    seen: set[str] = set()
    total = 0
    for raw_path in crate.raw_paths:
        full = os.path.join(lib.volume_root, raw_path)
        try:
            st = os.stat(full)
        except OSError:
            missing += 1
            continue
        present += 1
        if full not in seen:
            seen.add(full)
            total += st.st_size
    return present, missing, total


def dir_size(path: Path) -> int:
    """Marimea totala (bytes) a unui folder, recursiv. Link-urile simbolice
    frante si erorile de acces sunt ignorate."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += os.stat(fp, follow_symlinks=False).st_size
            except OSError:
                pass
    return total


def free_space(path: Path) -> int | None:
    """Spatiul liber (bytes) pe volumul care contine `path`. Daca `path` inca nu
    exista, urca la primul parinte existent. Returneaza None daca nu se poate afla."""
    p = Path(path)
    while not p.exists():
        if p.parent == p:
            return None
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def estimate_required_bytes(
    plan: CopyPlan, dest_root: Path, serato_source_dir: Path | None = None
) -> int:
    """Cat spatiu ii trebuie planului pe destinatie: copiile reale, plus
    hardlink-urile care ajung pe alt volum (devin copii), plus folderul _Serato_
    daca e copiat si el."""
    required = plan.total_bytes

    dest_dev = None
    probe = Path(dest_root)
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    try:
        dest_dev = os.stat(probe).st_dev
    except OSError:
        dest_dev = None

    for op in plan.operations:
        if op.is_primary:
            continue
        try:
            same_vol = dest_dev is not None and op.source_path.stat().st_dev == dest_dev
        except OSError:
            same_vol = False
        if not same_vol:
            try:
                required += op.source_path.stat().st_size
            except OSError:
                pass

    if serato_source_dir is not None:
        required += dir_size(Path(serato_source_dir))

    return required


def execute_plan(plan: CopyPlan, progress_callback=None):
    """Executa planul. progress_callback(done, total, current_operation) e apelat dupa fiecare fisier."""
    total = len(plan.operations)
    dest_dirs_created: set[Path] = set()

    for i, op in enumerate(plan.operations, start=1):
        dest_dir = op.dest_path.parent
        if dest_dir not in dest_dirs_created:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_dirs_created.add(dest_dir)

        if op.is_primary:
            shutil.copy2(op.source_path, op.dest_path)
        else:
            try:
                os.link(op.source_path, op.dest_path)
            except OSError:
                # volume diferit sau filesystem fara suport hardlink -> copiere normala
                shutil.copy2(op.source_path, op.dest_path)

        if progress_callback:
            progress_callback(i, total, op)
