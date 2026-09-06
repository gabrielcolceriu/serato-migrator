"""UI-22 — ⌘K command palette.

A borderless floating panel: a search field over a short results list.
Type to filter, ↑/↓ to move, Return runs, Esc closes. Commands are plain
(title, callable) pairs supplied by the app delegate — navigation to every
screen plus the few global actions.
"""
from __future__ import annotations

import objc
from AppKit import (
    NSPanel, NSWindowController, NSView, NSSearchField, NSTableView,
    NSTableColumn, NSScrollView, NSVisualEffectView, NSColor,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered, NSFont,
)
from Foundation import NSObject, NSMakeRect

from . import theme


class CommandPaletteController(NSWindowController):
    def initWithApp_(self, app):
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 520, 340),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        panel.setMovableByWindowBackground_(True)
        panel.setHidesOnDeactivate_(True)
        panel.setLevel_(3)  # floating
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())

        self = objc.super(CommandPaletteController, self).initWithWindow_(panel)
        if self is None:
            return None
        self._app = app
        self._all = []      # (title, callable)
        self._shown = []

        bg = NSVisualEffectView.alloc().initWithFrame_(((0, 0), (520, 340)))
        bg.setMaterial_(18)  # HUD-ish window material
        bg.setState_(1)
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(12.0)
        panel.setContentView_(bg)

        self._field = NSSearchField.alloc().initWithFrame_(NSMakeRect(16, 292, 488, 32))
        self._field.setFont_(NSFont.systemFontOfSize_(16))
        self._field.setFocusRingType_(1)
        self._field.setPlaceholderString_("Comandă…")
        self._field.setTarget_(self)
        self._field.setAction_(b"filter:")
        (self._field.cell()).setSendsSearchStringImmediately_(True)
        bg.addSubview_(self._field)

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(8, 8, 504, 276))
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(True)
        self._tv = NSTableView.alloc().initWithFrame_(scroll.bounds())
        col = NSTableColumn.alloc().initWithIdentifier_("c")
        col.setWidth_(480)
        self._tv.addTableColumn_(col)
        self._tv.setHeaderView_(None)
        self._tv.setRowHeight_(26.0)
        self._tv.setBackgroundColor_(NSColor.clearColor())
        self._tv.setDataSource_(self)
        self._tv.setDelegate_(self)
        self._tv.setTarget_(self)
        self._tv.setDoubleAction_(b"runSelected:")
        scroll.setDocumentView_(self._tv)
        bg.addSubview_(scroll)
        return self

    # ---- public ----
    @objc.python_method
    def present(self, commands):
        self._all = list(commands)
        self._field.setStringValue_("")
        self._apply_("")
        win = self.window()
        main = self._app._wc.window() if getattr(self._app, "_wc", None) else None
        if main is not None:
            f = main.frame()
            win.setFrameOrigin_((f.origin.x + (f.size.width - 520) / 2,
                                 f.origin.y + f.size.height - 420))
        else:
            win.center()
        win.makeKeyAndOrderFront_(None)
        win.makeFirstResponder_(self._field)

    # ---- filtering ----
    def filter_(self, sender):
        self._apply_(self._field.stringValue())

    @objc.python_method
    def _apply_(self, q):
        q = (q or "").strip().lower()
        self._shown = [c for c in self._all if not q or q in c[0].lower()]
        self._tv.reloadData()
        if self._shown:
            from Foundation import NSIndexSet
            self._tv.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(0), False)

    # ---- table ----
    def numberOfRowsInTableView_(self, tv):
        return len(self._shown)

    def tableView_objectValueForTableColumn_row_(self, tv, col, row):
        return self._shown[row][0]

    def runSelected_(self, sender):
        row = self._tv.selectedRow()
        if 0 <= row < len(self._shown):
            fn = self._shown[row][1]
            self.window().orderOut_(None)
            try:
                fn()
            except Exception:
                pass

    # ---- key handling from the search field ----
    def control_textView_doCommandBySelector_(self, control, tv, sel):
        s = sel if isinstance(sel, str) else str(sel)
        if s == "cancelOperation:":
            self.window().orderOut_(None)
            return True
        if s == "insertNewline:":
            self.runSelected_(None)
            return True
        if s in ("moveDown:", "moveUp:"):
            n = len(self._shown)
            if not n:
                return True
            cur = self._tv.selectedRow()
            nxt = (cur + (1 if s == "moveDown:" else -1)) % n
            from Foundation import NSIndexSet
            self._tv.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(nxt), False)
            self._tv.scrollRowToVisible_(nxt)
            return True
        return False
