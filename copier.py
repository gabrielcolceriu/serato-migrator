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


def plan_copy(libraries: list[SeratoLibrary], dest_root: Path, normalize_names: bool = True) -> CopyPlan:
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
            crate_dir = dest_root.joinpath(*crate.hierarchy)
            crate_key = str(crate.file_path)
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
