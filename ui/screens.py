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
from Foundation import NSObject, NSMakeRect, NSDate, NSIndexSet, NSNotFound as _NSNotFound
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
