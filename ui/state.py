"""Small persisted-state layer backed by NSUserDefaults (~/Library/Preferences).

Everything the UI wants to remember between launches goes through here so there
is a single, typed surface for window frame, sidebar/inspector collapse, the
selected destination, last-used folders, per-library scan timestamps, and the
Settings values.
"""
from __future__ import annotations

from Foundation import NSUserDefaults

# The app's own domain in ~/Library/Preferences (a suite named after the bundle
# id is rejected by NSUserDefaults).
_d = NSUserDefaults.standardUserDefaults()

# ---- keys -------------------------------------------------------------------
K_WINDOW_FRAME = "window.frame"
K_SIDEBAR_COLLAPSED = "sidebar.collapsed"
K_INSPECTOR_COLLAPSED = "inspector.collapsed"
K_SELECTED_DESTINATION = "nav.selected"          # sidebar destination id
K_ACTIVE_LIBRARY_ROOT = "library.active_root"
K_LAST_MIGRATION_DEST = "migrate.last_dest"
K_LAST_ORPHAN_ROOT = "orphans.last_root"
K_JOURNAL_MODE = "journal.mode"                  # "activity" | "raw"
K_JOURNAL_LEVEL = "journal.level"                # "all" | "info" | "warning" | "error"
K_SCAN_TIMESTAMPS = "library.scan_timestamps"    # {root: iso8601}

# Settings
K_BACKUP_BEFORE_MIGRATE = "settings.backup_before_migrate"
K_BACKUP_LOCATION = "settings.backup_location"   # "next_to_dest" | "ask"
K_DEFAULT_NORMALIZE_NAMES = "settings.default_normalize_names"
K_SHOW_NONDESTRUCTIVE_CONFIRMS = "settings.show_nondestructive_confirms"
K_APPEARANCE = "settings.appearance"             # "system" | "light" | "dark"

_DEFAULTS = {
    K_SIDEBAR_COLLAPSED: False,
    K_INSPECTOR_COLLAPSED: False,
    K_SELECTED_DESTINATION: "overview",
    K_JOURNAL_MODE: "activity",
    K_JOURNAL_LEVEL: "all",
    K_BACKUP_BEFORE_MIGRATE: True,
    K_BACKUP_LOCATION: "next_to_dest",
    K_DEFAULT_NORMALIZE_NAMES: True,
    K_SHOW_NONDESTRUCTIVE_CONFIRMS: True,
    K_APPEARANCE: "system",
}


def register_defaults() -> None:
    reg = {}
    for k, v in _DEFAULTS.items():
        reg[k] = v
    _d.registerDefaults_(reg)


def get(key: str, default=None):
    v = _d.objectForKey_(key)
    if v is None:
        return _DEFAULTS.get(key, default)
    return v


def get_bool(key: str, default: bool = False) -> bool:
    if _d.objectForKey_(key) is None:
        return bool(_DEFAULTS.get(key, default))
    return bool(_d.boolForKey_(key))


def set(key: str, value) -> None:  # noqa: A003 - deliberate simple name
    if isinstance(value, bool):
        _d.setBool_forKey_(value, key)
    else:
        _d.setObject_forKey_(value, key)


def get_dict(key: str) -> dict:
    v = _d.dictionaryForKey_(key)
    return dict(v) if v else {}


def set_dict(key: str, value: dict) -> None:
    _d.setObject_forKey_(dict(value), key)
