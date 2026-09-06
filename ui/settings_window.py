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
    b.setTag_(0)
    return b


class SettingsWindowController(NSWindowController):
    def initDefault(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 460, 300), style, NSBackingStoreBuffered, False)
        win.setTitle_("Setări")
        win.center()
        self = objc.super(SettingsWindowController, self).initWithWindow_(win)
        if self is None:
            return None
        v = win.contentView()
        y = 258
        self._keys = [
            state.K_BACKUP_BEFORE_MIGRATE,
            state.K_DEFAULT_NORMALIZE_NAMES,
            state.K_SHOW_NONDESTRUCTIVE_CONFIRMS,
        ]
        for tag, (title, key) in enumerate((
            ("Creează backup înainte de migrare", state.K_BACKUP_BEFORE_MIGRATE),
            ("Normalizează numele SCRISE CU MAJUSCULE (implicit)", state.K_DEFAULT_NORMALIZE_NAMES),
            ("Arată confirmările pentru acțiunile non-distructive", state.K_SHOW_NONDESTRUCTIVE_CONFIRMS),
        ), start=1):
            c = _check(title, key)
            c.setFrame_(NSMakeRect(24, y, 372, 20))
            c.setTag_(tag)
            c.setTarget_(self)
            c.setAction_(b"toggled:")
            v.addSubview_(c)
            y -= 30

        # backup location
        bl = NSTextField.labelWithString_("Locație backup")
        bl.setFrame_(NSMakeRect(24, y - 6, 120, 20))
        v.addSubview_(bl)
        _bl = state.get(state.K_BACKUP_LOCATION) or "next_to_dest"
        self._backupLoc = NSTextField.labelWithString_(
            "Lângă destinație" if _bl in ("next_to_dest", "ask") else _bl)
        self._backupLoc.setFrame_(NSMakeRect(150, y - 6, 210, 20))
        self._backupLoc.setLineBreakMode_(4)
        v.addSubview_(self._backupLoc)
        pick = NSButton.alloc().initWithFrame_(NSMakeRect(360, y - 10, 80, 26))
        pick.setTitle_("Alege…")
        pick.setBezelStyle_(1)
        pick.setTarget_(self)
        pick.setAction_(b"pickBackupLoc:")
        v.addSubview_(pick)
        y -= 36

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
        i = sender.tag() - 1
        if 0 <= i < len(self._keys):
            state.set(self._keys[i], bool(sender.state()))

    def pickBackupLoc_(self, sender):
        from AppKit import NSOpenPanel
        p = NSOpenPanel.openPanel()
        p.setCanChooseDirectories_(True)
        p.setCanChooseFiles_(False)
        p.setPrompt_("Alege")
        if p.runModal() == 1:
            path = p.URLs()[0].path()
            state.set(state.K_BACKUP_LOCATION, path)
            self._backupLoc.setStringValue_(path)

    def appearanceChanged_(self, sender):
        state.set(state.K_APPEARANCE, ["system", "light", "dark"][sender.indexOfSelectedItem()])
        from AppKit import NSApp, NSAppearance
        idx = sender.indexOfSelectedItem()
        NSApp().setAppearance_(None if idx == 0 else NSAppearance.appearanceNamed_(
            "NSAppearanceNameAqua" if idx == 1 else "NSAppearanceNameDarkAqua"))
