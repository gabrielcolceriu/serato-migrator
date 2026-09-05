"""AppKit application shell for Serato Migrator (UI-01).

Delivers the native window: a grouped source-list sidebar, a routed content
area, a contextual toolbar unified with the title bar, a real menu bar, the
standard About panel, a Settings window (Cmd+,) and window/UI-state
persistence. Screens are wired to the existing toolkit-free logic modules; the
per-screen visual redesign lands in UI-02..UI-23.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

import objc
from AppKit import (
    NSApp, NSApplication, NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered, NSBezelStyleRounded, NSButton, NSColor, NSFont,
    NSMenu, NSMenuItem, NSOutlineView, NSScrollView, NSSplitView,
    NSTableColumn, NSTextField, NSToolbar, NSToolbarItem, NSView,
    NSWindow, NSWindowController, NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled, NSWindowStyleMaskFullSizeContentView,
    NSWindowTitleHidden, NSAlert, NSAppearance,
)
from Foundation import (
    NSObject, NSMakeRect, NSNotificationCenter, NSDate, NSIndexSet,
    NSAutoreleasePool,
)
from PyObjCTools import AppHelper

import scanner
from . import state

APP_NAME = "Serato Migrator"
try:
    from gui import APP_VERSION  # single source of truth for the version string
except Exception:  # pragma: no cover
    APP_VERSION = "0.0.0"


# --------------------------------------------------------------------------- nav
# (id, label, sf-symbol-ish name, is_group_header)
NAV = [
    ("overview", "Prezentare", "square.grid.2x2", False),
    ("__lib", "BIBLIOTECĂ", None, True),
    ("libraries", "Biblioteci", "internaldrive", False),
    ("crates", "Crate-uri", "square.stack.3d.up", False),
    ("orphans", "Fișiere orfane", "questionmark.folder", False),
    ("__tools", "INSTRUMENTE", None, True),
    ("migrate", "Migrare", "shippingbox", False),
    ("metadata", "Metadata", "tag", False),
    ("__system", "SISTEM", None, True),
    ("journal", "Jurnal", "list.bullet.rectangle", False),
]
NAV_TITLES = {i: lbl for i, lbl, _s, grp in NAV if not grp}


def _label(text, *, bold=False, secondary=False, size=13):
    tf = NSTextField.labelWithString_(text or "")
    f = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    tf.setFont_(f)
    if secondary:
        tf.setTextColor_(NSColor.secondaryLabelColor())
    return tf


# ---------------------------------------------------------------- content router
class ContentRouter(NSObject):
    """Holds the container view and swaps a child NSViewController per destination."""

    def initWithContainer_appDelegate_(self, container, delegate):
        self = objc.super(ContentRouter, self).init()
        if self is None:
            return None
        self._container = container
        self._delegate = delegate
        self._vcs = {}
        self._current = None
        return self

    def show_(self, dest_id):
        if dest_id == self._current:
            return
        for v in list(self._container.subviews()):
            v.removeFromSuperview()
        vc = self._vcs.get(dest_id)
        if vc is None:
            vc = self._make(dest_id)
            self._vcs[dest_id] = vc
        view = vc.view()
        view.setFrame_(self._container.bounds())
        view.setAutoresizingMask_((1 << 1) | (1 << 4))  # width | height
        self._container.addSubview_(view)
        self._current = dest_id
        if hasattr(vc, "didBecomeVisible"):
            vc.didBecomeVisible()

    @objc.python_method
    def _make(self, dest_id):
        from .screens import make_screen
        return make_screen(dest_id, self._delegate)


# ----------------------------------------------------------------- sidebar (src)
class SidebarDataSource(NSObject):
    def initWithDelegate_(self, delegate):
        self = objc.super(SidebarDataSource, self).init()
        if self is None:
            return None
        self._delegate = delegate
        self._rows = NAV
        return self

    # flat outline (single level) — group headers are non-selectable rows
    def outlineView_numberOfChildrenOfItem_(self, ov, item):
        return 0 if item is not None else len(self._rows)

    def outlineView_child_ofItem_(self, ov, idx, item):
        return idx

    def outlineView_isItemExpandable_(self, ov, item):
        return False

    def outlineView_objectValueForTableColumn_byItem_(self, ov, col, item):
        return self._rows[item][1]

    def outlineView_isGroupItem_(self, ov, item):
        return self._rows[item][3]

    def outlineView_shouldSelectItem_(self, ov, item):
        return not self._rows[item][3]

    def outlineViewSelectionDidChange_(self, note):
        ov = note.object()
        row = ov.selectedRow()
        if row < 0:
            return
        dest = self._rows[row][0]
        if dest.startswith("__"):
            return
        self._delegate.selectDestination_(dest)


# --------------------------------------------------------------- window + toolbar
class MainWindowController(NSWindowController):
    def initWithAppDelegate_(self, delegate):
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
                 | NSWindowStyleMaskFullSizeContentView)
        frame_str = state.get(state.K_WINDOW_FRAME)
        rect = NSMakeRect(0, 0, 1180, 760)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        win.setTitle_(APP_NAME)
        win.setTitleVisibility_(NSWindowTitleHidden)
        win.setTitlebarAppearsTransparent_(False)
        win.setMinSize_((980, 620))
        win.setReleasedWhenClosed_(False)

        self = objc.super(MainWindowController, self).initWithWindow_(win)
        if self is None:
            return None
        self._delegate = delegate
        self._sidebar_collapsed = False
        self._sidebar_width = 224
        self._buildContent()
        self._buildToolbar()

        if frame_str:
            win.setFrameFromString_(frame_str)
        else:
            win.center()
        win.setDelegate_(self)
        if state.get_bool(state.K_SIDEBAR_COLLAPSED):
            self._setSidebarCollapsed_(True)
        return self

    # --- layout ---
    def _buildContent(self):
        win = self.window()
        split = NSSplitView.alloc().initWithFrame_(win.contentView().bounds())
        split.setVertical_(True)
        split.setDividerStyle_(2)  # thin
        split.setAutoresizingMask_((1 << 1) | (1 << 4))
        split.setTranslatesAutoresizingMaskIntoConstraints_(True)
        self._split = split

        # sidebar
        ov = NSOutlineView.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 600))
        col = NSTableColumn.alloc().initWithIdentifier_("main")
        col.setWidth_(200)
        ov.addTableColumn_(col)
        ov.setOutlineTableColumn_(col)
        ov.setHeaderView_(None)
        ov.setRowSizeStyle_(1)  # small/standard
        ov.setFloatsGroupRows_(False)
        ov.setSelectionHighlightStyle_(1)  # source list
        ov.setIndentationPerLevel_(0)
        self._sidebar_ds = SidebarDataSource.alloc().initWithDelegate_(self._delegate)
        ov.setDataSource_(self._sidebar_ds)
        ov.setDelegate_(self._sidebar_ds)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self._sidebar_ds, b"outlineViewSelectionDidChange:",
            "NSOutlineViewSelectionDidChangeNotification", ov)
        self._sidebar = ov
        sb_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 600))
        sb_scroll.setDocumentView_(ov)
        sb_scroll.setHasVerticalScroller_(True)
        sb_scroll.setDrawsBackground_(False)
        sb_scroll.setBorderType_(0)

        # content container
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 900, 600))
        self._content_container = container
        self._router = ContentRouter.alloc().initWithContainer_appDelegate_(
            container, self._delegate)
        self._delegate.setRouter_(self._router)

        split.setDelegate_(self)
        split.addSubview_(sb_scroll)
        split.addSubview_(container)
        split.setPosition_ofDividerAtIndex_(224, 0)
        win.setContentView_(split)

    # --- NSSplitViewDelegate: let the sidebar collapse fully & clamp its width
    def splitView_canCollapseSubview_(self, sv, subview):
        return subview is sv.subviews()[0]

    def splitView_constrainMinCoordinate_ofSubviewAt_(self, sv, proposed, idx):
        return 0.0

    def splitView_constrainMaxCoordinate_ofSubviewAt_(self, sv, proposed, idx):
        return 320.0

    def splitView_shouldAdjustSizeOfSubview_(self, sv, subview):
        # keep the sidebar fixed-width on window resize; only the content grows
        return subview is not sv.subviews()[0]

    def _buildToolbar(self):
        tb = NSToolbar.alloc().initWithIdentifier_("main.toolbar")
        tb.setDelegate_(self)
        tb.setDisplayMode_(2)  # icon only
        tb.setAllowsUserCustomization_(False)
        self.window().setToolbar_(tb)
        self._toolbar = tb

    # --- NSToolbarDelegate ---
    def toolbarAllowedItemIdentifiers_(self, tb):
        return ["toggleSidebar", "title", "NSToolbarFlexibleSpaceItem", "refresh"]

    def toolbarDefaultItemIdentifiers_(self, tb):
        return ["toggleSidebar", "title", "NSToolbarFlexibleSpaceItem", "refresh"]

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(self, tb, ident, flag):
        item = NSToolbarItem.alloc().initWithItemIdentifier_(ident)
        if ident == "toggleSidebar":
            item.setLabel_("Sidebar")
            b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 34, 26))
            b.setBezelStyle_(NSBezelStyleRounded)
            b.setTitle_("☰")
            b.setTarget_(self)
            b.setAction_(b"toggleSidebar:")
            item.setView_(b)
        elif ident == "title":
            self._title_label = _label(NAV_TITLES.get("overview", APP_NAME), bold=True, size=15)
            item.setView_(self._title_label)
        elif ident == "refresh":
            item.setLabel_("Reîmprospătează")
            b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 34, 26))
            b.setBezelStyle_(NSBezelStyleRounded)
            b.setTitle_("⟳")
            b.setTarget_(self._delegate)
            b.setAction_(b"refreshCurrent:")
            item.setView_(b)
        return item

    def setToolbarTitle_(self, text):
        if getattr(self, "_title_label", None) is not None:
            self._title_label.setStringValue_(text)

    def toggleSidebar_(self, sender):
        # NSSplitView (pre-VC) has no built-in collapse toggle; track our own
        # state and move the divider. isSubviewCollapsed_ does not update when
        # you only set the divider position, so we must not rely on it.
        self._setSidebarCollapsed_(not getattr(self, "_sidebar_collapsed", False))

    def _setSidebarCollapsed_(self, collapsed):
        collapsed = bool(collapsed)
        cur = self._split.subviews()[0].frame().size.width
        if not collapsed and cur > 1:
            return  # already open
        if collapsed:
            if cur > 1:
                self._sidebar_width = cur
            self._split.setPosition_ofDividerAtIndex_(0.0, 0)
        else:
            self._split.setPosition_ofDividerAtIndex_(
                float(getattr(self, "_sidebar_width", 224) or 224), 0)
        self._sidebar_collapsed = collapsed
        state.set(state.K_SIDEBAR_COLLAPSED, collapsed)

    def selectSidebarRowForDestination_(self, dest_id):
        for row, (i, *_rest) in enumerate(NAV):
            if i == dest_id:
                self._sidebar.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(row), False)
                break

    # --- NSWindowDelegate ---
    def windowDidResize_(self, note):
        state.set(state.K_WINDOW_FRAME, self.window().stringWithSavedFrame())

    def windowDidMove_(self, note):
        state.set(state.K_WINDOW_FRAME, self.window().stringWithSavedFrame())

    def windowShouldClose_(self, sender):
        return self._delegate.windowShouldClose()


# ------------------------------------------------------------------- app delegate
class AppDelegate(NSObject):
    def init(self):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self._router = None
        self._wc = None
        self._libraries = []
        self._journal = []          # list[(NSDate, level, op, msg)]
        self._busy = 0
        return self

    # --- lifecycle ---
    def applicationDidFinishLaunching_(self, note):
        state.register_defaults()
        self._applyAppearance()
        self._buildMenu()
        self._wc = MainWindowController.alloc().initWithAppDelegate_(self)
        self._wc.showWindow_(None)
        NSApp().activateIgnoringOtherApps_(True)
        last = state.get(state.K_SELECTED_DESTINATION) or "overview"
        self.selectDestination_(last)
        self._wc.selectSidebarRowForDestination_(last)
        self.rescanLibraries_(None)

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return True

    # --- router / nav ---
    def setRouter_(self, router):
        self._router = router

    def selectDestination_(self, dest_id):
        if self._router is None:
            return
        self._router.show_(dest_id)
        state.set(state.K_SELECTED_DESTINATION, dest_id)
        if self._wc is not None:
            self._wc.setToolbarTitle_(NAV_TITLES.get(dest_id, APP_NAME))

    def currentDestination(self):
        return state.get(state.K_SELECTED_DESTINATION) or "overview"

    # --- library scan (shared) ---
    def rescanLibraries_(self, sender):
        self.log_("Scanez bibliotecile Serato…", "info", "scan")
        self._beginBusy_("scanare biblioteci")

        def work():
            try:
                libs = scanner.find_serato_libraries()
            except Exception:
                libs = []
                self.log_("Eroare la scanare:\n" + traceback.format_exc(), "error", "scan")
            AppHelper.callAfter(self._librariesScanned_, libs)

        threading.Thread(target=work, daemon=True).start()

    def _librariesScanned_(self, libs):
        self._libraries = list(libs)
        ts = state.get_dict(state.K_SCAN_TIMESTAMPS)
        now = NSDate.date().description()
        for lib in self._libraries:
            ts[str(lib.volume_root)] = str(now)
        state.set_dict(state.K_SCAN_TIMESTAMPS, ts)
        if not state.get(state.K_ACTIVE_LIBRARY_ROOT) and self._libraries:
            state.set(state.K_ACTIVE_LIBRARY_ROOT, str(self._libraries[0].volume_root))
        n = len(self._libraries)
        missing = sum(len(l.missing_tracks) for l in self._libraries)
        self.log_(f"{n} biblioteci · {missing} track-uri lipsă", "info", "scan")
        self._endBusy_("scanare biblioteci")
        if self._router is not None:
            for vc in getattr(self._router, "_vcs", {}).values():
                if hasattr(vc, "librariesChanged"):
                    vc.librariesChanged()

    def libraries(self):
        return self._libraries

    def activeLibrary(self):
        root = state.get(state.K_ACTIVE_LIBRARY_ROOT)
        for lib in self._libraries:
            if str(lib.volume_root) == root:
                return lib
        return self._libraries[0] if self._libraries else None

    def setActiveLibraryRoot_(self, root):
        state.set(state.K_ACTIVE_LIBRARY_ROOT, str(root))
        if self._router is not None:
            for vc in getattr(self._router, "_vcs", {}).values():
                if hasattr(vc, "librariesChanged"):
                    vc.librariesChanged()

    # --- toolbar generic ---
    def refreshCurrent_(self, sender):
        dest = self.currentDestination()
        vc = getattr(self._router, "_vcs", {}).get(dest)
        if vc is not None and hasattr(vc, "refresh"):
            vc.refresh()
        else:
            self.rescanLibraries_(None)

    # --- journal ---
    @objc.python_method
    def log_(self, msg, level="info", op=None, detail=None):
        self._journal.append((NSDate.date(), level, op, str(msg), detail))
        vc = getattr(self._router, "_vcs", {}).get("journal")
        if vc is not None and hasattr(vc, "journalChanged"):
            AppHelper.callAfter(vc.journalChanged)

    def journal(self):
        return self._journal

    def clearJournal(self):
        self._journal = []

    # --- busy / close guard ---
    def _beginBusy_(self, label):
        self._busy += 1

    def _endBusy_(self, label):
        self._busy = max(0, self._busy - 1)

    def isBusy(self):
        return self._busy > 0

    def windowShouldClose(self):
        if self._busy > 0:
            from AppKit import NSAlert
            a = NSAlert.alloc().init()
            a.setMessageText_("O operațiune este în curs.")
            a.setInformativeText_("Așteaptă să se termine înainte să închizi aplicația.")
            a.addButtonWithTitle_("OK")
            a.beginSheetModalForWindow_completionHandler_(self._wc.window(), None)
            return False
        return True

    # --- menu ---
    def _buildMenu(self):
        mainmenu = NSMenu.alloc().init()

        app_item = NSMenuItem.alloc().init()
        mainmenu.addItem_(app_item)
        app_menu = NSMenu.alloc().init()
        app_item.setSubmenu_(app_menu)
        app_menu.addItemWithTitle_action_keyEquivalent_(
            f"Despre {APP_NAME}", b"showAbout:", "")
        app_menu.addItem_(NSMenuItem.separatorItem())
        settings_item = app_menu.addItemWithTitle_action_keyEquivalent_(
            "Setări…", b"showSettings:", ",")
        settings_item.setTarget_(self)
        app_menu.addItem_(NSMenuItem.separatorItem())
        app_menu.addItemWithTitle_action_keyEquivalent_(
            f"Ascunde {APP_NAME}", b"hide:", "h")
        app_menu.addItemWithTitle_action_keyEquivalent_(
            f"Închide {APP_NAME}", b"terminate:", "q")

        # Bibliotecă menu
        lib_item = NSMenuItem.alloc().init()
        mainmenu.addItem_(lib_item)
        lib_menu = NSMenu.alloc().initWithTitle_("Bibliotecă")
        lib_item.setSubmenu_(lib_menu)
        m = lib_menu.addItemWithTitle_action_keyEquivalent_("Rescanează", b"rescanLibraries:", "r")
        m.setTarget_(self)

        # Editare (standard)
        edit_item = NSMenuItem.alloc().init()
        mainmenu.addItem_(edit_item)
        edit_menu = NSMenu.alloc().initWithTitle_("Editare")
        edit_item.setSubmenu_(edit_menu)
        for title, sel, key in (("Anulează", b"undo:", "z"), ("Refă", b"redo:", "Z")):
            edit_menu.addItemWithTitle_action_keyEquivalent_(title, sel, key)
        edit_menu.addItem_(NSMenuItem.separatorItem())
        for title, sel, key in (("Decupează", b"cut:", "x"), ("Copiază", b"copy:", "c"),
                                 ("Lipește", b"paste:", "v"), ("Selectează tot", b"selectAll:", "a")):
            edit_menu.addItemWithTitle_action_keyEquivalent_(title, sel, key)

        # Fereastră
        win_item = NSMenuItem.alloc().init()
        mainmenu.addItem_(win_item)
        win_menu = NSMenu.alloc().initWithTitle_("Fereastră")
        win_item.setSubmenu_(win_menu)
        win_menu.addItemWithTitle_action_keyEquivalent_("Minimizează", b"performMiniaturize:", "m")
        win_menu.addItemWithTitle_action_keyEquivalent_("Zoom", b"performZoom:", "")
        NSApp().setWindowsMenu_(win_menu)

        NSApp().setMainMenu_(mainmenu)

    def showAbout_(self, sender):
        opts = {
            "ApplicationName": APP_NAME,
            "ApplicationVersion": APP_VERSION,
            "Version": "",
            "Copyright": "Gabriel Colceriu · cu Claude Code",
        }
        NSApp().orderFrontStandardAboutPanelWithOptions_(opts)

    def showSettings_(self, sender):
        from .settings_window import SettingsWindowController
        if getattr(self, "_settings_wc", None) is None:
            self._settings_wc = SettingsWindowController.alloc().initDefault()
        self._settings_wc.showWindow_(None)
        self._settings_wc.window().makeKeyAndOrderFront_(None)

    def _applyAppearance(self):
        mode = state.get(state.K_APPEARANCE) or "system"
        from AppKit import NSAppearance
        if mode == "light":
            NSApp().setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))
        elif mode == "dark":
            NSApp().setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        else:
            NSApp().setAppearance_(None)


def main():
    pool = NSAutoreleasePool.alloc().init()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()
    del pool


if __name__ == "__main__":
    main()
