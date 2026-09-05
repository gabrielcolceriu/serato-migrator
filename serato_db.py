"""Parser pentru formatul binar Serato DJ Pro: database V2 si fisiere .crate.

Format: TLV (tag-length-value).
  - tag: 4 caractere ASCII
  - length: uint32 big-endian
  - value: continut, interpretat dupa prima litera a tag-ului:
      'o' -> container (se parseaza recursiv ca lista de tag-uri)
      't' / 'p' -> text UTF-16BE
      'b' -> boolean (1 byte)
      'u' -> uint32 big-endian
      altfel -> bytes brute

Referinta: format reverse-engineered de comunitate (folosit si de Mixxx,
serato-tags, etc.) - nu exista libraria oficiala Serato.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path


def parse_tlv(data: bytes) -> list[tuple[str, object]]:
    entries = []
    pos = 0
    n = len(data)
    while pos + 8 <= n:
        tag = data[pos:pos + 4].decode("ascii", errors="replace")
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        pos += 8
        value_bytes = data[pos:pos + length]
        pos += length

        first = tag[0]
        if first == "o":
            value = parse_tlv(value_bytes)
        elif first in ("t", "p"):
            value = value_bytes.decode("utf-16-be", errors="replace")
        elif first == "b":
            value = bool(value_bytes[0]) if value_bytes else False
        elif first == "u":
            value = struct.unpack(">I", value_bytes)[0] if len(value_bytes) == 4 else value_bytes
        else:
            value = value_bytes
        entries.append((tag, value))
    return entries


def serialize_tlv(entries: list[tuple[str, object]]) -> bytes:
    """Inversul lui parse_tlv - reconstruieste bytes-ii originali dintr-o lista
    de (tag, valoare), eventual modificata."""
    out = bytearray()
    for tag, value in entries:
        first = tag[0]
        if first == "o":
            value_bytes = serialize_tlv(value)
        elif first in ("t", "p"):
            value_bytes = value.encode("utf-16-be")
        elif first == "b":
            value_bytes = b"\x01" if value else b"\x00"
        elif first == "u":
            value_bytes = struct.pack(">I", value) if isinstance(value, int) else value
        else:
            value_bytes = value
        out += tag.encode("ascii")
        out += struct.pack(">I", len(value_bytes))
        out += value_bytes
    return bytes(out)


def rewrite_paths(entries: list[tuple[str, object]], field_tag: str,
                   new_path_by_old: dict[str, str]) -> list[tuple[str, object]]:
    """Returneaza o copie a entries cu valorile campului `field_tag` (ex: 'pfil'
    in database V2, 'ptrk' in .crate) inlocuite conform new_path_by_old, acolo
    unde vechea valoare are o inlocuire cunoscuta."""
    new_entries = []
    for tag, value in entries:
        if tag == "otrk":
            new_value = []
            for t2, v2 in value:
                if t2 == field_tag and v2 in new_path_by_old:
                    new_value.append((t2, new_path_by_old[v2]))
                else:
                    new_value.append((t2, v2))
            new_entries.append((tag, new_value))
        else:
            new_entries.append((tag, value))
    return new_entries


def rewrite_track_fields(entries: list[tuple[str, object]], path_field: str,
                          edits_by_path: dict[str, dict[str, object]]) -> list[tuple[str, object]]:
    """Pentru fiecare otrk identificat dupa `path_field` (ex: 'pfil'), suprascrie
    campurile date in edits_by_path[cale] (ex: {'tsng': 'Titlu nou'}), adaugand
    tag-ul daca lipsea complet. Spre deosebire de rewrite_paths, identificarea
    se face dupa calea track-ului, nu dupa vechea valoare a campului - necesar
    pentru campuri ne-unice ca artist/titlu (multe track-uri au aceeasi valoare,
    adesea goala)."""
    new_entries = []
    for tag, value in entries:
        if tag != "otrk":
            new_entries.append((tag, value))
            continue
        path = next((v2 for t2, v2 in value if t2 == path_field), None)
        fields = edits_by_path.get(path) if path else None
        if not fields:
            new_entries.append((tag, value))
            continue

        new_value = []
        remaining = dict(fields)
        for t2, v2 in value:
            if t2 in remaining:
                new_value.append((t2, remaining.pop(t2)))
            else:
                new_value.append((t2, v2))
        for t2, v2 in remaining.items():   # campuri care nu existau deloc in track
            new_value.append((t2, v2))
        new_entries.append((tag, new_value))
    return new_entries


def _get(entries: list[tuple[str, object]], tag: str):
    for t, v in entries:
        if t == tag:
            return v
    return None


@dataclass
class Track:
    abs_path: str          # cale absoluta reala pe disk (macOS), ex: /Volumes/PortableSSD/...
    raw_path: str           # cum e stocat in Serato (fara "/" la inceput)
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    file_type: str | None = None
    size: str | None = None

    @property
    def exists(self) -> bool:
        return Path(self.abs_path).exists()


def _raw_to_abs(raw_path: str, volume_root: str) -> str:
    """Serato stochează căile relativ la rădăcina volumului pe care se află
    folderul _Serato_ (fie discul de boot -> volume_root="/", fie un volum
    extern -> volume_root="/Volumes/NumeDrive")."""
    return str(Path(volume_root) / raw_path)


def parse_database(db_path: str | Path, volume_root: str = "/") -> dict[str, Track]:
    """Parseaza `database V2`. Returneaza dict raw_path -> Track (toate track-urile cunoscute de Serato).

    volume_root: radacina fata de care sunt relative caile (implicit "/" pentru
    biblioteca de pe discul de boot; foloseste "/Volumes/NumeDrive" pentru o
    biblioteca Serato aflata pe un volum extern).
    """
    data = Path(db_path).read_bytes()
    entries = parse_tlv(data)
    tracks: dict[str, Track] = {}
    for tag, value in entries:
        if tag != "otrk":
            continue
        raw_path = _get(value, "pfil")
        if not raw_path:
            continue
        tracks[raw_path] = Track(
            abs_path=_raw_to_abs(raw_path, volume_root),
            raw_path=raw_path,
            title=_get(value, "tsng"),
            artist=_get(value, "tart"),
            album=_get(value, "talb"),
            genre=_get(value, "tgen"),
            file_type=_get(value, "ttyp"),
            size=_get(value, "tsiz"),
        )
    return tracks


def crate_name_to_hierarchy(filename: str) -> list[str]:
    """'Others%%Crema%%Hip Hop & R&B.crate' -> ['Others', 'Crema', 'Hip Hop & R&B']"""
    stem = Path(filename).stem
    return stem.split("%%")


def parse_crate(crate_path: str | Path) -> list[str]:
    """Parseaza un fisier .crate. Returneaza lista de raw_path (fara '/')."""
    data = Path(crate_path).read_bytes()
    entries = parse_tlv(data)
    paths = []
    for tag, value in entries:
        if tag != "otrk":
            continue
        raw_path = _get(value, "ptrk")
        if raw_path:
            paths.append(raw_path)
    return paths


@dataclass
class Crate:
    hierarchy: list[str]     # ex: ['Others', 'Crema', 'Hip Hop & R&B']
    file_path: Path
    raw_paths: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return " / ".join(self.hierarchy)


def load_subcrates(serato_dir: str | Path) -> list[Crate]:
    subcrates_dir = Path(serato_dir) / "Subcrates"
    crates = []
    if not subcrates_dir.is_dir():
        return crates
    for f in sorted(subcrates_dir.glob("*.crate")):
        hierarchy = crate_name_to_hierarchy(f.name)
        raw_paths = parse_crate(f)
        crates.append(Crate(hierarchy=hierarchy, file_path=f, raw_paths=raw_paths))
    return crates
