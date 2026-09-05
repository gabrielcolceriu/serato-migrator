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


# nav model + the grouped source-list sidebar live in ui.sidebar (UI-02)
from .sidebar import SidebarController, NAV, NAV_TITLES, NAV_IDS  # noqa: E402,F401


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
        self._inspector_container = None
        self._wc = None
        return self

    def setInspectorContainer_windowController_(self, inspector, wc):
        self._inspector_container = inspector
        self._wc = wc

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
        self._updateInspectorFor_(vc)
        if hasattr(vc, "didBecomeVisible"):
            vc.didBecomeVisible()

    @objc.python_method
    def _updateInspectorFor_(self, vc):
        if self._inspector_container is None:
            return
        for v in list(self._inspector_container.subviews()):
            v.removeFromSuperview()
        insp = vc.inspectorView() if hasattr(vc, "inspectorView") else None
        if insp is not None:
            insp.setFrame_(self._inspector_container.bounds())
            insp.setAutoresizingMask_((1 << 1) | (1 << 4))
            self._inspector_container.addSubview_(insp)
        if self._wc is not None:
            self._wc.setInspectorAvailable_(insp is not None)

    def refreshInspector(self):
        vc = self._vcs.get(self._current)
        if vc is not None:
            self._updateInspectorFor_(vc)

    @objc.python_method
    def _make(self, dest_id):
        from .screens import make_screen
        return make_screen(dest_id, self._delegate)


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

        # sidebar (grouped source list + active-library footer)
        self._sidebar_ctl = SidebarController.alloc().initWithAppDelegate_(self._delegate)
        sb_scroll = self._sidebar_ctl.view()

        # content container
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 700, 600))
        self._content_container = container

        # inspector container (3rd pane; shown only when a screen provides content)
        inspector = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 600))
        self._inspector_container = inspector
        self._inspector_width = 280
        self._inspector_collapsed = True

        self._router = ContentRouter.alloc().initWithContainer_appDelegate_(
            container, self._delegate)
        self._router.setInspectorContainer_windowController_(inspector, self)
        self._delegate.setRouter_(self._router)

        split.setDelegate_(self)
        split.addSubview_(sb_scroll)
        split.addSubview_(container)
        split.addSubview_(inspector)
        split.setPosition_ofDividerAtIndex_(224, 0)
        split.setPosition_ofDividerAtIndex_(split.bounds().size.width, 1)  # inspector collapsed
        win.setContentView_(split)

    # --- inspector show/hide (driven by the router per screen) ---
    def setInspectorVisible_(self, visible):
        visible = bool(visible)
        w = self._split.bounds().size.width
        if visible:
            self._split.setPosition_ofDividerAtIndex_(
                w - float(getattr(self, "_inspector_width", 280) or 280), 1)
        else:
            cur = self._inspector_container.frame().size.width
            if cur > 1:
                self._inspector_width = cur
            self._split.setPosition_ofDividerAtIndex_(w, 1)
        self._inspector_collapsed = not visible
        state.set(state.K_INSPECTOR_COLLAPSED, not visible)

    def toggleInspector_(self, sender):
        # only meaningful when the current screen has an inspector
        if getattr(self, "_inspector_available", False):
            self.setInspectorVisible_(self._inspector_collapsed)

    def setInspectorAvailable_(self, available):
        self._inspector_available = bool(available)
        if not available:
            self.setInspectorVisible_(False)
        elif not state.get_bool(state.K_INSPECTOR_COLLAPSED):
            self.setInspectorVisible_(True)

    # --- NSSplitViewDelegate: sidebar + inspector collapse & fixed widths
    def splitView_canCollapseSubview_(self, sv, subview):
        subs = sv.subviews()
        return subview is subs[0] or (len(subs) > 2 and subview is subs[2])

    def splitView_constrainMinCoordinate_ofSubviewAt_(self, sv, proposed, idx):
        if idx == 0:
            return 0.0
        return max(proposed, sv.bounds().size.width * 0.35)  # content keeps room

    def splitView_constrainMaxCoordinate_ofSubviewAt_(self, sv, proposed, idx):
        if idx == 0:
            return 320.0
        return sv.bounds().size.width  # inspector divider can go fully right

    def splitView_shouldAdjustSizeOfSubview_(self, sv, subview):
        subs = sv.subviews()
        # only the content pane grows on window resize
        if subview is subs[0]:
            return False
        if len(subs) > 2 and subview is subs[2]:
            return False
        return True

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
        self._sidebar_ctl.selectDestination(dest_id)

    def refreshSidebarFooter(self):
        self._sidebar_ctl.refreshFooter()

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
        try:
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
        except Exception:
            import traceback
            Path("/tmp/seratomigrator_startup_error.txt").write_text(traceback.format_exc())
            raise

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
        from . import health as _health
        for lib in self._libraries:
            _health.mark_scanned(str(lib.volume_root))
        if not state.get(state.K_ACTIVE_LIBRARY_ROOT) and self._libraries:
            state.set(state.K_ACTIVE_LIBRARY_ROOT, str(self._libraries[0].volume_root))
        n = len(self._libraries)
        missing = sum(len(l.missing_tracks) for l in self._libraries)
        self.log_(f"{n} biblioteci · {missing} track-uri lipsă", "info", "scan")
        self._endBusy_("scanare biblioteci")
        if self._wc is not None:
            self._wc.refreshSidebarFooter()
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
        if self._wc is not None:
            self._wc.refreshSidebarFooter()
        if self._router is not None:
            for vc in getattr(self._router, "_vcs", {}).values():
                if hasattr(vc, "librariesChanged"):
                    vc.librariesChanged()

    def toggleSidebar_(self, sender):
        if self._wc is not None:
            self._wc.toggleSidebar_(sender)

    def toggleInspector_(self, sender):
        if self._wc is not None:
            self._wc.toggleInspector_(sender)

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

        # Vizualizare
        view_item = NSMenuItem.alloc().init()
        mainmenu.addItem_(view_item)
        view_menu = NSMenu.alloc().initWithTitle_("Vizualizare")
        view_item.setSubmenu_(view_menu)
        mi = view_menu.addItemWithTitle_action_keyEquivalent_(
            "Ascunde/Arată bara laterală", b"toggleSidebar:", "s")
        mi.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))  # cmd | alt
        mi.setTarget_(self)
        mi2 = view_menu.addItemWithTitle_action_keyEquivalent_(
            "Ascunde/Arată inspectorul", b"toggleInspector:", "i")
        mi2.setKeyEquivalentModifierMask_((1 << 20) | (1 << 19))
        mi2.setTarget_(self)

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
