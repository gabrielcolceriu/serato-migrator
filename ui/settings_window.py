"""Settings window (Cmd+,). One pane for now; values persist via ui.state."""
from __future__ import annotations

import objc
from AppKit import (
    NSWindow, NSWindowController, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSBackingStoreBuffered, NSButton, NSButtonTypeSwitch, NSPopUpButton,
    NSTextField, NSFont, NSView, NSMakeRect as _mr,
)
from Foundation import NSObject, NSMakeRect

from . import state


def _check(title, key):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 20))
    b.setButtonType_(NSButtonTypeSwitch)
    b.setTitle_(title)
    b.setState_(1 if state.get_bool(key) else 0)
    b._key = key
    return b


class SettingsWindowController(NSWindowController):
    def initDefault(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 420, 240), style, NSBackingStoreBuffered, False)
        win.setTitle_("Setări")
        win.center()
        self = objc.super(SettingsWindowController, self).initWithWindow_(win)
        if self is None:
            return None
        v = win.contentView()
        y = 200
        self._checks = []
        for title, key in (
            ("Creează backup înainte de migrare", state.K_BACKUP_BEFORE_MIGRATE),
            ("Normalizează numele SCRISE CU MAJUSCULE (implicit)", state.K_DEFAULT_NORMALIZE_NAMES),
            ("Arată confirmările pentru acțiunile non-distructive", state.K_SHOW_NONDESTRUCTIVE_CONFIRMS),
        ):
            c = _check(title, key)
            c.setFrame_(NSMakeRect(24, y, 372, 20))
            c.setTarget_(self)
            c.setAction_(b"toggled:")
            v.addSubview_(c)
            self._checks.append(c)
            y -= 30

        lbl = NSTextField.labelWithString_("Aspect")
        lbl.setFrame_(NSMakeRect(24, y - 6, 80, 20))
        v.addSubview_(lbl)
        self._appearance = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(110, y - 10, 160, 26))
        self._appearance.addItemsWithTitles_(["Sistem", "Deschis", "Închis"])
        cur = state.get(state.K_APPEARANCE) or "system"
        self._appearance.selectItemAtIndex_({"system": 0, "light": 1, "dark": 2}.get(cur, 0))
        self._appearance.setTarget_(self)
        self._appearance.setAction_(b"appearanceChanged:")
        v.addSubview_(self._appearance)
        return self

    def toggled_(self, sender):
        state.set(sender._key, bool(sender.state()))

    def appearanceChanged_(self, sender):
        state.set(state.K_APPEARANCE, ["system", "light", "dark"][sender.indexOfSelectedItem()])
        from AppKit import NSApp, NSAppearance
        idx = sender.indexOfSelectedItem()
        NSApp().setAppearance_(None if idx == 0 else NSAppearance.appearanceNamed_(
            "NSAppearanceNameAqua" if idx == 1 else "NSAppearanceNameDarkAqua"))
