"""Entry point. The native macOS (AppKit / PyObjC) UI lives in the `ui` package;
the previous Tkinter implementation is kept at `legacy/gui_tk.py` for reference
and rollback during the UI redesign (see docs/UI_REDESIGN_2026.md).
"""
from __future__ import annotations

APP_VERSION = "0.7.1"


def _build_app_icon(size: int = 128):
    """Kept for `build_icon.py`; delegates to the procedural drawing in the
    legacy module (imported lazily so the Tk dependency isn't pulled in at
    normal runtime)."""
    from legacy.gui_tk import _build_app_icon as _f
    return _f(size)


def main() -> None:
    from ui.app import main as _run
    _run()


if __name__ == "__main__":
    main()
