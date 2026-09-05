"""Detectare automata a bibliotecilor Serato (locala + volume externe) si
construirea unui model unificat: librarii, crate-uri, track-uri, orfane."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import serato_db as sdb

AUDIO_EXTENSIONS = {".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a", ".ogg", ".wma", ".alac"}

# foldere de ignorat la scanarea pentru fisiere orfane
IGNORE_DIR_NAMES = {
    "_Serato_", ".Spotlight-V100", ".Trashes", ".TemporaryItems", ".fseventsd",
    "$RECYCLE.BIN", "System Volume Information",
}


@dataclass
class SeratoLibrary:
    name: str                # nume descriptiv, ex: "PortableSSD" sau "Mac (local)"
    volume_root: str         # radacina fata de care sunt relative caile, ex "/Volumes/PortableSSD" sau "/"
    serato_dir: Path
    tracks: dict[str, sdb.Track] = field(default_factory=dict)
    crates: list[sdb.Crate] = field(default_factory=list)

    @property
    def missing_tracks(self) -> list[sdb.Track]:
        return [t for t in self.tracks.values() if not t.exists]

    @property
    def present_tracks(self) -> list[sdb.Track]:
        return [t for t in self.tracks.values() if t.exists]


def find_serato_libraries() -> list[SeratoLibrary]:
    """Cauta biblioteci Serato: ~/Music/_Serato_ + radacina fiecarui volum montat."""
    candidates: list[tuple[str, str]] = []  # (volume_root, name)

    home_music = Path.home() / "Music"
    if (home_music / "_Serato_").is_dir():
        candidates.append((str(home_music), "Mac (local)"))

    volumes_dir = Path("/Volumes")
    if volumes_dir.is_dir():
        for entry in sorted(volumes_dir.iterdir()):
            if entry.name == "Macintosh HD":
                continue  # e link catre "/", deja acoperit de home_music
            try:
                if (entry / "_Serato_").is_dir():
                    candidates.append((str(entry), entry.name))
            except PermissionError:
                continue

    libraries = []
    for volume_root, name in candidates:
        serato_dir = Path(volume_root) / "_Serato_"
        db_path = serato_dir / "database V2"
        if not db_path.is_file():
            continue
        tracks = sdb.parse_database(db_path, volume_root=volume_root)
        crates = sdb.load_subcrates(serato_dir)
        libraries.append(SeratoLibrary(
            name=name, volume_root=volume_root, serato_dir=serato_dir,
            tracks=tracks, crates=crates,
        ))
    return libraries


def crate_abs_paths(crate: sdb.Crate, volume_root: str) -> list[str]:
    return [str(Path(volume_root) / p) for p in crate.raw_paths]


PROGRESS_EVERY = 250   # la cate fisiere scanate se apeleaza progress_cb


def find_orphan_files(scan_root: str | Path, known_abs_paths: set[str], progress_cb=None) -> list[Path]:
    """Cauta fisiere audio sub scan_root care NU apar in known_abs_paths.

    known_abs_paths trebuie sa fie cai absolute normalizate (str) - de obicei
    reuniunea tuturor track-urilor cunoscute de biblioteca(ile) Serato de pe acel volum.
    progress_cb(scanate, orfane_gasite_pana_acum), apelat periodic.
    """
    scan_root = Path(scan_root)
    orphans = []
    scanned = 0
    for path in _walk_audio_files(scan_root):
        scanned += 1
        if str(path) not in known_abs_paths:
            orphans.append(path)
        if progress_cb and scanned % PROGRESS_EVERY == 0:
            progress_cb(scanned, len(orphans))
    if progress_cb:
        progress_cb(scanned, len(orphans))
    return orphans


def build_filename_index(root: str | Path, progress_cb=None) -> dict[str, list[Path]]:
    """Indexeaza toate fisierele audio de sub root dupa nume de fisier (fara cale).

    progress_cb(numar_fisiere_indexate), apelat periodic.
    """
    index: dict[str, list[Path]] = {}
    count = 0
    for p in _walk_audio_files(Path(root)):
        index.setdefault(p.name, []).append(p)
        count += 1
        if progress_cb and count % PROGRESS_EVERY == 0:
            progress_cb(count)
    if progress_cb:
        progress_cb(count)
    return index


def find_missing_elsewhere(
    library: SeratoLibrary, progress_cb=None
) -> tuple[list[tuple[sdb.Track, list[Path]]], list[sdb.Track]]:
    """Pentru track-urile lipsa dintr-o biblioteca, cauta pe tot volumul acesteia
    dupa nume de fisier identic, in caz ca au fost doar mutate/reorganizate.

    Returneaza (gasite: lista de (Track, lista de cai candidate), chiar_lipsa: lista de Track).
    """
    missing = library.missing_tracks
    index = build_filename_index(library.volume_root, progress_cb=progress_cb)
    found: list[tuple[sdb.Track, list[Path]]] = []
    still_missing: list[sdb.Track] = []
    for t in missing:
        candidates = index.get(Path(t.abs_path).name)
        if candidates:
            found.append((t, candidates))
        else:
            still_missing.append(t)
    return found, still_missing


def _walk_audio_files(root: Path):
    try:
        entries = list(root.iterdir())
    except (PermissionError, OSError):
        return
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name in IGNORE_DIR_NAMES:
                continue
            yield from _walk_audio_files(entry)
        elif entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS:
            yield entry
