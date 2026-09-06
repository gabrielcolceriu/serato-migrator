"""Redenumire în bloc a fișierelor audio dintr-o bibliotecă Serato, cu
rescrierea căilor în `database V2` și în fiecare `.crate` care le referă — ca
Serato să găsească fișierele la noul nume fără „Locate Missing Files".

Reguli de normalizare pure (str -> str pe numele fișierului). Nimic nu se scrie
fără un plan calculat întâi (`plan_renames`) și un apel explicit
(`execute_renames`), care face backup la `_Serato_` înainte de orice.

Nu modifică `serato_db` / `scanner` / `copier` / `metadata_editor` — doar
folosește primitivele TLV din `serato_db`.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import serato_db
from copier import normalize_caps_filename

_DB_ESSENTIAL_FILES = ("database V2", "neworder.pref", "collapsed.pref")
_DB_ESSENTIAL_DIRS = ("Subcrates", "SmartCrates", "Smart Crates")

_LEADING_NUM_RE = re.compile(r"^\s*\d{1,3}\s*[.\-)_]\s*")
_MULTISPACE_RE = re.compile(r"\s{2,}")
_JUNK_BRACKET_RE = re.compile(
    r"\s*[\(\[]\s*[^)\]]*?"
    r"(?:www\.|https?:|official|lyric|visualizer|audio only|"
    r"\bhd\b|\bhq\b|\b4k\b|\b1080p\b|free download|download here|"
    r"videoclip|video oficial|original mix\s*\]|extended mix\s*\])"
    r"[^)\]]*[\)\]]",
    re.IGNORECASE,
)


def _fix_caps(stem: str) -> str:
    # normalize_caps_filename lucrează pe nume cu extensie; îi dăm un ".x" fals
    return normalize_caps_filename(stem + ".x")[:-2]


def _strip_leading_num(stem: str) -> str:
    return _LEADING_NUM_RE.sub("", stem)


def _underscores_to_spaces(stem: str) -> str:
    return stem.replace("_", " ")


def _strip_junk_brackets(stem: str) -> str:
    return _JUNK_BRACKET_RE.sub("", stem)


def _tidy_spaces(stem: str) -> str:
    s = _MULTISPACE_RE.sub(" ", stem).strip()
    # normalize a dash to " - " ONLY when it is already used as a separator
    # (space on at least one side) — never touch hyphenated words like DA-I / hip-hop
    s = re.sub(r"\s+-\s*|\s*-\s+", " - ", s)
    return s.strip(" -_.")


# cheie -> (etichetă UI, funcție, ordine)
RULES = [
    ("underscores", "Înlocuiește _ cu spațiu", _underscores_to_spaces),
    ("tracknum", "Elimină numărul de la început (01 - , 01. )", _strip_leading_num),
    ("brackets", "Elimină etichete de tip (official video) / [www…]", _strip_junk_brackets),
    ("caps", "MAJUSCULE → Title Case", _fix_caps),
    ("spaces", "Curăță spații multiple și separatori", _tidy_spaces),
]
RULE_LABELS = {k: lbl for k, lbl, _fn in RULES}


def normalize_name(filename: str, rule_keys) -> str:
    """Aplică regulile bifate, în ordinea din RULES, pe numele fișierului
    (păstrează extensia)."""
    stem, ext = os.path.splitext(filename)
    for key, _lbl, fn in RULES:
        if key in rule_keys:
            stem = fn(stem)
    stem = stem.strip()
    return (stem + ext) if stem else filename


@dataclass
class RenameOp:
    raw_path: str          # calea Serato curentă (relativă la volume_root)
    old_abs: Path
    new_abs: Path
    new_raw: str


@dataclass
class RenamePlan:
    ops: list[RenameOp] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (nume, motiv)


@dataclass
class RenameResult:
    renamed: int
    failed: list[tuple[str, str]]
    backup_dir: Path
    db_updated: bool
    crates_updated: int


def plan_renames(lib, rule_keys) -> RenamePlan:
    """Construiește planul: pentru fiecare track calculează numele nou; sare
    peste cele nemodificate, cele lipsă de pe disc și coliziunile."""
    plan = RenamePlan()
    vol = Path(lib.volume_root)
    keys = set(rule_keys)
    if not keys:
        return plan

    planned_dests: set[Path] = set()
    for raw_path in list(lib.tracks):
        old_abs = vol / raw_path
        name = old_abs.name
        new_name = normalize_name(name, keys)
        if new_name == name:
            continue
        if not old_abs.is_file():
            plan.skipped.append((name, "fișier lipsă pe disc"))
            continue
        new_abs = old_abs.with_name(new_name)
        if new_abs == old_abs:
            continue
        if new_abs in planned_dests or (new_abs.exists() and new_abs != old_abs):
            plan.skipped.append((name, f"coliziune cu „{new_name}”"))
            continue
        planned_dests.add(new_abs)
        new_raw = str(Path(raw_path).with_name(new_name))
        plan.ops.append(RenameOp(raw_path=raw_path, old_abs=old_abs,
                                 new_abs=new_abs, new_raw=new_raw))
    return plan


def _backup_serato(serato_dir: Path) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    backup_dir = serato_dir.with_name(f"_Serato_ (backup redenumire {stamp})")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for nm in _DB_ESSENTIAL_FILES:
        src = serato_dir / nm
        if src.is_file():
            shutil.copy2(src, backup_dir / nm)
    for d in _DB_ESSENTIAL_DIRS:
        src = serato_dir / d
        if src.is_dir():
            shutil.copytree(src, backup_dir / d)
    return backup_dir


def execute_renames(lib, plan: RenamePlan, progress_cb=None) -> RenameResult:
    """Backup `_Serato_` -> redenumește fișierele pe disc -> rescrie `pfil` în
    `database V2` și `ptrk` în fiecare `.crate` afectat. Rescrierea DB se face
    doar pentru redenumirile care au reușit fizic."""
    serato_dir = Path(lib.serato_dir)
    backup_dir = _backup_serato(serato_dir)

    mapping: dict[str, str] = {}   # raw_path vechi -> raw_path nou
    failed: list[tuple[str, str]] = []
    total = len(plan.ops)
    for i, op in enumerate(plan.ops, 1):
        try:
            op.new_abs.parent.mkdir(parents=True, exist_ok=True)
            os.rename(op.old_abs, op.new_abs)
            mapping[op.raw_path] = op.new_raw
        except OSError as e:
            failed.append((op.old_abs.name, str(e)))
        if progress_cb:
            progress_cb(i, total)

    db_updated = False
    if mapping:
        db_path = serato_dir / "database V2"
        if db_path.is_file():
            entries = serato_db.parse_tlv(db_path.read_bytes())
            entries = serato_db.rewrite_paths(entries, "pfil", mapping)
            db_path.write_bytes(serato_db.serialize_tlv(entries))
            db_updated = True

    crates_updated = 0
    subcrates = serato_dir / "Subcrates"
    if mapping and subcrates.is_dir():
        for cf in sorted(subcrates.glob("*.crate")):
            raw = cf.read_bytes()
            entries = serato_db.parse_tlv(raw)
            new_entries = serato_db.rewrite_paths(entries, "ptrk", mapping)
            new_bytes = serato_db.serialize_tlv(new_entries)
            if new_bytes != raw:
                cf.write_bytes(new_bytes)
                crates_updated += 1

    return RenameResult(renamed=len(mapping), failed=failed,
                        backup_dir=backup_dir, db_updated=db_updated,
                        crates_updated=crates_updated)
