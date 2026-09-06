"""Screen view-controllers for the UI-01 shell.

Every screen is wired to the existing toolkit-free logic (`scanner`, `copier`,
`metadata_editor`). Visual polish, inspectors, health badges, guided flows and
empty-state design are the subject of UI-02..UI-23; this module's job is a
native, runnable baseline with no placeholder / TODO handlers.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

import objc
from AppKit import (
    NSColor, NSFont, NSTextField, NSView, NSViewController, NSScrollView,
    NSTableView, NSTableColumn, NSButton, NSBezelStyleRounded, NSStackView,
    NSUserInterfaceLayoutOrientationVertical,
    NSUserInterfaceLayoutOrientationHorizontal, NSTextView, NSOpenPanel,
    NSProgressIndicator, NSProgressIndicatorBarStyle, NSSearchField,
    NSImageView, NSPopUpButton, NSAlert, NSAttributedString,
    NSForegroundColorAttributeName, NSFontAttributeName, NSLayoutConstraint,
    NSSwitchButton,
)
from Foundation import NSObject, NSMakeRect, NSDate, NSIndexSet, NSNotFound as _NSNotFound
from PyObjCTools import AppHelper

import scanner
import copier
import metadata_editor

from . import theme

_AUTOSIZE = (1 << 1) | (1 << 4)  # width | height


def _label(text, *, bold=False, secondary=False, size=13):
    """Thin bridge to the design-system label. `size` still accepted for the
    few call sites that pass an explicit point size; otherwise a text style is
    inferred so light/dark + Dynamic-Type-ish scaling come for free."""
    if size >= 22:
        style = "largeTitle"
    elif size >= 17:
        style = "title2"
    elif size >= 15:
        style = "headline"
    elif secondary or size <= 11:
        style = "caption" if size <= 11 else "secondary"
    else:
        style = "body"
    tf = theme.make_label(text, style=style,
                          color=NSColor.secondaryLabelColor() if secondary else None)
    if bold and style in ("body", "secondary", "caption"):
        tf.setFont_(NSFont.systemFontOfSize_weight_(size, 0.4))  # semibold-ish
    return tf


def _button(title, target, action):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 140, 28))
    b.setBezelStyle_(NSBezelStyleRounded)
    b.setTitle_(title)
    b.setTarget_(target)
    b.setAction_(action)
    return b


def _spacer(height):
    v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, height))
    v.setTranslatesAutoresizingMaskIntoConstraints_(False)
    from AppKit import NSLayoutConstraint
    c = NSLayoutConstraint.constraintWithItem_attribute_relatedBy_toItem_attribute_multiplier_constant_(
        v, 8, 0, None, 0, 1.0, float(height))  # attribute 8 = height
    v.addConstraint_(c)
    return v


def _alert(message, *, informative=None, style=0):
    a = NSAlert.alloc().init()
    a.setMessageText_(message)
    if informative:
        a.setInformativeText_(informative)
    a.setAlertStyle_(style)
    a.runModal()


import re as _re


def _sort_key(value, numeric):
    if numeric:
        m = _re.search(r"-?[\d][\d.,]*", str(value))
        if not m:
            return float("-inf")
        raw = m.group().replace(".", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return float("-inf")
    return str(value).lower()


class _Rows(NSObject):
    """Generic NSTableView data source over a list of tuples + column keys.

    Click-to-sort headers: declare the numeric column identifiers via
    ``setNumericColumns_`` so `23.100` sorts as a number, not a string.
    """

    def initWithColumns_(self, columns):
        self = objc.super(_Rows, self).init()
        if self is None:
            return None
        self._columns = list(columns)   # list of identifiers
        self._data = []                 # list[tuple]
        self._numeric = set()
        self._sort = None               # (identifier, ascending)
        return self

    def setNumericColumns_(self, idents):
        self._numeric = set(idents)

    def setData_(self, data):
        self._data = list(data)
        self._applySort()

    def data(self):
        return self._data

    @objc.python_method
    def _applySort(self):
        if not self._sort:
            return
        ident, asc = self._sort
        try:
            i = self._columns.index(ident)
        except ValueError:
            return
        numeric = ident in self._numeric
        self._data.sort(key=lambda row: _sort_key(row[i], numeric),
                        reverse=not asc)

    def numberOfRowsInTableView_(self, tv):
        return len(self._data)

    def tableView_objectValueForTableColumn_row_(self, tv, col, row):
        try:
            i = self._columns.index(col.identifier())
            return str(self._data[row][i])
        except Exception:
            return ""

    def tableView_sortDescriptorsDidChange_(self, tv, old):
        sd = tv.sortDescriptors()
        if sd and len(sd):
            d = sd[0]
            self._sort = (str(d.key()), bool(d.ascending()))
            self._applySort()
            tv.reloadData()


def _table(columns, titles, widths, *, numeric=(), sortable=True):
    from Foundation import NSSortDescriptor
    tv = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 400))
    tv.setRowSizeStyle_(1)
    tv.setAllowsMultipleSelection_(True)
    tv.setUsesAlternatingRowBackgroundColors_(False)
    tv.setGridStyleMask_(0)
    tv.setIntercellSpacing_((3, 2))
    try:
        tv.setStyle_(1)  # NSTableViewStyleFullWidth — plain, no heavy chrome
    except Exception:
        pass
    right = {"Track-uri", "Disponibile", "Lipsă", "Crate-uri", "Mărime"}
    # the widest text column absorbs slack; numeric columns never do
    _fill = max((i for i, t in enumerate(titles) if t not in right),
                key=lambda i: widths[i], default=len(columns) - 1)
    for idx, (ident, title, w) in enumerate(zip(columns, titles, widths)):
        c = NSTableColumn.alloc().initWithIdentifier_(ident)
        c.setTitle_(title)
        c.setWidth_(w)
        c.setMinWidth_(28)
        c.setResizingMask_(2 if idx == _fill else 1)
        c.headerCell().setStringValue_(title)
        if sortable:
            c.setSortDescriptorPrototype_(
                NSSortDescriptor.sortDescriptorWithKey_ascending_(ident, True))
        if title in right or ident in numeric:
            try:
                c.headerCell().setAlignment_(2)  # right
                c.dataCell().setAlignment_(2)
                c.dataCell().setFont_(
                    NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0))
            except Exception:
                pass
        tv.addTableColumn_(c)
    ds = _Rows.alloc().initWithColumns_(columns)
    if numeric:
        ds.setNumericColumns_(numeric)
    tv.setDataSource_(ds)
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 400))
    scroll.setDocumentView_(tv)
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(0)  # no outer border (HIG)
    scroll.setDrawsBackground_(False)
    scroll.setAutoresizingMask_(_AUTOSIZE)
    return tv, ds, scroll


class BaseScreen(NSViewController):
    def initWithDelegate_(self, delegate):
        self = objc.super(BaseScreen, self).init()
        if self is None:
            return None
        self._app = delegate
        return self

    def loadView(self):
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 900, 620))
        v.setAutoresizingMask_(_AUTOSIZE)
        self.setView_(v)
        self.build_(v)

    @objc.python_method
    def build_(self, v):
        pass

    @objc.python_method
    def _headerInto_title_subtitle_(self, v, title, subtitle):
        t = _label(title, bold=True, size=22)
        t.setFrame_(NSMakeRect(24, v.bounds().size.height - 52, 700, 30))
        t.setAutoresizingMask_(1 << 3)  # min-y margin flexible -> stays at top
        v.addSubview_(t)
        if subtitle:
            s = _label(subtitle, secondary=True)
            s.setFrame_(NSMakeRect(24, v.bounds().size.height - 74, 700, 18))
            s.setAutoresizingMask_(1 << 3)
            v.addSubview_(s)

    @objc.python_method
    def _bodyContainerIn_(self, v, top=92):
        c = NSView.alloc().initWithFrame_(
            NSMakeRect(24, 16, v.bounds().size.width - 48, v.bounds().size.height - top - 16))
        c.setAutoresizingMask_(_AUTOSIZE)
        v.addSubview_(c)
        return c


# ------------------------------------------------------------------- Overview
def _link(title, target, action):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 20))
    b.setBordered_(False)
    b.setButtonType_(7)  # momentary change
    attrs = {NSForegroundColorAttributeName: NSColor.linkColor(),
             NSFontAttributeName: NSFont.systemFontOfSize_(13)}
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, attrs))
    b.setTarget_(target)
    b.setAction_(action)
    b.setContentHuggingPriority_forOrientation_(251, 0)
    return b


class OverviewScreen(BaseScreen):
    def build_(self, v):
        self._stack = NSStackView.alloc().initWithFrame_(NSMakeRect(0, 0, v.bounds().size.width, v.bounds().size.height))
        self._stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        self._stack.setAlignment_(1)  # leading
        self._stack.setSpacing_(10)
        self._stack.setEdgeInsets_((20, 28, 28, 28))
        self._stack.setAutoresizingMask_(_AUTOSIZE)
        v.addSubview_(self._stack)
        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

    def refresh(self):
        self._app.rescanLibraries_(None)

    def render(self):
        from . import health as _health
        for sub in list(self._stack.arrangedSubviews()):
            self._stack.removeArrangedSubview_(sub)
            sub.removeFromSuperview()
        add = self._stack.addArrangedSubview_

        lib = self._app.activeLibrary()
        if lib is None:
            add(theme.make_label("Nu a fost detectată nicio bibliotecă Serato.", style="title2"))
            add(theme.make_label("Conectează un volum cu un folder _Serato_ sau alege manual unul.",
                                 style="secondary"))
            add(_spacer(8))
            add(_button("Alege bibliotecă…", self, b"chooseLibrary:"))
            return

        libs = self._app.libraries()
        if len(libs) > 1:
            row = NSStackView.alloc().init()
            row.setSpacing_(6)
            row.addArrangedSubview_(theme.make_label("Bibliotecă activă:", style="secondary"))
            pop = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 24))
            pop.addItemsWithTitles_([l.name for l in libs])
            try:
                pop.selectItemAtIndex_([str(l.volume_root) for l in libs].index(str(lib.volume_root)))
            except ValueError:
                pass
            pop.setTarget_(self)
            pop.setAction_(b"switchLibrary:")
            self._pop = pop
            row.addArrangedSubview_(pop)
            add(row)
            add(_spacer(4))

        add(theme.make_label(lib.name, style="largeTitle"))
        add(theme.make_label(str(lib.volume_root), style="secondary"))
        add(_spacer(6))

        h = _health.library_health(lib, scanning=self._app.isBusy())
        hrow = NSStackView.alloc().init()
        hrow.setSpacing_(6)
        sym = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, 18, 18))
        from .sidebar import _symbol
        sym.setImage_(_symbol(h.symbol, point=15))
        sym.setContentTintColor_(theme.ok_color() if h.key == "ok"
                                 else theme.warn_color() if h.key in ("missing", "metadata")
                                 else theme.secondary_label() if h.key == "scanning"
                                 else theme.error_color())
        hrow.addArrangedSubview_(sym)
        hrow.addArrangedSubview_(theme.make_label(h.label, style="headline"))
        if h.target:
            hrow.addArrangedSubview_(_link("Vezi", self, b"goHealthTarget:"))
            self._health_target = h.target
        add(hrow)
        add(_spacer(8))

        stats = NSStackView.alloc().init()
        stats.setSpacing_(28)
        for value, name in ((len(lib.present_tracks), "track-uri"),
                            (len(lib.crates), "crate-uri"),
                            (len(lib.missing_tracks), "lipsă")):
            col = NSStackView.alloc().init()
            col.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
            col.setAlignment_(1)
            col.setSpacing_(0)
            col.addArrangedSubview_(theme.make_label(theme.format_int(value), style="title2"))
            col.addArrangedSubview_(theme.make_label(name, style="caption"))
            stats.addArrangedSubview_(col)
        add(stats)
        add(_spacer(6))

        add(theme.make_label(f"Ultima scanare: {_health.last_scan_text(str(lib.volume_root))}",
                             style="caption"))
        add(_spacer(10))
        add(_button("Scanează din nou", self._app, b"rescanLibraries:"))
        add(_spacer(16))

        add(theme.make_label("Acțiuni rapide", style="headline"))
        add(_link("Migrează biblioteca", self, b"goMigrate:"))
        add(_link("Verifică fișierele", self, b"goMissing:"))
        add(_link("Analizează metadata", self, b"goMetadata:"))

    # actions
    def chooseLibrary_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setPrompt_("Alege")
        panel.setMessage_("Alege folderul rădăcină al bibliotecii (conține _Serato_)")
        if panel.runModal() == 1:
            root = panel.URLs()[0].path()
            lib = scanner.load_library_at(root)
            if lib is None:
                _alert("Nu am găsit un folder _Serato_ valid în:\n" + root)
                return
            self._app._libraries = list(self._app._libraries) + [lib]
            self._app.setActiveLibraryRoot_(root)
            self.render()

    def switchLibrary_(self, sender):
        libs = self._app.libraries()
        idx = self._pop.indexOfSelectedItem()
        if 0 <= idx < len(libs):
            self._app.setActiveLibraryRoot_(str(libs[idx].volume_root))
            self.render()

    def goHealthTarget_(self, sender):
        self._app.selectDestination_(getattr(self, "_health_target", "overview"))
        self._app._wc.selectSidebarRowForDestination_(getattr(self, "_health_target", "overview"))

    def goMigrate_(self, sender):
        self._app.selectDestination_("migrate"); self._app._wc.selectSidebarRowForDestination_("migrate")

    def goMissing_(self, sender):
        self._app.selectDestination_("crates"); self._app._wc.selectSidebarRowForDestination_("crates")

    def goMetadata_(self, sender):
        self._app.selectDestination_("metadata"); self._app._wc.selectSidebarRowForDestination_("metadata")


# ------------------------------------------------------------------- Libraries
class LibrariesScreen(BaseScreen):
    def build_(self, v):
        self._headerInto_title_subtitle_(v, "Biblioteci", "Biblioteci Serato detectate pe acest Mac")
        self._summary = _label("", secondary=True)
        self._summary.setFrame_(NSMakeRect(24, v.bounds().size.height - 100, 900, 18))
        self._summary.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._summary)

        # empty state (no library)
        self._empty = NSStackView.alloc().initWithFrame_(NSMakeRect(24, 120, 520, 140))
        self._empty.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        self._empty.setAlignment_(1)
        self._empty.setSpacing_(8)
        self._empty.setAutoresizingMask_(1 << 3)
        self._empty.addArrangedSubview_(
            theme.make_label("Nu a fost detectată nicio bibliotecă Serato.", style="title2"))
        self._empty.addArrangedSubview_(theme.make_label(
            "Conectează un volum cu un folder _Serato_ sau alege manual unul.",
            style="secondary"))
        self._empty.addArrangedSubview_(_button("Alege bibliotecă…", self, b"chooseLibrary:"))
        self._empty.setHidden_(True)
        v.addSubview_(self._empty)

        body = self._bodyContainerIn_(v, top=118)
        self._tv, self._ds, scroll = _table(
            ["name", "root", "tracks", "present", "missing", "crates", "health"],
            ["Bibliotecă", "Locație", "Track-uri", "Disponibile", "Lipsă", "Crate-uri", "Stare"],
            [150, 230, 90, 100, 70, 90, 300],
            numeric=("tracks", "present", "missing", "crates"))
        self._tv.setAllowsMultipleSelection_(False)
        self._tv.setTarget_(self)
        self._tv.setDoubleAction_(b"revealSelected:")
        self._scroll = scroll
        scroll.setFrame_(body.bounds())
        body.addSubview_(scroll)

        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"rowSelected:", "NSTableViewSelectionDidChangeNotification", self._tv)

        self._buildContextMenu()
        self._inspector = None
        self._selected_root = None
        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

    def refresh(self):
        self._app.rescanLibraries_(None)

    # ---- data ----
    @objc.python_method
    def _rowsFor(self, libs):
        from . import health as _health
        out = []
        for l in libs:
            h = _health.library_health(l, scanning=self._app.isBusy())
            mark = {"ok": "✓", "scanning": "↻"}.get(h.key, "⚠")
            out.append((l.name, str(l.volume_root),
                        theme.format_int(len(l.tracks)),
                        theme.format_int(len(l.present_tracks)),
                        theme.format_int(len(l.missing_tracks)),
                        theme.format_int(len(l.crates)),
                        f"{mark} {h.label}"))
        return out

    def render(self):
        libs = self._app.libraries()
        empty = not libs
        self._empty.setHidden_(not empty)
        self._scroll.setHidden_(empty)
        self._ds.setData_(self._rowsFor(libs))
        self._tv.reloadData()
        tot_tracks = sum(len(l.tracks) for l in libs)
        tot_present = sum(len(l.present_tracks) for l in libs)
        tot_missing = sum(len(l.missing_tracks) for l in libs)
        tot_crates = sum(len(l.crates) for l in libs)
        n = len(libs)
        self._summary.setStringValue_(
            "" if empty else
            f"{n} {'Bibliotecă' if n == 1 else 'Biblioteci'} · "
            f"{theme.format_int(tot_tracks)} Track-uri · "
            f"{theme.format_int(tot_present)} Disponibile · "
            f"{theme.format_int(tot_missing)} Lipsă · "
            f"{theme.format_int(tot_crates)} Crate-uri")
        self._restoreSelection()

    # ---- selection <-> active library + inspector ----
    @objc.python_method
    def _libAtRow(self, row):
        data = self._ds.data()
        if not (0 <= row < len(data)):
            return None
        root = data[row][1]
        for l in self._app.libraries():
            if str(l.volume_root) == root:
                return l
        return None

    @objc.python_method
    def _restoreSelection(self):
        if not self._selected_root:
            return
        data = self._ds.data()
        for i, r in enumerate(data):
            if r[1] == self._selected_root:
                self._tv.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(i), False)
                return

    def rowSelected_(self, note):
        lib = self._libAtRow(self._tv.selectedRow())
        if lib is None:
            self._selected_root = None
        else:
            self._selected_root = str(lib.volume_root)
            self._app.setActiveLibraryRoot_(str(lib.volume_root))
            self._ensureInspector().set_library(lib)
        if self._app._router is not None:
            self._app._router.refreshInspector()

    @objc.python_method
    def _ensureInspector(self):
        if self._inspector is None:
            self._inspector = LibraryInspector.alloc().initWithScreen_(self)
        return self._inspector

    def inspectorView(self):
        if not self._selected_root:
            return None
        return self._ensureInspector().view()

    # ---- context menu ----
    @objc.python_method
    def _buildContextMenu(self):
        from AppKit import NSMenu, NSMenuItem
        m = NSMenu.alloc().init()
        for title, sel in (
            ("Deschide în Finder", b"revealSelected:"),
            ("Rescanează", b"rescanAll:"),
            ("Verifică fișiere lipsă", b"verifyMissing:"),
            ("Reconstruiește baza de date", b"rebuildDB:"),
            ("Exportă baza de date…", b"exportDB:"),
        ):
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
            it.setTarget_(self)
            m.addItem_(it)
        self._tv.setMenu_(m)

    @objc.python_method
    def _contextLib(self):
        row = self._tv.clickedRow()
        if row < 0:
            row = self._tv.selectedRow()
        return self._libAtRow(row)

    # ---- actions ----
    def chooseLibrary_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setPrompt_("Alege")
        panel.setMessage_("Alege folderul rădăcină al bibliotecii (conține _Serato_)")
        if panel.runModal() != 1:
            return
        root = panel.URLs()[0].path()
        lib = scanner.load_library_at(root)
        if lib is None:
            _alert("Nu am găsit un folder _Serato_ valid în:\n" + root)
            return
        existing = [str(l.volume_root) for l in self._app.libraries()]
        if str(lib.volume_root) not in existing:
            self._app._libraries = list(self._app.libraries()) + [lib]
        self._app.setActiveLibraryRoot_(str(lib.volume_root))
        self._app.log_(f"Bibliotecă adăugată manual: {lib.name}", "info", "libraries")
        self.render()

    def revealSelected_(self, sender):
        lib = self._contextLib()
        if lib is None:
            return
        from AppKit import NSWorkspace
        from Foundation import NSURL
        NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
            [NSURL.fileURLWithPath_(str(lib.volume_root))])

    def rescanAll_(self, sender):
        self._app.rescanLibraries_(None)

    def verifyMissing_(self, sender):
        lib = self._contextLib()
        if lib is None:
            return
        if not lib.missing_tracks:
            _alert("Toate fișierele bibliotecii sunt prezente pe disc.",
                   informative=lib.name)
            return
        self._app.log_(f"Caut fișierele lipsă din {lib.name} pe volum…", "info", "libraries")
        self._app._beginBusy_("verify")

        def work():
            try:
                found, still = scanner.find_missing_elsewhere(lib)
                err = None
            except Exception:
                found, still, err = [], [], traceback.format_exc()
            AppHelper.callAfter(self._missingDone_, lib.name, found, still, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _missingDone_(self, name, found, still, err):
        self._app._endBusy_("verify")
        if err:
            self._app.log_("Eroare la verificarea fișierelor lipsă:\n" + err, "error", "libraries")
            _alert("Verificarea a eșuat (vezi Jurnal).")
            return
        self._app.log_(
            f"{name}: {len(found)} de recuperat prin redenumire, {len(still)} chiar lipsă",
            "info", "libraries")
        _alert(f"{name}",
               informative=(f"{len(found)} fișiere găsite în altă parte pe volum "
                            f"(mutate/reorganizate)\n{len(still)} chiar lipsesc de pe volum."))

    def rebuildDB_(self, sender):
        lib = self._contextLib()
        if lib is None:
            return
        a = NSAlert.alloc().init()
        a.setMessageText_(f"Reconstruiești baza de date pentru „{lib.name}”?")
        a.setInformativeText_(
            "Se face întâi un backup complet al folderului _Serato_. Baza nouă "
            "păstrează doar track-urile ale căror fișiere există fizic pe disc. "
            "Metadata per track e clonată din baza veche.")
        a.addButtonWithTitle_("Reconstruiește")
        a.addButtonWithTitle_("Anulează")
        if a.runModal() != 1000:
            return
        self._app.log_(f"Reconstruiesc baza de date pentru {lib.name}…", "info", "libraries")
        self._app._beginBusy_("rebuild")

        def work():
            try:
                res = copier.rebuild_database_from_disk(lib)
                err = None
            except Exception:
                res, err = None, traceback.format_exc()
            AppHelper.callAfter(self._rebuildDone_, lib.name, res, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _rebuildDone_(self, name, res, err):
        self._app._endBusy_("rebuild")
        if err:
            self._app.log_("Eroare la reconstrucția bazei de date:\n" + err, "error", "libraries")
            _alert("Reconstrucția a eșuat (vezi Jurnal).")
            return
        self._app.log_(
            f"{name}: bază reconstruită — {res.tracks_kept} track-uri păstrate, "
            f"{res.tracks_dropped} eliminate, {res.crates_kept} crate-uri păstrate. "
            f"Backup: {res.backup_dir}", "info", "libraries")
        _alert(f"Bază de date reconstruită pentru „{name}”",
               informative=(f"{res.tracks_kept} track-uri păstrate · "
                            f"{res.tracks_dropped} eliminate\n"
                            f"{res.crates_kept} crate-uri păstrate · "
                            f"{res.crates_dropped} eliminate\n\n"
                            f"Backup: {res.backup_dir}"))
        self._app.rescanLibraries_(None)

    def exportDB_(self, sender):
        lib = self._contextLib()
        if lib is None:
            return
        from AppKit import NSSavePanel
        panel = NSSavePanel.savePanel()
        panel.setNameFieldStringValue_(f"{lib.name} — Serato DB.zip")
        panel.setPrompt_("Exportă")
        if panel.runModal() != 1:
            return
        dest = panel.URL().path()
        self._app.log_(f"Exportă baza de date {lib.name} → {dest}", "info", "libraries")
        self._app._beginBusy_("export")

        def work():
            try:
                n = copier.export_database(lib, Path(dest))
                err = None
            except Exception:
                n, err = 0, traceback.format_exc()
            AppHelper.callAfter(self._exportDone_, dest, n, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _exportDone_(self, dest, n, err):
        self._app._endBusy_("export")
        if err:
            self._app.log_("Eroare la exportul bazei de date:\n" + err, "error", "libraries")
            _alert("Exportul a eșuat (vezi Jurnal).")
            return
        self._app.log_(f"Export gata: {n} intrări → {dest}", "info", "libraries")
        _alert("Bază de date exportată", informative=f"{n} intrări scrise în\n{dest}")


class LibraryInspector(NSObject):
    """Right-hand inspector for a selected library (UI-03)."""

    def initWithScreen_(self, screen):
        self = objc.super(LibraryInspector, self).init()
        if self is None:
            return None
        self._screen = screen
        self._app = screen._app
        self._lib = None
        self._build()
        return self

    def view(self):
        return self._container

    @objc.python_method
    def set_library(self, lib):
        from . import health as _health
        self._lib = lib
        if lib is None:
            return
        self._name.setStringValue_(lib.name)
        self._rows["Locație"].setStringValue_(str(lib.volume_root))
        self._rows["Track-uri"].setStringValue_(theme.format_int(len(lib.tracks)))
        self._rows["Disponibile"].setStringValue_(theme.format_int(len(lib.present_tracks)))
        self._rows["Lipsă"].setStringValue_(theme.format_int(len(lib.missing_tracks)))
        self._rows["Crate-uri"].setStringValue_(theme.format_int(len(lib.crates)))
        h = _health.library_health(lib, scanning=self._app.isBusy())
        mark = {"ok": "✓", "scanning": "↻"}.get(h.key, "⚠")
        self._rows["Stare"].setStringValue_(f"{mark} {h.label}")
        self._rows["Stare"].setTextColor_(
            theme.ok_color() if h.key == "ok"
            else theme.secondary_label() if h.key == "scanning"
            else theme.warn_color())
        self._rows["Ultima scanare"].setStringValue_(
            _health.last_scan_text(str(lib.volume_root)))

    @objc.python_method
    def _build(self):
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 600))
        container.setAutoresizingMask_(_AUTOSIZE)
        self._container = container
        stack = NSStackView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 600))
        stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        stack.setAlignment_(1)
        stack.setSpacing_(6)
        stack.setEdgeInsets_((16, 16, 16, 16))
        stack.setAutoresizingMask_(_AUTOSIZE)
        container.addSubview_(stack)
        add = stack.addArrangedSubview_

        add(theme.make_label("BIBLIOTECĂ", style="caption",
                             color=NSColor.tertiaryLabelColor()))
        self._name = theme.make_label("", style="headline")
        add(self._name)
        add(_spacer(6))
        self._rows = {}
        for key in ("Locație", "Track-uri", "Disponibile", "Lipsă", "Crate-uri",
                    "Stare", "Ultima scanare"):
            row = NSStackView.alloc().init()
            row.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
            row.setSpacing_(6)
            row.setAlignment_(12)
            cap = theme.make_label(key, style="caption", color=theme.secondary_label())
            cap.setContentHuggingPriority_forOrientation_(252, 0)
            cap.setContentCompressionResistancePriority_forOrientation_(750, 0)
            cap.addConstraint_(
                NSLayoutConstraint.constraintWithItem_attribute_relatedBy_toItem_attribute_multiplier_constant_(
                    cap, 7, 0, None, 0, 1.0, 92.0))
            val = theme.make_label("", style="callout")
            val.setLineBreakMode_(4)  # truncate middle for paths
            row.addArrangedSubview_(cap)
            row.addArrangedSubview_(val)
            add(row)
            self._rows[key] = val
        add(_spacer(12))
        add(theme.make_label("ACȚIUNI", style="caption",
                             color=NSColor.tertiaryLabelColor()))
        for title, sel in (
            ("Deschide în Finder", b"revealSelected:"),
            ("Rescanează", b"rescanAll:"),
            ("Verifică fișiere lipsă", b"verifyMissing:"),
            ("Reconstruiește baza de date", b"rebuildDB:"),
            ("Exportă baza de date…", b"exportDB:"),
        ):
            add(self._link_(title, sel))

    @objc.python_method
    def _link_(self, title, sel):
        b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 240, 18))
        b.setBordered_(False)
        b.setButtonType_(7)
        b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
            title, {NSForegroundColorAttributeName: NSColor.linkColor(),
                    NSFontAttributeName: NSFont.systemFontOfSize_(12)}))
        b.setTarget_(self._screen)
        b.setAction_(sel)
        return b


# ------------------------------------------------------------------- Crates
class _CrateNode:
    """One row in the crate outline: a hierarchy segment that may also be a
    crate itself (when `crate` is set)."""
    __slots__ = ("name", "children", "crate", "count", "warn")

    def __init__(self, name):
        self.name = name
        self.children = []
        self.crate = None
        self.count = 0
        self.warn = 0


def _build_crate_tree(lib, query=""):
    from . import health as _health
    q = (query or "").strip().lower()
    index = {}
    top = []
    for crate in lib.crates:
        prefix = ()
        parent_children = top
        node = None
        for seg in crate.hierarchy:
            prefix = prefix + (seg,)
            node = index.get(prefix)
            if node is None:
                node = _CrateNode(seg)
                index[prefix] = node
                parent_children.append(node)
            parent_children = node.children
        node.crate = crate
        node.count = len(crate.raw_paths)
        node.warn = _health.crate_missing_count(lib, crate)

    if not q:
        return top

    def keep(node):
        node.children[:] = [c for c in node.children if keep(c)]
        return q in node.name.lower() or bool(node.children)

    return [n for n in top if keep(n)]


class CratesScreen(BaseScreen):
    def build_(self, v):
        self._top = []            # list[_CrateNode]
        self._all_rows = []       # full (status,artist,title,path,Track) for the selected crate
        self._crate_tracks = []   # Track|None per *visible* row
        self._selected_crate = None
        self._selected_track = None
        self._inspector = None

        self._headerInto_title_subtitle_(v, "Crate-uri", None)

        # toolbar row: search + expand/collapse + track filter segmented
        self._search = NSSearchField.alloc().initWithFrame_(
            NSMakeRect(24, v.bounds().size.height - 108, 240, 24))
        self._search.setAutoresizingMask_(1 << 3)
        self._search.setPlaceholderString_("Filtrează crate-uri")
        self._search.setTarget_(self)
        self._search.setAction_(b"filterCrates:")
        v.addSubview_(self._search)

        bx = _button("Extinde tot", self, b"expandAll:")
        bx.setFrame_(NSMakeRect(272, v.bounds().size.height - 110, 110, 26))
        bx.setAutoresizingMask_(1 << 3)
        v.addSubview_(bx)
        bc = _button("Restrânge tot", self, b"collapseAll:")
        bc.setFrame_(NSMakeRect(386, v.bounds().size.height - 110, 120, 26))
        bc.setAutoresizingMask_(1 << 3)
        v.addSubview_(bc)

        from AppKit import NSSegmentedControl
        seg = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(v.bounds().size.width - 260, v.bounds().size.height - 110, 236, 24))
        seg.setSegmentCount_(3)
        for i, t in enumerate(("Toate", "OK", "Lipsă")):
            seg.setLabel_forSegment_(t, i)
            seg.setWidth_forSegment_(76, i)
        seg.setSelectedSegment_(0)
        seg.setAutoresizingMask_(1 << 0 | 1 << 3)
        seg.setTarget_(self)
        seg.setAction_(b"filterTracks:")
        self._seg = seg
        v.addSubview_(seg)

        body = self._bodyContainerIn_(v, top=126)

        # left: crate outline
        from AppKit import (NSOutlineView, NSTableColumn, NSTableCellView,
                            NSScrollView)
        ov = NSOutlineView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, body.bounds().size.height))
        col = NSTableColumn.alloc().initWithIdentifier_("main")
        col.setWidth_(340)
        ov.addTableColumn_(col)
        ov.setOutlineTableColumn_(col)
        ov.setHeaderView_(None)
        ov.setRowSizeStyle_(1)
        ov.setIndentationPerLevel_(14)
        ov.setAutoresizesOutlineColumn_(False)
        ov.setDataSource_(self)
        ov.setDelegate_(self)
        try:
            ov.setStyle_(2)  # inset / source-list feel
        except Exception:
            pass
        self._outline = ov
        os_ = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, body.bounds().size.height))
        os_.setDocumentView_(ov)
        os_.setHasVerticalScroller_(True)
        os_.setBorderType_(0)
        os_.setAutoresizingMask_(1 << 4)
        self._outlineScroll = os_
        body.addSubview_(os_)

        # left: empty-state label (shown instead of the outline)
        self._crateEmpty = theme.make_label("Biblioteca nu conține crate-uri.",
                                            style="secondary")
        self._crateEmpty.setFrame_(NSMakeRect(4, body.bounds().size.height - 40, 340, 18))
        self._crateEmpty.setAutoresizingMask_(1 << 3)
        self._crateEmpty.setHidden_(True)
        body.addSubview_(self._crateEmpty)

        # right: tracks table + its own empty state
        self._tracksTv, self._tracksDs, ts = _table(
            ["status", "artist", "title", "path"], ["", "Artist", "Titlu", "Cale"],
            [34, 170, 220, 320], numeric=())
        ts.setFrame_(NSMakeRect(372, 0, body.bounds().size.width - 372, body.bounds().size.height))
        ts.setAutoresizingMask_(_AUTOSIZE)
        self._tracksScroll = ts
        body.addSubview_(ts)
        self._tracksEmpty = theme.make_label(
            "Selectează un crate pentru a vedea track-urile.", style="secondary")
        self._tracksEmpty.setFrame_(NSMakeRect(380, body.bounds().size.height - 40,
                                               body.bounds().size.width - 400, 18))
        self._tracksEmpty.setAutoresizingMask_(1 << 3 | 1 << 1)
        body.addSubview_(self._tracksEmpty)

        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"outlineSelChanged:", "NSOutlineViewSelectionDidChangeNotification", self._outline)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"trackSelected:", "NSTableViewSelectionDidChangeNotification", self._tracksTv)

        # crate context menu
        from AppKit import NSMenu, NSMenuItem
        m = NSMenu.alloc().init()
        for title, sel in (("Deschide folderul în Finder", b"revealCrate:"),
                           ("Copiază căile track-urilor", b"copyCratePaths:"),
                           ("Rescanează", b"rescanFromCrate:")):
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
            it.setTarget_(self)
            m.addItem_(it)
        self._outline.setMenu_(m)

        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

    # ---- render / data ----
    def render(self):
        lib = self._app.activeLibrary()
        has_crates = bool(lib and lib.crates)
        self._top = _build_crate_tree(lib, self._search.stringValue()) if has_crates else []
        self._crateEmpty.setHidden_(has_crates)
        self._outlineScroll.setHidden_(not has_crates)
        self._outline.reloadData()
        for n in self._top:
            self._outline.expandItem_(n)
        self._all_rows = []
        self._crate_tracks = []
        self._selected_crate = None
        self._selected_track = None
        self._tracksDs.setData_([])
        self._tracksTv.reloadData()
        self._tracksEmpty.setHidden_(False)
        if self._app._router is not None:
            self._app._router.refreshInspector()

    def filterCrates_(self, sender):
        lib = self._app.activeLibrary()
        self._top = _build_crate_tree(lib, self._search.stringValue()) if (lib and lib.crates) else []
        self._outline.reloadData()
        for n in self._top:
            self._outline.expandItem_expandChildren_(n, True)

    def expandAll_(self, sender):
        for n in self._top:
            self._outline.expandItem_expandChildren_(n, True)

    def collapseAll_(self, sender):
        for n in self._top:
            self._outline.collapseItem_collapseChildren_(n, True)

    # ---- NSOutlineView data source ----
    def outlineView_numberOfChildrenOfItem_(self, ov, item):
        return len(self._top) if item is None else len(item.children)

    def outlineView_child_ofItem_(self, ov, idx, item):
        return self._top[idx] if item is None else item.children[idx]

    def outlineView_isItemExpandable_(self, ov, item):
        return bool(item.children)

    def outlineView_viewForTableColumn_item_(self, ov, col, item):
        from AppKit import NSTableCellView
        cell = ov.makeViewWithIdentifier_owner_("crate", self)
        if cell is None:
            cell = NSTableCellView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 22))
            cell.setIdentifier_("crate")
            name = theme.make_label("", style="body")
            name.setFrame_(NSMakeRect(2, 3, 210, 16))
            cell.addSubview_(name)
            cell.setTextField_(name)
            cnt = theme.make_label("", style="caption", color=theme.secondary_label())
            cnt.setFrame_(NSMakeRect(214, 3, 64, 16))
            cnt.setAlignment_(2)
            cnt.setTag_(91)
            cell.addSubview_(cnt)
            warn = theme.make_label("", style="caption", color=theme.warn_color())
            warn.setFrame_(NSMakeRect(280, 3, 56, 16))
            warn.setTag_(92)
            cell.addSubview_(warn)
        cell.textField().setStringValue_(item.name)
        cell.viewWithTag_(91).setStringValue_(theme.format_int(item.count) if item.crate else "")
        cell.viewWithTag_(92).setStringValue_(f"⚠ {item.warn}" if item.warn else "")
        return cell

    def outlineView_heightOfRowByItem_(self, ov, item):
        return 24.0

    # ---- crate selection -> tracks ----
    def outlineSelChanged_(self, note):
        row = self._outline.selectedRow()
        item = self._outline.itemAtRow_(row) if row >= 0 else None
        lib = self._app.activeLibrary()
        self._selected_track = None
        if item is None or item.crate is None or lib is None:
            self._selected_crate = None
            self._all_rows = []
            self._applyTrackFilter()
            if self._app._router is not None:
                self._app._router.refreshInspector()
            return
        self._selected_crate = item.crate
        rows = []
        for rp in item.crate.raw_paths:
            ap = Path(lib.volume_root) / rp
            t = lib.tracks.get(rp)
            rows.append(("✓" if ap.exists() else "⚠",
                         (t.artist if t else "") or "", (t.title if t else "") or "",
                         str(ap), t))
        self._all_rows = rows
        self._applyTrackFilter()
        if self._app._router is not None:
            self._app._router.refreshInspector()

    def filterTracks_(self, sender):
        self._applyTrackFilter()

    @objc.python_method
    def _applyTrackFilter(self):
        mode = self._seg.selectedSegment()  # 0 all, 1 ok, 2 missing
        rows = self._all_rows
        if mode == 1:
            rows = [r for r in rows if r[0] == "✓"]
        elif mode == 2:
            rows = [r for r in rows if r[0] != "✓"]
        self._crate_tracks = [r[4] for r in rows]
        self._tracksDs.setData_([r[:4] for r in rows])
        self._tracksTv.reloadData()
        self._tracksEmpty.setHidden_(bool(self._selected_crate))

    # -- Track Inspector (UI-15) --
    @objc.python_method
    def _ensureInspector(self):
        if self._inspector is None:
            from .track_inspector import TrackInspector
            self._inspector = TrackInspector.alloc().initWithApp_(self._app)
        return self._inspector

    def inspectorView(self):
        if getattr(self, "_selected_track", None) is None:
            return None
        return self._ensureInspector().view()

    def trackSelected_(self, note):
        row = self._tracksTv.selectedRow()
        lib = self._app.activeLibrary()
        track = None
        if 0 <= row < len(self._crate_tracks) and lib is not None:
            track = self._crate_tracks[row]
        self._selected_track = track
        if track is not None:
            self._ensureInspector().set_track(lib, track, on_saved=self._trackEdited)
        if self._app._router is not None:
            self._app._router.refreshInspector()

    @objc.python_method
    def _trackEdited(self):
        row = self._tracksTv.selectedRow()
        if 0 <= row < len(self._crate_tracks):
            t = self._crate_tracks[row]
            data = list(self._tracksDs.data())
            if row < len(data):
                cur = list(data[row])
                cur[1] = (t.artist or "") if t else ""
                cur[2] = (t.title or "") if t else ""
                data[row] = tuple(cur)
                self._tracksDs.setData_(data)
                self._tracksTv.reloadData()
                self._tracksTv.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(row), False)

    # ---- crate context menu ----
    @objc.python_method
    def _menuCrate(self):
        row = self._outline.clickedRow()
        if row < 0:
            row = self._outline.selectedRow()
        item = self._outline.itemAtRow_(row) if row >= 0 else None
        return item.crate if item is not None else None

    def revealCrate_(self, sender):
        crate = self._menuCrate()
        lib = self._app.activeLibrary()
        if crate is None or lib is None:
            return
        from AppKit import NSWorkspace
        from Foundation import NSURL
        # reveal the folder that holds this crate's first present track
        for rp in crate.raw_paths:
            ap = Path(lib.volume_root) / rp
            if ap.exists():
                NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
                    [NSURL.fileURLWithPath_(str(ap))])
                return
        NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
            [NSURL.fileURLWithPath_(str(crate.file_path))])

    def copyCratePaths_(self, sender):
        crate = self._menuCrate()
        lib = self._app.activeLibrary()
        if crate is None or lib is None:
            return
        from AppKit import NSPasteboard, NSPasteboardTypeString
        paths = "\n".join(str(Path(lib.volume_root) / rp) for rp in crate.raw_paths)
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(paths, NSPasteboardTypeString)
        self._app.log_(f"{len(crate.raw_paths)} căi copiate din „{crate.display_name}”",
                       "info", "crates")

    def rescanFromCrate_(self, sender):
        self._app.rescanLibraries_(None)


class _FlippedView(NSView):
    """Top-left origin, so manually-placed rows read top-to-bottom and a scroll
    view of one starts at the top."""

    def isFlipped(self):
        return True


class _DropView(NSView):
    """Plain NSView that accepts folder drops and forwards them to a screen."""

    def initWithFrame_(self, frame):
        self = objc.super(_DropView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._screen = None
        return self

    def setScreen_(self, s):
        self._screen = s

    def draggingEntered_(self, sender):
        return 1  # NSDragOperationCopy

    def prepareForDragOperation_(self, sender):
        return True

    def performDragOperation_(self, sender):
        if self._screen is not None:
            return bool(self._screen.handleFolderDrop_(sender))
        return False


# ------------------------------------------------------------------- Orphans
class OrphansScreen(BaseScreen):
    """State-driven: BEFORE SCAN / SCANNING / NOTHING FOUND / RESULTS FOUND —
    exactly one visible at a time."""

    def build_(self, v):
        self._state = "before"
        self._scan_root = None
        self._orphans = []      # list[(abs_path, location, size_bytes)]
        self._filtered = []
        self._headerInto_title_subtitle_(
            v, "Fișiere orfane", "Fișiere audio de pe disc necunoscute de Serato")
        self._body = _DropView.alloc().initWithFrame_(
            NSMakeRect(24, 16, v.bounds().size.width - 48, v.bounds().size.height - 96 - 16))
        self._body.setScreen_(self)
        self._body.setAutoresizingMask_(_AUTOSIZE)
        v.addSubview_(self._body)
        self._body.registerForDraggedTypes_(["public.file-url", "NSFilenamesPboardType"])
        self._panels = {}
        self._buildBefore()
        self._buildScanning()
        self._buildNothing()
        self._buildResults()
        self.render()

    def didBecomeVisible(self):
        if self._state in ("before", "nothing"):
            self._refreshLocations()

    def librariesChanged(self):
        if self._state == "before":
            self._refreshLocations()

    # ---- state switching ----
    @objc.python_method
    def _show(self, state):
        self._state = state
        for k, p in self._panels.items():
            p.setHidden_(k != state)

    def render(self):
        self._refreshLocations()
        self._show(self._state)

    # ---- BEFORE ----
    @objc.python_method
    def _buildBefore(self):
        p = NSView.alloc().initWithFrame_(self._body.bounds())
        p.setAutoresizingMask_(_AUTOSIZE)
        self._body.addSubview_(p)
        self._panels["before"] = p
        y = p.bounds().size.height
        lbl = theme.make_label(
            "Un fișier „orfan” e un fișier audio aflat pe disc, în folderul "
            "bibliotecii, pe care Serato nu îl cunoaște (nu apare în „database "
            "V2”). Scanarea compară fișierele de pe disc cu cele știute de Serato.",
            style="body")
        lbl.setFrame_(NSMakeRect(0, y - 72, 640, 60))
        lbl.setAutoresizingMask_(1 << 3)
        lbl.setLineBreakMode_(0)
        lbl.setUsesSingleLineMode_(False)
        p.addSubview_(lbl)
        cap = theme.make_label("Locație de scanat", style="caption",
                               color=theme.secondary_label())
        cap.setFrame_(NSMakeRect(0, y - 104, 400, 16))
        cap.setAutoresizingMask_(1 << 3)
        p.addSubview_(cap)
        self._loc = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(0, y - 132, 420, 26))
        self._loc.setAutoresizingMask_(1 << 3)
        self._loc.setTarget_(self)
        self._loc.setAction_(b"locChanged:")
        p.addSubview_(self._loc)
        browse = _button("Alege folder…", self, b"browseRoot:")
        browse.setFrame_(NSMakeRect(430, y - 133, 130, 28))
        browse.setAutoresizingMask_(1 << 3)
        p.addSubview_(browse)
        self._scanBtn = NSButton.alloc().initWithFrame_(NSMakeRect(0, y - 176, 160, 30))
        self._scanBtn.setBezelStyle_(NSBezelStyleRounded)
        self._scanBtn.setTitle_("Scanează")
        self._scanBtn.setKeyEquivalent_("\r")
        self._scanBtn.setTarget_(self)
        self._scanBtn.setAction_(b"scan:")
        self._scanBtn.setAutoresizingMask_(1 << 3)
        p.addSubview_(self._scanBtn)

    @objc.python_method
    def _refreshLocations(self):
        if not hasattr(self, "_loc"):
            return
        self._loc.removeAllItems()
        roots = [str(l.volume_root) for l in self._app.libraries()]
        for r in roots:
            self._loc.addItemWithTitle_(r)
        if self._scan_root and self._scan_root not in roots:
            self._loc.addItemWithTitle_(self._scan_root)
        if self._scan_root:
            self._loc.selectItemWithTitle_(self._scan_root)
        elif roots:
            self._scan_root = roots[0]
        self._scanBtn.setEnabled_(bool(self._loc.numberOfItems()))

    def locChanged_(self, sender):
        t = self._loc.titleOfSelectedItem()
        if t:
            self._scan_root = str(t)

    def browseRoot_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setPrompt_("Alege")
        if panel.runModal() == 1:
            self._scan_root = panel.URLs()[0].path()
            self._refreshLocations()

    # ---- SCANNING ----
    @objc.python_method
    def _buildScanning(self):
        p = NSView.alloc().initWithFrame_(self._body.bounds())
        p.setAutoresizingMask_(_AUTOSIZE)
        p.setHidden_(True)
        self._body.addSubview_(p)
        self._panels["scanning"] = p
        y = p.bounds().size.height
        self._spin = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(0, y - 60, 24, 24))
        self._spin.setStyle_(1)  # spinning
        self._spin.setAutoresizingMask_(1 << 3)
        p.addSubview_(self._spin)
        self._scanMsg = theme.make_label("Se scanează…", style="body")
        self._scanMsg.setFrame_(NSMakeRect(34, y - 58, 560, 20))
        self._scanMsg.setAutoresizingMask_(1 << 3)
        p.addSubview_(self._scanMsg)
        self._scanSub = theme.make_label("", style="secondary")
        self._scanSub.setFrame_(NSMakeRect(34, y - 82, 560, 18))
        self._scanSub.setAutoresizingMask_(1 << 3)
        p.addSubview_(self._scanSub)

    # ---- NOTHING FOUND ----
    @objc.python_method
    def _buildNothing(self):
        p = NSStackView.alloc().initWithFrame_(self._body.bounds())
        p.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        p.setAlignment_(1)
        p.setSpacing_(6)
        p.setAutoresizingMask_(_AUTOSIZE)
        p.setHidden_(True)
        self._body.addSubview_(p)
        self._panels["nothing"] = p
        p.addArrangedSubview_(theme.make_label("✓ Nu au fost găsite fișiere orfane",
                                               style="title2"))
        p.addArrangedSubview_(theme.make_label(
            "Toate fișierele audio scanate sunt asociate bibliotecii Serato.",
            style="secondary"))
        p.addArrangedSubview_(_spacer(8))
        p.addArrangedSubview_(_button("Scanează din nou", self, b"backToBefore:"))

    def backToBefore_(self, sender):
        self._show("before")
        self._refreshLocations()

    # ---- RESULTS FOUND ----
    @objc.python_method
    def _buildResults(self):
        p = NSView.alloc().initWithFrame_(self._body.bounds())
        p.setAutoresizingMask_(_AUTOSIZE)
        p.setHidden_(True)
        self._body.addSubview_(p)
        self._panels["results"] = p
        y = p.bounds().size.height
        self._summary = theme.make_label("", style="headline")
        self._summary.setFrame_(NSMakeRect(0, y - 30, 600, 20))
        self._summary.setAutoresizingMask_(1 << 3)
        p.addSubview_(self._summary)
        self._oSearch = NSSearchField.alloc().initWithFrame_(NSMakeRect(0, y - 62, 260, 24))
        self._oSearch.setAutoresizingMask_(1 << 3)
        self._oSearch.setPlaceholderString_("Filtrează fișierele")
        self._oSearch.setTarget_(self)
        self._oSearch.setAction_(b"filterResults:")
        p.addSubview_(self._oSearch)
        self._tv, self._ds, scroll = _table(
            ["file", "loc", "size"], ["Fișier", "Locație", "Mărime"],
            [280, 300, 90], numeric=("size",))
        scroll.setFrame_(NSMakeRect(0, 44, p.bounds().size.width, y - 62 - 44))
        scroll.setAutoresizingMask_(_AUTOSIZE)
        p.addSubview_(scroll)
        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"resultsSelChanged:", "NSTableViewSelectionDidChangeNotification", self._tv)
        # action bar
        self._addBtn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 6, 260, 30))
        self._addBtn.setBezelStyle_(NSBezelStyleRounded)
        self._addBtn.setTitle_("Adaugă în crate-ul „Orfane”")
        self._addBtn.setTarget_(self)
        self._addBtn.setAction_(b"addToCrate:")
        p.addSubview_(self._addBtn)
        rb = _button("Deschide în Finder", self, b"revealResult:")
        rb.setFrame_(NSMakeRect(270, 6, 170, 28))
        p.addSubview_(rb)
        cb = _button("Copiază căile", self, b"copyResults:")
        cb.setFrame_(NSMakeRect(448, 6, 150, 28))
        p.addSubview_(cb)

    # ---- scan ----
    def scan_(self, sender):
        lib = self._app.activeLibrary()
        if lib is None:
            _alert("Nicio bibliotecă activă.")
            return
        root = self._scan_root or str(lib.volume_root)
        known = {t.abs_path for t in lib.tracks.values()}
        self._show("scanning")
        self._spin.startAnimation_(None)
        self._scanMsg.setStringValue_("Se scanează…")
        self._scanSub.setStringValue_(root)
        self._app.log_(f"Scanez {root} după fișiere orfane…", "info", "orphans")
        self._app._beginBusy_("orphans")

        def progress(n):
            AppHelper.callAfter(self._scanSub.setStringValue_,
                                f"{theme.format_int(n)} fișiere inspectate — {root}")

        def work():
            err = None
            try:
                found = scanner.find_orphan_files(root, known, progress_cb=progress)
            except Exception:
                found, err = [], traceback.format_exc()
            AppHelper.callAfter(self._scanDone_, found, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _scanDone_(self, found, err):
        self._spin.stopAnimation_(None)
        self._app._endBusy_("orphans")
        if err:
            self._app.log_("Eroare scanare orfane:\n" + err, "error", "orphans")
            _alert("Scanarea a eșuat (vezi Jurnal).")
            self._show("before")
            return
        rows = []
        for pth in found:
            pth = Path(pth)
            try:
                sz = pth.stat().st_size
            except OSError:
                sz = 0
            rows.append((str(pth), str(pth.parent), sz))
        self._orphans = rows
        self._app.log_(f"Scanare orfane: {len(rows)} găsite", "info", "orphans")
        if not rows:
            self._show("nothing")
            return
        total = sum(r[2] for r in rows)
        self._summary.setStringValue_(
            f"{theme.format_int(len(rows))} fișiere orfane · {theme.human_size(total)}")
        self._applyResultsFilter()
        self._show("results")

    def filterResults_(self, sender):
        self._applyResultsFilter()

    @objc.python_method
    def _applyResultsFilter(self):
        q = self._oSearch.stringValue().lower()
        self._filtered = sorted(
            (r for r in self._orphans if not q or q in r[0].lower()),
            key=lambda r: r[2], reverse=True)  # largest orphans first
        self._ds.setData_([(Path(a).name, loc, theme.human_size(sz))
                           for a, loc, sz in self._filtered])
        self._tv.reloadData()
        self._updateAddButton()

    def resultsSelChanged_(self, note):
        self._updateAddButton()

    @objc.python_method
    def _updateAddButton(self):
        sel = self._tv.selectedRowIndexes().count()
        k = sel if sel else len(self._filtered)
        self._addBtn.setTitle_(f"Adaugă {theme.format_int(k)} în crate-ul „Orfane”")
        self._addBtn.setEnabled_(k > 0)

    @objc.python_method
    def _rowAbs(self, row):
        data = self._ds.data()
        if not (0 <= row < len(data)):
            return None
        name, loc, _sz = data[row]
        return str(Path(loc) / name)

    @objc.python_method
    def _selectedAbsPaths(self):
        idx = self._tv.selectedRowIndexes()
        if idx.count():
            out = []
            i = idx.firstIndex()
            while i != _NSNotFound:
                ap = self._rowAbs(i)
                if ap:
                    out.append(ap)
                i = idx.indexGreaterThanIndex_(i)
            return out
        return [self._rowAbs(r) for r in range(len(self._ds.data()))]

    def addToCrate_(self, sender):
        lib = self._app.activeLibrary()
        paths = self._selectedAbsPaths()
        if lib is None or not paths:
            return
        a = NSAlert.alloc().init()
        a.setMessageText_(f"Adaugi {len(paths)} fișiere în crate-ul „Orfane”?")
        a.setInformativeText_("Se face întâi un backup la „database V2”. Fișierele "
                              "sunt adăugate în crate și în baza de date Serato.")
        a.addButtonWithTitle_("Adaugă")
        a.addButtonWithTitle_("Anulează")
        if a.runModal() != 1000:
            return
        self._app._beginBusy_("orphans")
        self._app.log_(f"Adaug {len(paths)} orfane în crate-ul „Orfane”…", "info", "orphans")

        def work():
            err = None
            try:
                res = copier.add_orphans_to_crate(lib, paths, "Orfane")
            except Exception:
                res, err = (0, 0), traceback.format_exc()
            AppHelper.callAfter(self._addDone_, res, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _addDone_(self, res, err):
        self._app._endBusy_("orphans")
        if err:
            self._app.log_("Eroare la adăugarea orfanelor:\n" + err, "error", "orphans")
            _alert("Adăugarea a eșuat (vezi Jurnal).")
            return
        in_crate, in_db = res
        self._app.log_(f"Orfane adăugate: {in_crate} în crate, {in_db} în baza de date",
                       "info", "orphans")
        _alert("Fișiere adăugate în „Orfane”",
               informative=f"{in_crate} în crate · {in_db} în „database V2”")
        self._app.rescanLibraries_(None)
        self._show("before")

    def revealResult_(self, sender):
        paths = self._selectedAbsPaths()[:1]
        if not paths:
            return
        from AppKit import NSWorkspace
        from Foundation import NSURL
        NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
            [NSURL.fileURLWithPath_(paths[0])])

    def copyResults_(self, sender):
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_("\n".join(self._selectedAbsPaths()), NSPasteboardTypeString)
        self._app.log_("Căile fișierelor orfane copiate", "info", "orphans")

    # ---- drag & drop a folder to set the scan location ----
    def handleFolderDrop_(self, sender):
        from Foundation import NSURL
        urls = sender.draggingPasteboard().readObjectsForClasses_options_([NSURL], None)
        for u in (urls or []):
            p = u.path()
            if p and Path(p).is_dir():
                self._scan_root = p
                self._show("before")
                self._refreshLocations()
                a = NSAlert.alloc().init()
                a.setMessageText_("Scanezi acum acest folder pentru fișiere orfane?")
                a.setInformativeText_(p)
                a.addButtonWithTitle_("Scanează")
                a.addButtonWithTitle_("Mai târziu")
                if a.runModal() == 1000:
                    self.scan_(None)
                return True
        return False


# ------------------------------------------------------------------- Migrate
_MIG_STEPS = ["Sursă", "Destinație", "Opțiuni", "Verificare",
              "Migrare", "Verificare-post", "Complet"]


class MigrateScreen(BaseScreen):
    """The hero workflow — a guided 7-step pager. Every copier call is the same
    one the old flow made; the pager only sequences and narrates them."""

    def build_(self, v):
        self._step = 0
        self._sel_keys = None       # None = all crates; else set[str(crate.file_path)]
        self._include_unsorted = True
        self._dest = ""
        self._db_mode = "fresh"     # "fresh" | "copy"
        self._normalize = True
        self._backup = True
        self._plan = None
        self._required = 0
        self._free = None
        self._crate_sizes = {}      # crate_key -> bytes
        self._run_log = []
        self._verify = None
        self._t0 = 0.0

        self._headerInto_title_subtitle_(v, "Migrare", None)
        self._crumbs = theme.make_label("", style="caption", color=theme.secondary_label())
        self._crumbs.setFrame_(NSMakeRect(24, v.bounds().size.height - 92, 700, 16))
        self._crumbs.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._crumbs)

        self._pager = NSView.alloc().initWithFrame_(
            NSMakeRect(24, 52, v.bounds().size.width - 48, v.bounds().size.height - 92 - 52))
        self._pager.setAutoresizingMask_(_AUTOSIZE)
        v.addSubview_(self._pager)

        # nav bar
        self._backBtn = _button("‹ Înapoi", self, b"back:")
        self._backBtn.setFrame_(NSMakeRect(24, 12, 100, 28))
        self._backBtn.setAutoresizingMask_(1 << 5)
        v.addSubview_(self._backBtn)
        self._nextBtn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 12, 160, 30))
        self._nextBtn.setBezelStyle_(NSBezelStyleRounded)
        self._nextBtn.setTitle_("Continuă ›")
        self._nextBtn.setKeyEquivalent_("\r")
        self._nextBtn.setTarget_(self)
        self._nextBtn.setAction_(b"next:")
        self._nextBtn.setFrameOrigin_((v.bounds().size.width - 48 - 160 + 24, 12))
        self._nextBtn.setAutoresizingMask_(1 << 0)
        v.addSubview_(self._nextBtn)

        self._panels = {}
        self._buildSource()
        self._buildDest()
        self._buildOptions()
        self._buildReview()
        self._buildRun()
        self._buildPostVerify()
        self._buildComplete()
        self._go(0)

    def didBecomeVisible(self):
        if self._step == 0:
            self._renderSource()

    def librariesChanged(self):
        if self._step == 0:
            self._renderSource()

    # ---- pager plumbing ----
    @objc.python_method
    def _go(self, step):
        self._step = max(0, min(step, len(_MIG_STEPS) - 1))
        for i, p in self._panels.items():
            p.setHidden_(i != self._step)
        self._crumbs.setStringValue_(
            "  →  ".join(("[%s]" % s if i == self._step else s)
                         for i, s in enumerate(_MIG_STEPS)))
        self._backBtn.setEnabled_(0 < self._step < 4)
        running = self._step in (4,)
        self._backBtn.setHidden_(self._step in (4, 5, 6))
        labels = {3: "Începe migrarea", 5: "Continuă ›", 6: "Închide"}
        self._nextBtn.setTitle_(labels.get(self._step, "Continuă ›"))
        self._nextBtn.setHidden_(self._step == 4)
        self._nextBtn.setEnabled_(not running)
        hooks = {0: self._renderSource, 1: self._renderDest, 3: self._renderReview,
                 5: self._renderPostVerify, 6: self._renderComplete}
        h = hooks.get(self._step)
        if h:
            h()

    def back_(self, sender):
        self._go(self._step - 1)

    def next_(self, sender):
        s = self._step
        if s == 0:
            if not self._selectedCrateList():
                _alert("Alege cel puțin un crate.")
                return
            self._go(1)
        elif s == 1:
            if not self._dest:
                _alert("Alege o destinație.")
                return
            self._go(2)
        elif s == 2:
            self._go(3)
        elif s == 3:
            self._startMigration()
        elif s == 5:
            self._go(6)
        elif s == 6:
            self._go(0)

    @objc.python_method
    def _panel(self, key, top=0):
        p = NSView.alloc().initWithFrame_(self._pager.bounds())
        p.setAutoresizingMask_(_AUTOSIZE)
        p.setHidden_(True)
        self._pager.addSubview_(p)
        self._panels[key] = p
        return p

    # ================================================== step 0 — Sursă
    @objc.python_method
    def _buildSource(self):
        p = self._panel(0)
        y = p.bounds().size.height
        self._srcLine = theme.make_label("", style="headline")
        self._srcLine.setFrame_(NSMakeRect(0, y - 26, p.bounds().size.width, 20))
        self._srcLine.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._srcLine)
        bar = NSView.alloc().initWithFrame_(NSMakeRect(0, y - 60, p.bounds().size.width, 26))
        bar.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(bar)
        ba = _button("Toate", self, b"crAll:"); ba.setFrame_(NSMakeRect(0, 0, 80, 24)); bar.addSubview_(ba)
        bn = _button("Niciunul", self, b"crNone:"); bn.setFrame_(NSMakeRect(86, 0, 90, 24)); bar.addSubview_(bn)
        self._unsortedChk = NSButton.alloc().initWithFrame_(NSMakeRect(190, 2, 320, 20))
        self._unsortedChk.setButtonType_(NSSwitchButton)
        self._unsortedChk.setTitle_("Include track-urile ne-încadrate în crate-uri")
        self._unsortedChk.setState_(1)
        self._unsortedChk.setTarget_(self)
        self._unsortedChk.setAction_(b"toggleUnsorted:")
        bar.addSubview_(self._unsortedChk)
        sc = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 28, p.bounds().size.width, y - 60 - 28))
        sc.setHasVerticalScroller_(True)
        sc.setBorderType_(0)
        sc.setDrawsBackground_(False)
        sc.setAutoresizingMask_(_AUTOSIZE)
        self._crateDoc = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, p.bounds().size.width, 10))
        self._crateDoc.setAutoresizingMask_(1 << 1)  # width sizable
        sc.setDocumentView_(self._crateDoc)
        self._crateScroll = sc
        p.addSubview_(sc)
        self._crateFooter = theme.make_label("", style="caption", color=theme.secondary_label())
        self._crateFooter.setFrame_(NSMakeRect(0, 6, p.bounds().size.width, 16))
        self._crateFooter.setAutoresizingMask_(1 << 1)
        p.addSubview_(self._crateFooter)
        self._crateChecks = []   # (NSButton, crate)

    @objc.python_method
    def _renderSource(self):
        lib = self._app.activeLibrary()
        if lib is None:
            self._srcLine.setStringValue_("Nicio bibliotecă activă.")
            self._nextBtn.setEnabled_(False)
            return
        self._nextBtn.setEnabled_(True)
        self._srcLine.setStringValue_(
            f"{lib.name} · {lib.volume_root} · {theme.format_int(len(lib.present_tracks))} "
            f"track-uri · {theme.format_int(len(lib.crates))} crate-uri")
        for sub in list(self._crateDoc.subviews()):
            sub.removeFromSuperview()
        self._crateChecks = []
        row_h = 22
        n = len(lib.crates)
        vis_h = self._crateScroll.contentSize().height
        doc_h = max(n * row_h, int(vis_h))
        w = self._crateScroll.contentSize().width
        self._crateDoc.setFrame_(NSMakeRect(0, 0, w, doc_h))
        for i, crate in enumerate(lib.crates):
            key = str(crate.file_path)
            cb = NSButton.alloc().initWithFrame_(NSMakeRect(0, i * row_h, w, 20))
            cb.setButtonType_(NSSwitchButton)
            cb.setTitle_(crate.display_name)
            cb.setState_(1 if (self._sel_keys is None or key in self._sel_keys) else 0)
            cb.setTarget_(self)
            cb.setAction_(b"crateToggled:")
            cb.setAutoresizingMask_(1 << 1)  # width sizable
            self._crateDoc.addSubview_(cb)
            self._crateChecks.append((cb, crate))
        if not getattr(self, "_sizes_started", False):
            self._sizes_started = True
            threading.Thread(target=self._computeCrateSizes, daemon=True).start()
        self._updateCrateFooter()

    @objc.python_method
    def _selectedCrateList(self):
        return [(cb, cr) for cb, cr in self._crateChecks if cb.state() == 1]

    @objc.python_method
    def _syncSelKeys(self):
        picked = {str(cr.file_path) for cb, cr in self._crateChecks if cb.state() == 1}
        allk = {str(cr.file_path) for cb, cr in self._crateChecks}
        self._sel_keys = None if picked == allk else picked

    @objc.python_method
    def _updateCrateFooter(self):
        picked = self._selectedCrateList()
        n = len(picked)
        tot = len(self._crateChecks)
        size = sum(self._crate_sizes.get(str(cr.file_path), 0) for cb, cr in picked)
        extra = "  (mărimile se calculează…)" if not self._crate_sizes else ""
        self._crateFooter.setStringValue_(
            f"{n}/{tot} crate-uri · ~{theme.human_size(size)}{extra}")

    def crateToggled_(self, sender):
        self._syncSelKeys()
        self._updateCrateFooter()

    def crAll_(self, sender):
        for cb, _cr in self._crateChecks:
            cb.setState_(1)
        self._syncSelKeys(); self._updateCrateFooter()

    def crNone_(self, sender):
        for cb, _cr in self._crateChecks:
            cb.setState_(0)
        self._syncSelKeys(); self._updateCrateFooter()

    def toggleUnsorted_(self, sender):
        self._include_unsorted = self._unsortedChk.state() == 1

    @objc.python_method
    def _computeCrateSizes(self):
        lib = self._app.activeLibrary()
        if lib is None:
            return
        vol = Path(lib.volume_root)
        sizes = {}
        for crate in lib.crates:
            tot = 0
            for rp in crate.raw_paths:
                try:
                    tot += (vol / rp).stat().st_size
                except OSError:
                    pass
            sizes[str(crate.file_path)] = tot
        self._crate_sizes = sizes
        AppHelper.callAfter(self._updateCrateFooter)

    # ================================================== step 1 — Destinație
    @objc.python_method
    def _buildDest(self):
        p = self._panel(1)
        y = p.bounds().size.height
        b = _button("Alege destinația…", self, b"chooseDest:")
        b.setFrame_(NSMakeRect(0, y - 40, 180, 30))
        b.setAutoresizingMask_(1 << 3)
        p.addSubview_(b)
        self._destPath = theme.make_label("Nicio destinație aleasă.", style="body")
        self._destPath.setFrame_(NSMakeRect(0, y - 76, p.bounds().size.width, 18))
        self._destPath.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._destPath)
        self._destInfo = theme.make_label("", style="secondary")
        self._destInfo.setFrame_(NSMakeRect(0, y - 150, p.bounds().size.width, 66))
        self._destInfo.setAutoresizingMask_(1 << 3 | 1 << 1)
        self._destInfo.setLineBreakMode_(0)
        self._destInfo.setUsesSingleLineMode_(False)
        p.addSubview_(self._destInfo)
        self._destFit = theme.make_label("", style="headline")
        self._destFit.setFrame_(NSMakeRect(0, y - 178, p.bounds().size.width, 20))
        self._destFit.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._destFit)

    def chooseDest_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setPrompt_("Alege")
        if panel.runModal() == 1:
            self._dest = panel.URLs()[0].path()
            self._renderDest()

    @objc.python_method
    def _renderDest(self):
        lib = self._app.activeLibrary()
        if not self._dest or lib is None:
            self._destPath.setStringValue_("Nicio destinație aleasă.")
            self._destInfo.setStringValue_("")
            self._destFit.setStringValue_("")
            return
        from AppKit import NSFileManager
        dest = self._dest
        try:
            vol_name = NSFileManager.defaultManager()\
                .componentsToDisplayForPath_(dest)[0]
        except Exception:
            vol_name = Path(dest).anchor or dest
        self._destPath.setStringValue_(dest)
        self._destInfo.setStringValue_("Calculez planul și spațiul…")
        self._destFit.setStringValue_("")

        def work():
            try:
                plan = copier.plan_copy(
                    [lib], Path(dest), normalize_names=self._normalize,
                    selected_crate_keys=self._sel_keys,
                    include_unsorted=self._include_unsorted)
                free = copier.free_space(Path(dest))
                sdir = lib.serato_dir if self._db_mode == "copy" else None
                req = copier.estimate_required_bytes(plan, Path(dest), sdir)
            except Exception:
                self._app.log_("Eroare plan migrare:\n" + traceback.format_exc(),
                               "error", "migrate")
                AppHelper.callAfter(self._destInfo.setStringValue_,
                                    "Eroare la calcul (vezi Jurnal).")
                return
            AppHelper.callAfter(self._destReady_, plan, req, free, str(vol_name))

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _destReady_(self, plan, req, free, vol_name):
        self._plan = plan
        self._required = req
        self._free = free
        self._destInfo.setStringValue_(
            f"Volum:               {vol_name}\n"
            f"Spațiu disponibil:   {theme.human_size(free) if free is not None else '—'}\n"
            f"Spațiu necesar:      {theme.human_size(req)}")
        if free is None:
            self._destFit.setStringValue_("• Spațiul liber nu a putut fi determinat")
            self._destFit.setTextColor_(theme.secondary_label())
        elif req <= free:
            self._destFit.setStringValue_("✓ Spațiu suficient")
            self._destFit.setTextColor_(theme.ok_color())
        else:
            self._destFit.setStringValue_(
                f"✕ NU ÎNCAPE — lipsesc ~{theme.human_size(req - free)}")
            self._destFit.setTextColor_(theme.error_color())

    # ================================================== step 2 — Opțiuni
    @objc.python_method
    def _buildOptions(self):
        p = self._panel(2)
        st = NSStackView.alloc().initWithFrame_(p.bounds())
        st.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        st.setAlignment_(1)
        st.setSpacing_(6)
        st.setEdgeInsets_((6, 0, 6, 0))
        st.setAutoresizingMask_(_AUTOSIZE)
        p.addSubview_(st)
        add = st.addArrangedSubview_

        add(theme.make_label("STRUCTURA BAZEI DE DATE", style="caption",
                             color=NSColor.tertiaryLabelColor()))
        self._rbFresh = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 560, 20))
        self._rbFresh.setButtonType_(4)  # radio
        self._rbFresh.setTitle_("Generează bază de date nouă (doar ce migrez)")
        self._rbFresh.setState_(1)
        self._rbFresh.setTarget_(self); self._rbFresh.setAction_(b"pickFresh:")
        add(self._rbFresh)
        add(theme.make_label(
            "Un „_Serato_” nou la destinație, doar cu track-urile și crate-urile alese. Originalul nu e citit decât pentru metadata.",
            style="caption", color=theme.secondary_label()))
        self._rbCopy = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 560, 20))
        self._rbCopy.setButtonType_(4)
        self._rbCopy.setTitle_("Copiază „_Serato_” + rescrie căile")
        self._rbCopy.setTarget_(self); self._rbCopy.setAction_(b"pickCopy:")
        add(self._rbCopy)
        add(theme.make_label(
            "Copiază baza de date existentă la destinație și rescrie căile către noua locație (necesită o singură bibliotecă).",
            style="caption", color=theme.secondary_label()))
        add(_spacer(10))

        add(theme.make_label("FIȘIERE", style="caption", color=NSColor.tertiaryLabelColor()))
        self._chkNorm = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 560, 20))
        self._chkNorm.setButtonType_(NSSwitchButton)
        self._chkNorm.setTitle_("Normalizează numele SCRISE CU MAJUSCULE")
        self._chkNorm.setState_(1)
        self._chkNorm.setTarget_(self); self._chkNorm.setAction_(b"toggleNorm:")
        add(self._chkNorm)
        add(_spacer(10))

        add(theme.make_label("SIGURANȚĂ", style="caption", color=NSColor.tertiaryLabelColor()))
        self._chkBackup = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 560, 20))
        self._chkBackup.setButtonType_(NSSwitchButton)
        self._chkBackup.setTitle_("Creează backup înainte de migrare")
        self._chkBackup.setState_(1)
        self._chkBackup.setTarget_(self); self._chkBackup.setAction_(b"toggleBackup:")
        add(self._chkBackup)
        add(theme.make_label(
            "Scrie un „Serato DB - <bibliotecă> - <dată>.zip” lângă destinație înainte de orice copiere (folosește exportul de bază de date existent).",
            style="caption", color=theme.secondary_label()))

    def pickFresh_(self, sender):
        self._db_mode = "fresh"
        self._rbFresh.setState_(1); self._rbCopy.setState_(0)

    def pickCopy_(self, sender):
        self._db_mode = "copy"
        self._rbCopy.setState_(1); self._rbFresh.setState_(0)

    def toggleNorm_(self, sender):
        self._normalize = self._chkNorm.state() == 1

    def toggleBackup_(self, sender):
        self._backup = self._chkBackup.state() == 1

    # ================================================== step 3 — Verificare
    @objc.python_method
    def _buildReview(self):
        p = self._panel(3)
        self._reviewText = NSTextView.alloc().initWithFrame_(p.bounds())
        self._reviewText.setEditable_(False)
        self._reviewText.setDrawsBackground_(False)
        self._reviewText.setFont_(NSFont.systemFontOfSize_(13))
        self._reviewText.setAutoresizingMask_(_AUTOSIZE)
        p.addSubview_(self._reviewText)

    @objc.python_method
    def _backupName(self, lib):
        from datetime import date
        return f"Serato DB - {lib.name} - {date.today().isoformat()}.zip"

    @objc.python_method
    def _renderReview(self):
        lib = self._app.activeLibrary()
        if lib is None or not self._dest:
            self._reviewText.setString_("Revino la pașii anteriori — lipsește biblioteca sau destinația.")
            self._nextBtn.setEnabled_(False)
            return
        self._reviewText.setString_("Pregătesc rezumatul…")
        self._nextBtn.setEnabled_(False)
        dest = self._dest
        norm, keys, unsorted = self._normalize, self._sel_keys, self._include_unsorted
        sdir = lib.serato_dir if self._db_mode == "copy" else None

        def work():
            try:
                plan = copier.plan_copy([lib], Path(dest), normalize_names=norm,
                                        selected_crate_keys=keys,
                                        include_unsorted=unsorted)
                req = copier.estimate_required_bytes(plan, Path(dest), sdir)
                free = copier.free_space(Path(dest))
            except Exception:
                self._app.log_("Eroare rezumat migrare:\n" + traceback.format_exc(),
                               "error", "migrate")
                AppHelper.callAfter(self._reviewText.setString_,
                                    "Eroare la calcul (vezi Jurnal).")
                return
            AppHelper.callAfter(self._reviewReady_, plan, req, free)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _reviewReady_(self, plan, req, free):
        lib = self._app.activeLibrary()
        self._plan = plan
        self._required = req
        self._free = free
        pl = plan
        fits = self._free is None or self._required <= self._free
        db_line = ("Generează una nouă, doar cu crate-urile alese"
                   if self._db_mode == "fresh"
                   else "Copiază „_Serato_” existent + rescrie căile")
        lines = [
            f"{lib.name}   ↓   {self._dest}",
            "",
            f"{theme.format_int(pl.primary_count)} fișiere de copiat · "
            f"{theme.format_int(pl.link_count)} hard link-uri · {theme.human_size(pl.total_bytes)}",
            "",
            f"Spațiu necesar:      {theme.human_size(self._required)}",
            f"Spațiu disponibil:   {theme.human_size(self._free) if self._free is not None else '—'}",
            ("✓ Spațiu suficient" if fits else
             f"✕ NU ÎNCAPE — lipsesc ~{theme.human_size(self._required - (self._free or 0))}"),
            f"{'✓' if not pl.skipped_missing else '⚠'} {len(pl.skipped_missing)} fișiere lipsă (sărite)",
            f"Bază de date:        {db_line}",
            f"Nume:                {'Normalizate' if self._normalize else 'Nemodificate'}",
            f"Backup:              {self._backupName(lib) if self._backup else '—'}",
            "",
            "Fișierele originale NU sunt șterse, mutate sau redenumite.",
        ]
        self._reviewText.setString_("\n".join(lines))
        self._nextBtn.setEnabled_(True)

    # ================================================== step 4 — Migrare
    @objc.python_method
    def _buildRun(self):
        p = self._panel(4)
        y = p.bounds().size.height
        self._phase = theme.make_label("", style="headline")
        self._phase.setFrame_(NSMakeRect(0, y - 26, p.bounds().size.width, 20))
        self._phase.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._phase)
        self._bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(0, y - 54, p.bounds().size.width, 16))
        self._bar.setIndeterminate_(True)
        self._bar.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._bar)
        self._progLine = theme.make_label("", style="body")
        self._progLine.setFrame_(NSMakeRect(0, y - 82, p.bounds().size.width, 18))
        self._progLine.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._progLine)
        self._curFile = theme.make_label("", style="secondary")
        self._curFile.setFrame_(NSMakeRect(0, y - 104, p.bounds().size.width, 18))
        self._curFile.setAutoresizingMask_(1 << 3 | 1 << 1)
        self._curFile.setLineBreakMode_(4)
        p.addSubview_(self._curFile)
        self._etaLine = theme.make_label("", style="secondary")
        self._etaLine.setFrame_(NSMakeRect(0, y - 126, p.bounds().size.width, 18))
        self._etaLine.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._etaLine)

    @objc.python_method
    def _runLog(self, msg):
        import time as _t
        self._run_log.append(f"{_t.strftime('%H:%M:%S')}  {msg}")
        self._app.log_(msg, "info", "migrate")

    @objc.python_method
    def _startMigration(self):
        lib = self._app.activeLibrary()
        if lib is None or not self._plan or not self._plan.operations:
            _alert("Nimic de migrat.")
            return
        # doesn't-fit sheet
        if self._free is not None and self._required > self._free:
            a = NSAlert.alloc().init()
            a.setMessageText_("NU ÎNCAPE pe destinație.")
            a.setInformativeText_(
                f"Necesar ~{theme.human_size(self._required)}, liber "
                f"{theme.human_size(self._free)}. Copierea se va opri cu eroare "
                f"când se umple discul. Continui totuși?")
            a.addButtonWithTitle_("Continuă")
            a.addButtonWithTitle_("Anulează")
            if a.runModal() != 1000:
                return
        if self._db_mode in ("fresh", "copy") and scanner.is_serato_running():
            a = NSAlert.alloc().init()
            a.setMessageText_("Serato DJ Pro rulează.")
            a.setInformativeText_("Închide Serato înainte de a scrie baza de date "
                                  "la destinație, altfel poate suprascrie schimbările.")
            a.addButtonWithTitle_("Am închis, continuă")
            a.addButtonWithTitle_("Anulează")
            if a.runModal() != 1000:
                return
        a = NSAlert.alloc().init()
        a.setMessageText_(
            f"Se copiază {self._plan.primary_count} fișiere "
            f"({theme.human_size(self._plan.total_bytes)}) plus "
            f"{self._plan.link_count} hard link-uri.")
        a.setInformativeText_("Fișierele originale NU sunt șterse. Continui?")
        a.addButtonWithTitle_("Începe")
        a.addButtonWithTitle_("Anulează")
        if a.runModal() != 1000:
            return

        self._run_log = []
        import time as _t
        self._t0 = _t.time()
        self._go(4)
        self._bar.startAnimation_(None)
        self._app._beginBusy_("migrare")
        plan = self._plan
        dest_root = Path(self._dest)
        db_mode = self._db_mode
        do_backup = self._backup
        backup_name = self._backupName(lib)

        def cb(done, total, op):
            AppHelper.callAfter(self._progress_, done, total, str(op.dest_path.name))

        def work():
            err = None
            try:
                if do_backup:
                    AppHelper.callAfter(self._phaseTo_, "Backup bază de date")
                    copier.export_database(lib, dest_root / backup_name)
                    AppHelper.callAfter(self._runLog, f"Backup scris: {backup_name}")
                AppHelper.callAfter(self._phaseTo_, "Copiere fișiere")
                AppHelper.callAfter(self._bar.setIndeterminate_, False)
                copier.execute_plan(plan, progress_callback=cb)
                AppHelper.callAfter(self._runLog, "Fișiere copiate")
                if db_mode == "fresh":
                    AppHelper.callAfter(self._phaseTo_, "Bază de date nouă")
                    AppHelper.callAfter(self._bar.setIndeterminate_, True)
                    copier.write_fresh_serato([lib], plan, dest_root / "_Serato_", dest_root)
                    AppHelper.callAfter(self._runLog, "Bază de date nouă generată")
                else:
                    AppHelper.callAfter(self._phaseTo_, "Copiere „_Serato_”")
                    AppHelper.callAfter(self._bar.setIndeterminate_, True)
                    dsd = copier.copy_serato_folder(lib, dest_root)
                    AppHelper.callAfter(self._runLog, "Folder „_Serato_” copiat")
                    AppHelper.callAfter(self._phaseTo_, "Rescriere căi")
                    copier.rewrite_serato_database(lib, plan, dsd, dest_root)
                    AppHelper.callAfter(self._runLog, "Căi rescrise")
            except Exception:
                err = traceback.format_exc()
            AppHelper.callAfter(self._migrationDone_, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _phaseTo_(self, name):
        self._phase.setStringValue_(name)
        self._runLog(name)

    @objc.python_method
    def _progress_(self, done, total, name):
        import time as _t
        frac = (done / total) if total else 0
        self._bar.setMinValue_(0.0)
        self._bar.setMaxValue_(float(total or 1))
        self._bar.setDoubleValue_(float(done))
        self._progLine.setStringValue_(
            f"Copiere {theme.format_int(done)} / {theme.format_int(total)} fișiere · {frac*100:.0f}%")
        self._curFile.setStringValue_(name)
        el = _t.time() - self._t0
        eta = ""
        if done > 30 and frac > 0:
            rem = el / frac - el
            eta = f" · rămas ~{int(rem//60)}m {int(rem%60)}s"
        self._etaLine.setStringValue_(
            f"Timp scurs: {int(el//60)}m {int(el%60)}s{eta}")

    @objc.python_method
    def _migrationDone_(self, err):
        self._bar.stopAnimation_(None)
        self._app._endBusy_("migrare")
        if err:
            self._runLog("EROARE: " + err.strip().splitlines()[-1])
            self._app.log_("Migrare eșuată:\n" + err, "error", "migrate")
            _alert("Migrarea a eșuat.", informative="Vezi Jurnal pentru detalii.")
            self._go(3)
            return
        self._go(5)

    # ================================================== step 5 — Verificare-post
    @objc.python_method
    def _buildPostVerify(self):
        p = self._panel(5)
        self._pvText = NSTextView.alloc().initWithFrame_(p.bounds())
        self._pvText.setEditable_(False)
        self._pvText.setDrawsBackground_(False)
        self._pvText.setFont_(NSFont.systemFontOfSize_(13))
        self._pvText.setAutoresizingMask_(_AUTOSIZE)
        p.addSubview_(self._pvText)

    @objc.python_method
    def _renderPostVerify(self):
        self._pvText.setString_("Verific rezultatul migrării…")
        self._nextBtn.setEnabled_(False)
        plan = self._plan
        dest_root = Path(self._dest)
        import time as _t
        dur = _t.time() - self._t0

        def work():
            files_ok = files_bad = 0
            failures = []
            for op in plan.operations:
                if not op.is_primary:
                    continue
                try:
                    if op.dest_path.exists() and \
                       op.dest_path.stat().st_size == op.source_path.stat().st_size:
                        files_ok += 1
                    else:
                        files_bad += 1
                        failures.append(f"{op.source_path.name}: dimensiune diferită / lipsă")
                except OSError as e:
                    files_bad += 1
                    failures.append(f"{op.source_path.name}: {e}")
            db_ok = False
            db_count = 0
            try:
                import serato_db as _sdb
                dbp = dest_root / "_Serato_" / "database V2"
                if dbp.is_file():
                    tracks = _sdb.parse_database(dbp, str(dest_root))
                    db_count = len(tracks)
                    db_ok = db_count > 0
            except Exception:
                db_ok = False
            AppHelper.callAfter(self._pvReady_, files_ok, files_bad, failures,
                                db_ok, db_count, dur)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _pvReady_(self, ok, bad, failures, db_ok, db_count, dur):
        lib = self._app.activeLibrary()
        crates_n = len(self._sel_keys) if self._sel_keys is not None else \
            (len(lib.crates) if lib else 0)
        self._verify = (ok, bad, failures, db_ok, db_count, dur)
        dm = f"{int(dur//60)}m {int(dur%60)}s"
        if bad == 0 and db_ok:
            txt = [
                "Migrare finalizată",
                "",
                f"✓ {theme.format_int(ok)} fișiere copiate și verificate ({theme.format_int(ok)} / {theme.format_int(ok)})",
                f"✓ {theme.format_int(crates_n)} crate-uri migrate",
                f"✓ Baza de date poate fi citită ({theme.format_int(db_count)} track-uri)",
                "",
                f"Durată: {dm}",
            ]
        else:
            txt = [
                "Migrare finalizată cu avertismente",
                "",
                f"{theme.format_int(ok)} reușite · {theme.format_int(bad)} eșuate",
                ("✓ Baza de date poate fi citită" if db_ok
                 else "⚠ Baza de date nouă nu a putut fi citită"),
                "",
                f"Durată: {dm}",
            ]
        self._pvText.setString_("\n".join(txt))
        self._nextBtn.setEnabled_(True)
        if failures:
            self._runLog(f"Verificare-post: {bad} eșuate")

    # ================================================== step 6 — Complet
    @objc.python_method
    def _buildComplete(self):
        p = self._panel(6)
        y = p.bounds().size.height
        self._doneMsg = theme.make_label("Migrare completă.", style="title2")
        self._doneMsg.setFrame_(NSMakeRect(0, y - 30, p.bounds().size.width, 24))
        self._doneMsg.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._doneMsg)
        self._doneSub = theme.make_label("", style="secondary")
        self._doneSub.setFrame_(NSMakeRect(0, y - 54, p.bounds().size.width, 18))
        self._doneSub.setAutoresizingMask_(1 << 3 | 1 << 1)
        p.addSubview_(self._doneSub)
        rb = _button("Deschide în Finder", self, b"revealDest:")
        rb.setFrame_(NSMakeRect(0, y - 96, 170, 28))
        rb.setAutoresizingMask_(1 << 3)
        p.addSubview_(rb)
        lb = _button("Vezi jurnalul acestei migrări", self, b"showRunLog:")
        lb.setFrame_(NSMakeRect(180, y - 96, 240, 28))
        lb.setAutoresizingMask_(1 << 3)
        p.addSubview_(lb)

    @objc.python_method
    def _renderComplete(self):
        if self._verify:
            ok, bad, _f, db_ok, db_count, dur = self._verify
            self._doneMsg.setStringValue_(
                "Migrare completă" if bad == 0 and db_ok
                else "Migrare completă (cu avertismente)")
            self._doneSub.setStringValue_(
                f"{theme.format_int(ok)} fișiere la {self._dest}")

    def revealDest_(self, sender):
        from AppKit import NSWorkspace
        from Foundation import NSURL
        if self._dest:
            NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
                [NSURL.fileURLWithPath_(self._dest)])

    def showRunLog_(self, sender):
        _alert("Jurnalul acestei migrări",
               informative="\n".join(self._run_log) or "(gol)")


# ------------------------------------------------------------------- Metadata
_MD_FIELDS = [("artist", "tart", "Artist"), ("title", "tsng", "Titlu"),
              ("album", "talb", "Album"), ("genre", "tgen", "Gen")]
_MULTI = "— Valori multiple —"


class MetadataScreen(BaseScreen):
    def build_(self, v):
        self._rows = []          # list[Track] index-aligned with the table
        self._inspector = None
        self._headerInto_title_subtitle_(
            v, "Metadata", "Găsește și corectează Artist / Titlu / Album / Gen")
        y = v.bounds().size.height

        from AppKit import NSSegmentedControl
        seg = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(24, y - 96, 420, 24))
        seg.setSegmentCount_(4)
        for i, t in enumerate(("Toate", "Incomplete", "Fără artist", "Fără titlu")):
            seg.setLabel_forSegment_(t, i)
            seg.setWidth_forSegment_(104, i)
        seg.setSelectedSegment_(0)
        seg.setTarget_(self); seg.setAction_(b"filterChanged:")
        seg.setAutoresizingMask_(1 << 3)
        self._seg = seg
        v.addSubview_(seg)

        self._search = NSSearchField.alloc().initWithFrame_(NSMakeRect(456, y - 96, 240, 24))
        self._search.setAutoresizingMask_(1 << 3)
        self._search.setPlaceholderString_("Caută")
        self._search.setTarget_(self); self._search.setAction_(b"filterChanged:")
        v.addSubview_(self._search)

        an = _button("Analizează Artist/Titlu lipsă", self, b"analyze:")
        an.setFrame_(NSMakeRect(708, y - 98, 240, 28))
        an.setAutoresizingMask_(1 << 3 | 1 << 0)
        v.addSubview_(an)

        body = self._bodyContainerIn_(v, top=112)
        # left: results table
        self._tv, self._ds, scroll = _table(
            ["artist", "title", "album", "genre", "file"],
            ["Artist", "Titlu", "Album", "Gen", "Fișier"], [150, 190, 140, 100, 220])
        scroll.setFrame_(NSMakeRect(0, 0, body.bounds().size.width - 320,
                                    body.bounds().size.height))
        scroll.setAutoresizingMask_(_AUTOSIZE)
        body.addSubview_(scroll)
        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"selChanged:", "NSTableViewSelectionDidChangeNotification", self._tv)

        # right: bulk editor
        self._bulk = _FlippedView.alloc().initWithFrame_(
            NSMakeRect(body.bounds().size.width - 300, 0, 300, body.bounds().size.height))
        self._bulk.setAutoresizingMask_(1 << 0 | 1 << 4)
        body.addSubview_(self._bulk)
        self._buildBulk()
        self._selCount = 0

    def didBecomeVisible(self):
        self._reload()

    def librariesChanged(self):
        self._reload()

    # ---- Track Inspector for a single selection (UI-15) ----
    @objc.python_method
    def _ensureInspector(self):
        if self._inspector is None:
            from .track_inspector import TrackInspector
            self._inspector = TrackInspector.alloc().initWithApp_(self._app)
        return self._inspector

    def inspectorView(self):
        if len(self._tv.selectedRowIndexes()) != 1:
            return None
        return self._ensureInspector().view()

    # ---- filtering ----
    def filterChanged_(self, sender):
        self._reload()

    @objc.python_method
    def _reload(self):
        lib = self._app.activeLibrary()
        if lib is None:
            self._rows = []
            self._ds.setData_([])
            self._tv.reloadData()
            self._renderBulk()
            return
        mode = self._seg.selectedSegment()
        q = self._search.stringValue().strip().lower()
        out = []
        for rp, t in lib.tracks.items():
            a = (t.artist or "").strip()
            ti = (t.title or "").strip()
            g = (t.genre or "").strip()
            if mode == 1 and (a and ti and g):
                continue
            if mode == 2 and a:
                continue
            if mode == 3 and ti:
                continue
            if q:
                blob = " ".join(x or "" for x in (t.artist, t.title, t.album, t.genre, rp)).lower()
                if q not in blob:
                    continue
            out.append(t)
            if len(out) >= 2000:
                break
        self._rows = out
        self._ds.setData_([((t.artist or ""), (t.title or ""), (t.album or ""),
                            (t.genre or ""), Path(t.abs_path).name) for t in out])
        self._tv.reloadData()
        self._renderBulk()

    # ---- bulk editor ----
    @objc.python_method
    def _buildBulk(self):
        self._bChk = {}
        self._bFld = {}
        h = self._bulk.bounds().size.height
        self._bTitle = theme.make_label("", style="headline")
        self._bTitle.setFrame_(NSMakeRect(0, 6, 300, 20))
        self._bulk.addSubview_(self._bTitle)
        yy = 40
        for key, _tag, label in _MD_FIELDS:
            chk = NSButton.alloc().initWithFrame_(NSMakeRect(0, yy, 300, 20))
            chk.setButtonType_(NSSwitchButton)
            chk.setTitle_(f"Actualizează {label}")
            chk.setTarget_(self); chk.setAction_(b"bulkChkToggled:")
            self._bulk.addSubview_(chk)
            fld = NSTextField.alloc().initWithFrame_(NSMakeRect(0, yy + 22, 300, 22))
            fld.setFont_(theme.font("body"))
            fld.setEnabled_(False)
            self._bulk.addSubview_(fld)
            self._bChk[key] = chk
            self._bFld[key] = fld
            yy += 54
        self._bId3 = NSButton.alloc().initWithFrame_(NSMakeRect(0, yy, 300, 20))
        self._bId3.setButtonType_(NSSwitchButton)
        self._bId3.setTitle_("Scrie modificările și în tag-urile ID3")
        self._bId3.setState_(1)
        self._bulk.addSubview_(self._bId3)
        yy += 30
        self._bApply = NSButton.alloc().initWithFrame_(NSMakeRect(0, yy, 300, 30))
        self._bApply.setBezelStyle_(NSBezelStyleRounded)
        self._bApply.setTitle_("Aplică")
        self._bApply.setTarget_(self); self._bApply.setAction_(b"applyBulk:")
        self._bulk.addSubview_(self._bApply)

    def bulkChkToggled_(self, sender):
        for key, chk in self._bChk.items():
            self._bFld[key].setEnabled_(chk.state() == 1)

    @objc.python_method
    def _selectedTracks(self):
        idx = self._tv.selectedRowIndexes()
        out = []
        i = idx.firstIndex()
        while i != _NSNotFound:
            if 0 <= i < len(self._rows):
                out.append(self._rows[i])
            i = idx.indexGreaterThanIndex_(i)
        return out

    def selChanged_(self, note):
        self._renderBulk()
        if self._app._router is not None:
            sel = self._selectedTracks()
            if len(sel) == 1:
                self._ensureInspector().set_track(
                    self._app.activeLibrary(), sel[0], on_saved=self._reload)
            self._app._router.refreshInspector()

    @objc.python_method
    def _renderBulk(self):
        sel = self._selectedTracks()
        self._selCount = len(sel)
        if len(sel) < 2:
            self._bTitle.setStringValue_(
                "Selectează 2+ track-uri pentru editare în bloc"
                if len(sel) == 0 else "1 track — editează în inspector")
            for key, _t, _l in _MD_FIELDS:
                self._bChk[key].setEnabled_(False)
                self._bFld[key].setEnabled_(False)
                self._bFld[key].setStringValue_("")
            self._bApply.setEnabled_(False)
            return
        self._bTitle.setStringValue_(f"{len(sel)} track-uri selectate")
        for key, _tag, _label in _MD_FIELDS:
            vals = {(getattr(t, key) or "").strip() for t in sel}
            self._bChk[key].setEnabled_(True)
            fld = self._bFld[key]
            if len(vals) == 1:
                common = next(iter(vals))
                fld.setStringValue_(common)
                fld.setPlaceholderString_("(gol)" if not common else "")
            else:
                fld.setStringValue_("")
                fld.setPlaceholderString_(_MULTI)
            fld.setEnabled_(self._bChk[key].state() == 1)
        self._bApply.setEnabled_(True)
        self._bApply.setTitle_(f"Aplică la {len(sel)} track-uri")

    def applyBulk_(self, sender):
        lib = self._app.activeLibrary()
        sel = self._selectedTracks()
        if lib is None or len(sel) < 2:
            return
        changes = {}
        for key, tag, label in _MD_FIELDS:
            if self._bChk[key].state() == 1:
                changes[tag] = (label, self._bFld[key].stringValue())
        if not changes:
            _alert("Bifează cel puțin un câmp de actualizat.")
            return
        summary = "\n".join(
            f"• {label} → „{val}”" if val else f"• {label} → (gol)"
            for label, val in changes.values())
        a = NSAlert.alloc().init()
        a.setMessageText_(f"Aplici modificările la {len(sel)} track-uri?")
        a.setInformativeText_(summary + "\n\n"
                              + ("Se scriu și tag-urile ID3." if self._bId3.state() == 1
                                 else "Doar în baza de date Serato."))
        a.addButtonWithTitle_("Aplică")
        a.addButtonWithTitle_("Anulează")
        if a.runModal() != 1000:
            return
        edits = {t.raw_path: {tag: val for tag, (_l, val) in changes.items()} for t in sel}
        write_id3 = self._bId3.state() == 1
        self._app._beginBusy_("metadata")
        self._app.log_(f"Metadata în bloc: {len(edits)} track-uri, câmpuri "
                       + ", ".join(l for l, _v in changes.values()), "info", "metadata")

        def work():
            err = None
            try:
                metadata_editor.apply_edits(lib, edits, write_id3=write_id3)
            except Exception:
                err = traceback.format_exc()
            AppHelper.callAfter(self._bulkDone_, changes, sel, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _bulkDone_(self, changes, sel, err):
        self._app._endBusy_("metadata")
        if err:
            self._app.log_("Eroare metadata în bloc:\n" + err, "error", "metadata")
            _alert("Aplicarea a eșuat (vezi Jurnal).")
            return
        for t in sel:
            for _tag, (label, val) in changes.items():
                key = next(k for k, tg, _l in _MD_FIELDS if _l == label)
                setattr(t, key, val or None)
        self._app.log_(f"Metadata actualizată pentru {len(sel)} track-uri", "info", "metadata")
        self._reload()

    # ---- Analizează Artist/Titlu lipsă (sheet) ----
    def analyze_(self, sender):
        lib = self._app.activeLibrary()
        if lib is None:
            return
        self._app._beginBusy_("metadata")

        def work():
            try:
                sugg = metadata_editor.suggest_artist_title_fixes(lib)
                err = None
            except Exception:
                sugg, err = [], traceback.format_exc()
            AppHelper.callAfter(self._analyzeDone_, sugg, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _analyzeDone_(self, sugg, err):
        self._app._endBusy_("metadata")
        if err:
            self._app.log_("Eroare analiză Artist/Titlu:\n" + err, "error", "metadata")
            _alert("Analiza a eșuat (vezi Jurnal).")
            return
        if not sugg:
            _alert("Nu am găsit track-uri de corectat automat.")
            return
        preview = "\n".join(
            f"• {s.filename}\n    {s.new_artist}  —  {s.new_title}"
            for s in sugg[:25])
        more = f"\n\n(+{len(sugg) - 25} altele)" if len(sugg) > 25 else ""
        a = NSAlert.alloc().init()
        a.setMessageText_(f"{len(sugg)} track-uri pot fi corectate")
        a.setInformativeText_(preview + more)
        a.addButtonWithTitle_(f"Aplică toate ({len(sugg)})")
        a.addButtonWithTitle_("Anulează")
        if a.runModal() != 1000:
            return
        lib = self._app.activeLibrary()
        edits = {s.raw_path: {"tart": s.new_artist, "tsng": s.new_title} for s in sugg}
        self._app._beginBusy_("metadata")

        def work():
            err = None
            try:
                metadata_editor.apply_edits(lib, edits, write_id3=True)
            except Exception:
                err = traceback.format_exc()
            AppHelper.callAfter(self._applyAnalyzeDone_, len(edits), err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _applyAnalyzeDone_(self, n, err):
        self._app._endBusy_("metadata")
        if err:
            self._app.log_("Eroare aplicare analiză:\n" + err, "error", "metadata")
            _alert("Aplicarea a eșuat (vezi Jurnal).")
            return
        self._app.log_(f"Artist/Titlu corectate pentru {n} track-uri", "info", "metadata")
        _alert(f"{n} track-uri corectate.")
        self._app.rescanLibraries_(None)


# ------------------------------------------------------------------- Journal
def _lvl_norm(level):
    return "warn" if level in ("warn", "warning") else (level or "info")


_LVL_ICON = {"info": "•", "warn": "⚠", "error": "✕"}


class JournalScreen(BaseScreen):
    def build_(self, v):
        self._mode = 0           # 0 Activitate, 1 Raw
        self._sub = 0            # 0 Toate, 1 Info, 2 Avertismente, 3 Erori
        self._headerInto_title_subtitle_(v, "Jurnal", "Istoricul operațiunilor")
        y = v.bounds().size.height

        from AppKit import NSSegmentedControl
        seg = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(24, y - 96, 220, 24))
        seg.setSegmentCount_(2)
        seg.setLabel_forSegment_("Activitate", 0)
        seg.setLabel_forSegment_("Raw Log", 1)
        seg.setWidth_forSegment_(110, 0)
        seg.setWidth_forSegment_(110, 1)
        seg.setSelectedSegment_(0)
        seg.setTarget_(self); seg.setAction_(b"modeChanged:")
        seg.setAutoresizingMask_(1 << 3)
        self._seg = seg
        v.addSubview_(seg)

        sub = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(256, y - 96, 340, 24))
        sub.setSegmentCount_(4)
        for i, t in enumerate(("Toate", "Info", "Avertismente", "Erori")):
            sub.setLabel_forSegment_(t, i)
            sub.setWidth_forSegment_(84, i)
        sub.setSelectedSegment_(0)
        sub.setTarget_(self); sub.setAction_(b"subChanged:")
        sub.setAutoresizingMask_(1 << 3)
        self._subSeg = sub
        v.addSubview_(sub)

        self._search = NSSearchField.alloc().initWithFrame_(NSMakeRect(608, y - 96, 200, 24))
        self._search.setPlaceholderString_("Caută")
        self._search.setTarget_(self); self._search.setAction_(b"searchChanged:")
        self._search.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._search)

        cp = _button("Copiază", self, b"copyLog:")
        cp.setFrame_(NSMakeRect(24, y - 132, 90, 26)); cp.setAutoresizingMask_(1 << 3)
        v.addSubview_(cp); self._btnCopy = cp
        cl = _button("Golește", self, b"clear:")
        cl.setFrame_(NSMakeRect(120, y - 132, 90, 26)); cl.setAutoresizingMask_(1 << 3)
        v.addSubview_(cl)
        ex = _button("Export…", self, b"exportLog:")
        ex.setFrame_(NSMakeRect(216, y - 132, 100, 26)); ex.setAutoresizingMask_(1 << 3)
        v.addSubview_(ex)

        body = self._bodyContainerIn_(v, top=152)
        scroll = NSScrollView.alloc().initWithFrame_(body.bounds())
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(0)
        scroll.setAutoresizingMask_(_AUTOSIZE)
        self._text = NSTextView.alloc().initWithFrame_(body.bounds())
        self._text.setEditable_(False)
        self._text.setAutoresizingMask_(1 << 1)
        scroll.setDocumentView_(self._text)
        body.addSubview_(scroll)
        self.journalChanged()

    def didBecomeVisible(self):
        self.journalChanged()

    def modeChanged_(self, sender):
        self._mode = self._seg.selectedSegment()
        raw = self._mode == 1
        self._subSeg.setHidden_(raw)
        self._search.setHidden_(raw)
        self.journalChanged()

    def subChanged_(self, sender):
        self._sub = self._subSeg.selectedSegment()
        self.journalChanged()

    def searchChanged_(self, sender):
        self.journalChanged()

    @objc.python_method
    def _rawText(self):
        out = []
        for e in self._app.journal():
            dt, level, op, msg = e[0], _lvl_norm(e[1]), e[2], e[3]
            hhmm = dt.descriptionWithLocale_(None)[11:19]
            mark = {"info": " ", "warn": "⚠", "error": "✕"}.get(level, " ")
            tag = f"[{op}] " if op else ""
            out.append(f"{hhmm} {mark} {tag}{msg}")
        return "\n".join(out)

    @objc.python_method
    def _activityText(self):
        from datetime import datetime
        q = self._search.stringValue().strip().lower()
        want = {1: "info", 2: "warn", 3: "error"}.get(self._sub)
        groups = []
        cur_day = None
        buf = []
        today = datetime.now().date()
        for e in self._app.journal():
            dt, level, op, msg, detail = e[0], _lvl_norm(e[1]), e[2], e[3], (e[4] if len(e) > 4 else None)
            if want and level != want:
                continue
            if q and q not in (msg or "").lower() and q not in (op or "").lower() \
               and q not in (str(detail) or "").lower():
                continue
            iso = dt.descriptionWithLocale_(None)  # 'YYYY-MM-DD HH:MM:SS ...'
            day = iso[:10]
            hhmm = iso[11:16]
            try:
                d = datetime.strptime(day, "%Y-%m-%d").date()
                label = ("ASTĂZI" if d == today
                         else "IERI" if (today - d).days == 1
                         else day)
            except ValueError:
                label = day
            if label != cur_day:
                if buf:
                    groups.append("\n".join(buf))
                buf = [label]
                cur_day = label
            icon = _LVL_ICON.get(level, "•")
            oppart = f"  {op}" if op else ""
            det = f"        {detail}" if detail else ""
            buf.append(f"  {icon} {hhmm}{oppart}  {msg}{det}")
        if buf:
            groups.append("\n".join(buf))
        return "\n\n".join(groups)

    def journalChanged(self):
        if not self._app.journal():
            self._text.setString_("Nu există evenimente în jurnal.")
            return
        if self._mode == 1:
            self._text.setFont_(NSFont.userFixedPitchFontOfSize_(12))
            self._text.setString_(self._rawText())
        else:
            self._text.setFont_(NSFont.systemFontOfSize_(13))
            txt = self._activityText()
            self._text.setString_(txt or "Niciun eveniment pentru acest filtru.")
        self._text.scrollRangeToVisible_((len(self._text.string()), 0))

    def copyLog_(self, sender):
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(
            self._rawText() if self._mode == 1 else self._activityText(),
            NSPasteboardTypeString)

    def exportLog_(self, sender):
        from AppKit import NSSavePanel
        from datetime import datetime
        panel = NSSavePanel.savePanel()
        panel.setNameFieldStringValue_(
            f"Serato Migrator - jurnal - {datetime.now():%Y-%m-%d %H%M}.txt")
        panel.setPrompt_("Export")
        if panel.runModal() != 1:
            return
        try:
            Path(panel.URL().path()).write_text(self._rawText(), encoding="utf-8")
            self._app.log_("Jurnal exportat", "info", "jurnal")
        except Exception:
            _alert("Exportul a eșuat.")

    def clear_(self, sender):
        self._app.clearJournal()
        self.journalChanged()


_SCREENS = {
    "overview": OverviewScreen,
    "libraries": LibrariesScreen,
    "crates": CratesScreen,
    "orphans": OrphansScreen,
    "migrate": MigrateScreen,
    "metadata": MetadataScreen,
    "journal": JournalScreen,
}


def make_screen(dest_id, delegate):
    cls = _SCREENS.get(dest_id, OverviewScreen)
    vc = cls.alloc().initWithDelegate_(delegate)
    vc.view()  # force loadView
    return vc


def _human(n: int) -> str:
    return theme.human_size(n)


def _human_OLD(n: int) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"
