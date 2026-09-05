"""Analiza si editare de metadata (Artist/Titlu/Album/Gen) pentru track-urile
unei biblioteci Serato - atat in baza de date Serato cat si (optional) in
tag-urile ID3 ale fisierelor audio efective."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import serato_db
from scanner import SeratoLibrary
from serato_db import Track

_SEPARATORS = (" - ", " – ", " — ")

# campurile editabile: nume afisat -> (tag Serato, cheie mutagen "easy")
EDITABLE_FIELDS = {
    "artist": ("tart", "artist"),
    "title": ("tsng", "title"),
    "album": ("talb", "album"),
    "genre": ("tgen", "genre"),
}


_LEADING_TRACK_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*[.\-)]\s*")


def split_artist_title(text: str) -> tuple[str, str] | None:
    """Incearca sa separe 'Artist - Titlu' in doua bucati. None daca nu se potriveste."""
    text = _LEADING_TRACK_NUMBER_RE.sub("", text.strip())
    for sep in _SEPARATORS:
        if sep in text:
            artist, title = text.split(sep, 1)
            artist, title = artist.strip(), title.strip()
            if artist and title:
                return artist, title
    return None


@dataclass
class MetadataSuggestion:
    raw_path: str
    filename: str
    old_artist: str
    old_title: str
    new_artist: str
    new_title: str


def suggest_artist_title_fixes(lib: SeratoLibrary) -> list[MetadataSuggestion]:
    """Gaseste track-uri unde artistul lipseste (si titlul contine 'Artist - Titlu')
    sau unde lipsesc amandoua (folosim numele fisierului)."""
    suggestions = []
    for raw_path, track in lib.tracks.items():
        title = (track.title or "").strip()
        artist = (track.artist or "").strip()
        filename_stem = Path(track.abs_path).stem

        split = None
        if not artist and title:
            split = split_artist_title(title)
        if not artist and not title:
            split = split_artist_title(filename_stem)

        if split:
            new_artist, new_title = split
            suggestions.append(MetadataSuggestion(
                raw_path=raw_path, filename=Path(track.abs_path).name,
                old_artist=artist, old_title=title,
                new_artist=new_artist, new_title=new_title,
            ))
    return suggestions


def apply_database_edits(lib: SeratoLibrary, edits: dict[str, dict[str, str]]):
    """Rescrie in database V2 al bibliotecii campurile date, pentru fiecare
    raw_path din `edits` (ex: {"tsng": "Titlu nou", "tart": "Artist nou"})."""
    db_path = lib.serato_dir / "database V2"
    entries = serato_db.parse_tlv(db_path.read_bytes())
    entries = serato_db.rewrite_track_fields(entries, "pfil", edits)

    db_path.write_bytes(serato_db.serialize_tlv(entries))


def write_id3_tags(abs_path: Path, fields: dict[str, str]):
    """Scrie tag-uri ID3/vorbis/etc in fisierul audio, folosind mutagen (easy mode)."""
    from mutagen import File as MutagenFile

    audio = MutagenFile(str(abs_path), easy=True)
    if audio is None:
        return
    for easy_key, value in fields.items():
        audio[easy_key] = value
    audio.save()


def apply_edits(lib: SeratoLibrary, edits: dict[str, dict[str, str]], write_id3: bool = True):
    """Aplica editari de metadata. `edits`: raw_path -> {tag_serato: valoare noua}
    (tag_serato fiind unul din 'tsng','tart','talb','tgen').

    Actualizeaza baza de date Serato si, daca write_id3, si fisierele audio efective.
    """
    apply_database_edits(lib, edits)

    if not write_id3:
        return

    tag_to_easy = {v[0]: v[1] for v in EDITABLE_FIELDS.values()}
    for raw_path, fields in edits.items():
        track = lib.tracks.get(raw_path)
        if not track:
            continue
        abs_path = Path(track.abs_path)
        if not abs_path.exists():
            continue
        easy_fields = {tag_to_easy[tag]: value for tag, value in fields.items() if tag in tag_to_easy}
        if easy_fields:
            try:
                write_id3_tags(abs_path, easy_fields)
            except Exception:
                pass   # fisier cu format neobisnuit / fara suport de tag-uri - sarim peste
