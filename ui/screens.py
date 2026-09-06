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
)
from Foundation import NSObject, NSMakeRect, NSDate, NSIndexSet
from PyObjCTools import AppHelper

import scanner
import copier

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
        self._stack.setEdgeInsets_((46, 28, 28, 28))
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
class CratesScreen(BaseScreen):
    def build_(self, v):
        self._headerInto_title_subtitle_(v, "Crate-uri", None)
        body = self._bodyContainerIn_(v)
        self._cratesTv, self._cratesDs, cs = _table(["crate", "count"], ["Crate", "Track-uri"], [260, 90])
        cs.setFrame_(NSMakeRect(0, 0, 360, body.bounds().size.height))
        cs.setAutoresizingMask_(1 << 4)
        body.addSubview_(cs)
        self._tracksTv, self._tracksDs, ts = _table(
            ["status", "artist", "title", "path"], ["", "Artist", "Titlu", "Cale"], [30, 160, 200, 320])
        ts.setFrame_(NSMakeRect(372, 0, body.bounds().size.width - 372, body.bounds().size.height))
        ts.setAutoresizingMask_(_AUTOSIZE)
        body.addSubview_(ts)
        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"crateSelected:", "NSTableViewSelectionDidChangeNotification", self._cratesTv)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"trackSelected:", "NSTableViewSelectionDidChangeNotification", self._tracksTv)
        self._crate_tracks = []   # Track|None per visible row, index-aligned
        self._inspector = None
        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

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
        # a metadata save changed the in-memory Track -> refresh the visible row
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

    def render(self):
        lib = self._app.activeLibrary()
        self._crates = lib.crates if lib else []
        self._cratesDs.setData_([(c.display_name, str(len(c.raw_paths))) for c in self._crates])
        self._cratesTv.reloadData()
        self._tracksDs.setData_([])
        self._tracksTv.reloadData()
        self._crate_tracks = []
        self._selected_track = None
        if self._app._router is not None:
            self._app._router.refreshInspector()

    def crateSelected_(self, note):
        row = self._cratesTv.selectedRow()
        lib = self._app.activeLibrary()
        if row < 0 or lib is None or row >= len(self._crates):
            return
        crate = self._crates[row]
        rows = []
        tracks = []
        for rp in crate.raw_paths:
            ap = Path(lib.volume_root) / rp
            t = lib.tracks.get(rp)
            tracks.append(t)
            rows.append(("✓" if ap.exists() else "⚠",
                         (t.artist if t else "") or "", (t.title if t else "") or "", str(ap)))
        self._crate_tracks = tracks
        self._selected_track = None
        self._tracksDs.setData_(rows)
        self._tracksTv.reloadData()
        if self._app._router is not None:
            self._app._router.refreshInspector()


# ------------------------------------------------------------------- Orphans
class OrphansScreen(BaseScreen):
    def build_(self, v):
        self._headerInto_title_subtitle_(v, "Fișiere orfane", "Fișiere audio de pe disc necunoscute de Serato")
        self._info = _label("Alege o bibliotecă și scanează.", secondary=True)
        self._info.setFrame_(NSMakeRect(24, v.bounds().size.height - 104, 700, 18))
        self._info.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._info)
        self._scanBtn = _button("Scanează după orfane", self, b"scan:")
        self._scanBtn.setFrame_(NSMakeRect(24, v.bounds().size.height - 140, 200, 28))
        self._scanBtn.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._scanBtn)
        body = self._bodyContainerIn_(v, top=160)
        self._tv, self._ds, scroll = _table(["path", "size"], ["Cale", "Mărime"], [640, 100])
        scroll.setFrame_(body.bounds())
        body.addSubview_(scroll)

    def scan_(self, sender):
        lib = self._app.activeLibrary()
        if lib is None:
            self._info.setStringValue_("Nicio bibliotecă activă.")
            return
        self._scanBtn.setEnabled_(False)
        self._info.setStringValue_("Se scanează…")
        self._app.log_(f"Scanez {lib.volume_root} după fișiere orfane…", "info", "orphans")
        root = str(lib.volume_root)
        known = {t.abs_path for t in lib.tracks.values()}

        def work():
            try:
                orphans = scanner.find_orphan_files(root, known)
            except Exception:
                orphans = []
                self._app.log_("Eroare scanare orfane:\n" + traceback.format_exc(), "error", "orphans")
            AppHelper.callAfter(self._done_, orphans)

        threading.Thread(target=work, daemon=True).start()

    def _done_(self, orphans):
        self._scanBtn.setEnabled_(True)
        total = 0
        rows = []
        for p in orphans:
            try:
                sz = p.stat().st_size
            except OSError:
                sz = 0
            total += sz
            rows.append((str(p), _human(sz)))
        self._ds.setData_(rows)
        self._tv.reloadData()
        if orphans:
            self._info.setStringValue_(f"{len(orphans)} fișiere orfane · {_human(total)}")
        else:
            self._info.setStringValue_("✓ Nu au fost găsite fișiere orfane")
        self._app.log_(f"Scanare orfane: {len(orphans)} găsite", "info", "orphans")


# ------------------------------------------------------------------- Migrate
class MigrateScreen(BaseScreen):
    def build_(self, v):
        self._headerInto_title_subtitle_(v, "Migrare", "Copiază track-urile în foldere numite după crate-uri, pe o destinație nouă")
        self._src = _label("", secondary=True)
        self._src.setFrame_(NSMakeRect(24, v.bounds().size.height - 108, 800, 18))
        self._src.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._src)
        self._dest = ""
        self._destLabel = _label("Destinație: (nicio)", secondary=True)
        self._destLabel.setFrame_(NSMakeRect(24, v.bounds().size.height - 132, 800, 18))
        self._destLabel.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._destLabel)
        b1 = _button("Alege destinația…", self, b"chooseDest:")
        b1.setFrame_(NSMakeRect(24, v.bounds().size.height - 172, 180, 28))
        b1.setAutoresizingMask_(1 << 3)
        v.addSubview_(b1)
        b2 = _button("Previzualizare", self, b"preview:")
        b2.setFrame_(NSMakeRect(214, v.bounds().size.height - 172, 150, 28))
        b2.setAutoresizingMask_(1 << 3)
        v.addSubview_(b2)
        self._summary = _label("", size=13)
        self._summary.setFrame_(NSMakeRect(24, v.bounds().size.height - 220, 820, 40))
        self._summary.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._summary)
        self._plan = None
        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

    def render(self):
        lib = self._app.activeLibrary()
        if lib:
            self._src.setStringValue_(
                f"Sursă: {lib.name} — {lib.volume_root} · {theme.format_int(len(lib.present_tracks))} track-uri · {theme.format_int(len(lib.crates))} crate-uri")
        else:
            self._src.setStringValue_("Sursă: (nicio bibliotecă)")

    def chooseDest_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setPrompt_("Alege")
        if panel.runModal() == 1:
            self._dest = panel.URLs()[0].path()
            self._destLabel.setStringValue_(f"Destinație: {self._dest}")

    def preview_(self, sender):
        lib = self._app.activeLibrary()
        if lib is None or not self._dest:
            self._summary.setStringValue_("Alege biblioteca și destinația întâi.")
            return
        self._summary.setStringValue_("Calculez planul…")
        dest = self._dest

        def work():
            try:
                plan = copier.plan_copy([lib], Path(dest))
                free = copier.free_space(Path(dest))
                req = copier.estimate_required_bytes(plan, Path(dest),
                                                     lib.serato_dir)
            except Exception:
                self._app.log_("Eroare previzualizare:\n" + traceback.format_exc(), "error", "migrate")
                AppHelper.callAfter(self._summary.setStringValue_, "Eroare la previzualizare (vezi Jurnal).")
                return
            AppHelper.callAfter(self._planReady_, plan, req, free)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _planReady_(self, plan, req, free):
        self._plan = plan
        fit = "✓ Încape" if (free is None or req <= free) else "✕ NU ÎNCAPE"
        self._summary.setStringValue_(
            f"{plan.primary_count} copii · {plan.link_count} hardlink-uri · "
            f"{_human(plan.total_bytes)} · necesar ~{_human(req)}"
            + (f" · liber {_human(free)}" if free else "") + f"   {fit}")
        self._app.log_(f"Plan migrare: {plan.primary_count} fișiere, {_human(plan.total_bytes)}", "info", "migrate")


# ------------------------------------------------------------------- Metadata
class MetadataScreen(BaseScreen):
    def build_(self, v):
        self._headerInto_title_subtitle_(v, "Metadata", "Găsește și corectează Artist / Titlu / Album / Gen")
        self._search = NSSearchField.alloc().initWithFrame_(
            NSMakeRect(24, v.bounds().size.height - 110, 280, 24))
        self._search.setAutoresizingMask_(1 << 3)
        self._search.setTarget_(self)
        self._search.setAction_(b"doSearch:")
        v.addSubview_(self._search)
        body = self._bodyContainerIn_(v, top=126)
        self._tv, self._ds, scroll = _table(
            ["artist", "title", "album", "genre", "file"],
            ["Artist", "Titlu", "Album", "Gen", "Fișier"], [150, 200, 150, 100, 220])
        scroll.setFrame_(body.bounds())
        body.addSubview_(scroll)

    def didBecomeVisible(self):
        pass

    def doSearch_(self, sender):
        lib = self._app.activeLibrary()
        q = self._search.stringValue().lower()
        if lib is None or not q:
            self._ds.setData_([])
            self._tv.reloadData()
            return
        rows = []
        for rp, t in lib.tracks.items():
            blob = " ".join(x or "" for x in (t.artist, t.title, t.album, t.genre, rp)).lower()
            if q in blob:
                rows.append(((t.artist or ""), (t.title or ""), (t.album or ""),
                             (t.genre or ""), Path(t.abs_path).name))
            if len(rows) >= 500:
                break
        self._ds.setData_(rows)
        self._tv.reloadData()


# ------------------------------------------------------------------- Journal
class JournalScreen(BaseScreen):
    def build_(self, v):
        self._headerInto_title_subtitle_(v, "Jurnal", "Istoricul operațiunilor")
        b = _button("Golește", self, b"clear:")
        b.setFrame_(NSMakeRect(24, v.bounds().size.height - 110, 100, 26))
        b.setAutoresizingMask_(1 << 3)
        v.addSubview_(b)
        body = self._bodyContainerIn_(v, top=128)
        scroll = NSScrollView.alloc().initWithFrame_(body.bounds())
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)
        scroll.setAutoresizingMask_(_AUTOSIZE)
        self._text = NSTextView.alloc().initWithFrame_(body.bounds())
        self._text.setEditable_(False)
        self._text.setFont_(NSFont.userFixedPitchFontOfSize_(12))
        self._text.setAutoresizingMask_(1 << 1)
        scroll.setDocumentView_(self._text)
        body.addSubview_(scroll)
        self.journalChanged()

    def didBecomeVisible(self):
        self.journalChanged()

    def journalChanged(self):
        lines = []
        for entry in self._app.journal():
            dt, level, op, msg = entry[0], entry[1], entry[2], entry[3]
            hhmm = dt.descriptionWithLocale_(None)[11:19]
            mark = {"info": " ", "warning": "⚠", "error": "✕"}.get(level, " ")
            tag = f"[{op}] " if op else ""
            lines.append(f"{hhmm} {mark} {tag}{msg}")
        self._text.setString_("\n".join(lines))
        self._text.scrollRangeToVisible_((len(self._text.string()), 0))

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
