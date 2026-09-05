"""UI-16 — Library Health + Crate Health.

Everything here is *derived* from data the app already has (a SeratoLibrary and
its scan state). No new persisted model beyond the per-library "last scan"
timestamp, and no change to the logic modules. Each warning state carries the
destination to jump to when the user clicks it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from . import state


@dataclass(frozen=True)
class Health:
    key: str            # scanning | missing | metadata | db | ok
    symbol: str         # SF Symbol name
    label: str          # icon + text is the rule; text here
    target: str | None  # sidebar destination to navigate to, or None


_OK = Health("ok", "checkmark.circle", "Biblioteca este în regulă", None)


def library_health(lib, *, scanning: bool = False) -> Health:
    if scanning:
        return Health("scanning", "arrow.triangle.2.circlepath", "Se scanează", None)
    if lib is None:
        return Health("db", "exclamationmark.octagon", "Nicio bibliotecă", None)
    try:
        db = lib.serato_dir / "database V2"
        if not db.is_file():
            return Health("db", "exclamationmark.octagon",
                          "Problemă bază de date (database V2 lipsește)", "libraries")
    except Exception:
        return Health("db", "exclamationmark.octagon", "Problemă bază de date", "libraries")

    missing = len(lib.missing_tracks)
    if missing:
        return Health("missing", "exclamationmark.triangle",
                      f"{missing} fișiere lipsă", "crates")

    incomplete = sum(1 for t in lib.tracks.values()
                     if not (t.artist or "").strip() or not (t.title or "").strip())
    if incomplete:
        return Health("metadata", "exclamationmark.triangle",
                      f"Metadata incompletă la {incomplete} track-uri", "metadata")
    return _OK


def crate_missing_count(lib, crate) -> int:
    if lib is None:
        return 0
    from pathlib import Path
    vol = Path(lib.volume_root)
    return sum(1 for rp in crate.raw_paths if not (vol / rp).is_file())


# ---- per-library "last scan" timestamp -------------------------------------
def mark_scanned(root: str) -> None:
    ts = state.get_dict(state.K_SCAN_TIMESTAMPS)
    ts[str(root)] = datetime.now(timezone.utc).isoformat()
    state.set_dict(state.K_SCAN_TIMESTAMPS, ts)


def last_scan_text(root: str) -> str:
    ts = state.get_dict(state.K_SCAN_TIMESTAMPS).get(str(root))
    if not ts:
        return "Niciodată scanată"
    try:
        dt = datetime.fromisoformat(ts).astimezone()
    except Exception:
        return "—"
    now = datetime.now().astimezone()
    if dt.date() == now.date():
        return f"astăzi, {dt:%H:%M}"
    if (now.date() - dt.date()).days == 1:
        return f"ieri, {dt:%H:%M}"
    return f"{dt:%d.%m.%Y, %H:%M}"
