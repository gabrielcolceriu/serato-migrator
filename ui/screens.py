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
    NSUserInterfaceLayoutOrientationVertical, NSTextView, NSOpenPanel,
    NSProgressIndicator, NSProgressIndicatorBarStyle, NSSearchField,
)
from Foundation import NSObject, NSMakeRect, NSDate
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


class _Rows(NSObject):
    """Generic NSTableView data source over a list of tuples + column keys."""

    def initWithColumns_(self, columns):
        self = objc.super(_Rows, self).init()
        if self is None:
            return None
        self._columns = list(columns)   # list of identifiers
        self._data = []                 # list[tuple]
        return self

    def setData_(self, data):
        self._data = list(data)

    def data(self):
        return self._data

    def numberOfRowsInTableView_(self, tv):
        return len(self._data)

    def tableView_objectValueForTableColumn_row_(self, tv, col, row):
        try:
            i = self._columns.index(col.identifier())
            return str(self._data[row][i])
        except Exception:
            return ""


def _table(columns, titles, widths):
    tv = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 400))
    tv.setUsesAlternatingRowBackgroundColors_(True)
    tv.setRowSizeStyle_(1)
    tv.setAllowsMultipleSelection_(True)
    for ident, title, w in zip(columns, titles, widths):
        c = NSTableColumn.alloc().initWithIdentifier_(ident)
        c.setTitle_(title)
        c.setWidth_(w)
        c.headerCell().setStringValue_(title)
        tv.addTableColumn_(c)
    ds = _Rows.alloc().initWithColumns_(columns)
    tv.setDataSource_(ds)
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 400))
    scroll.setDocumentView_(tv)
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(1)  # bezel; refined in UI-03
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
class OverviewScreen(BaseScreen):
    def build_(self, v):
        self._stack = NSStackView.alloc().initWithFrame_(v.bounds())
        self._stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        self._stack.setAlignment_(1)  # leading
        self._stack.setSpacing_(8)
        self._stack.setEdgeInsets_((24, 24, 24, 24))
        self._stack.setAutoresizingMask_(_AUTOSIZE)
        v.addSubview_(self._stack)
        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

    def render(self):
        for sub in list(self._stack.arrangedSubviews()):
            self._stack.removeArrangedSubview_(sub)
            sub.removeFromSuperview()
        lib = self._app.activeLibrary()
        if lib is None:
            self._stack.addArrangedSubview_(_label("Nu a fost detectată nicio bibliotecă Serato.", bold=True, size=17))
            self._stack.addArrangedSubview_(_label("Conectează un volum cu un folder _Serato_ sau alege manual unul.", secondary=True))
            self._stack.addArrangedSubview_(_button("Scanează din nou", self._app, b"rescanLibraries:"))
            return
        present = len(lib.present_tracks)
        missing = len(lib.missing_tracks)
        health = "✓ Biblioteca este în regulă" if missing == 0 else f"⚠ {missing} fișiere lipsă"
        self._stack.addArrangedSubview_(_label(lib.name, bold=True, size=22))
        self._stack.addArrangedSubview_(_label(str(lib.volume_root), secondary=True))
        self._stack.addArrangedSubview_(_label(health, bold=True, size=15))
        self._stack.addArrangedSubview_(_label(
            f"{theme.format_int(present)} track-uri     {theme.format_int(len(lib.crates))} crate-uri     {theme.format_int(missing)} lipsă"))
        self._stack.addArrangedSubview_(_button("Scanează din nou", self._app, b"rescanLibraries:"))


# ------------------------------------------------------------------- Libraries
class LibrariesScreen(BaseScreen):
    def build_(self, v):
        self._headerInto_title_subtitle_(v, "Biblioteci", "Biblioteci Serato detectate pe acest Mac")
        self._summary = _label("", secondary=True)
        self._summary.setFrame_(NSMakeRect(24, v.bounds().size.height - 100, 800, 18))
        self._summary.setAutoresizingMask_(1 << 3)
        v.addSubview_(self._summary)
        body = self._bodyContainerIn_(v, top=118)
        self._tv, self._ds, scroll = _table(
            ["name", "root", "tracks", "present", "missing", "crates"],
            ["Bibliotecă", "Locație", "Track-uri", "Disponibile", "Lipsă", "Crate-uri"],
            [160, 300, 90, 100, 80, 90])
        scroll.setFrame_(body.bounds())
        body.addSubview_(scroll)
        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

    def refresh(self):
        self._app.rescanLibraries_(None)

    def render(self):
        libs = self._app.libraries()
        rows = [(l.name, str(l.volume_root), theme.format_int(len(l.tracks)),
                 theme.format_int(len(l.present_tracks)),
                 theme.format_int(len(l.missing_tracks)),
                 theme.format_int(len(l.crates))) for l in libs]
        self._ds.setData_(rows)
        self._tv.reloadData()
        tot_tracks = sum(len(l.tracks) for l in libs)
        tot_missing = sum(len(l.missing_tracks) for l in libs)
        tot_crates = sum(len(l.crates) for l in libs)
        self._summary.setStringValue_(
            f"{len(libs)} Bibliotecă · {theme.format_int(tot_tracks)} Track-uri · {theme.format_int(tot_missing)} Lipsă · {theme.format_int(tot_crates)} Crate-uri")


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
        self.render()

    def didBecomeVisible(self):
        self.render()

    def librariesChanged(self):
        self.render()

    def render(self):
        lib = self._app.activeLibrary()
        self._crates = lib.crates if lib else []
        self._cratesDs.setData_([(c.display_name, str(len(c.raw_paths))) for c in self._crates])
        self._cratesTv.reloadData()
        self._tracksDs.setData_([])
        self._tracksTv.reloadData()

    def crateSelected_(self, note):
        row = self._cratesTv.selectedRow()
        lib = self._app.activeLibrary()
        if row < 0 or lib is None or row >= len(self._crates):
            return
        crate = self._crates[row]
        rows = []
        for rp in crate.raw_paths:
            ap = Path(lib.volume_root) / rp
            t = lib.tracks.get(rp)
            rows.append(("✓" if ap.exists() else "⚠",
                         (t.artist if t else "") or "", (t.title if t else "") or "", str(ap)))
        self._tracksDs.setData_(rows)
        self._tracksTv.reloadData()


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
