"""UI-02 — grouped source-list sidebar with SF Symbols + active-library footer.

Builds a container view: a view-based NSOutlineView (grouped rows, SF Symbol per
destination, system-accent selection) above a compact active-library status
block that shows name / track count / library health and returns to Prezentare
when clicked.
"""
from __future__ import annotations

import objc
from AppKit import (
    NSView, NSOutlineView, NSScrollView, NSTableColumn, NSTableCellView,
    NSTextField, NSImageView, NSImage, NSFont, NSColor, NSStackView,
    NSUserInterfaceLayoutOrientationVertical, NSLayoutConstraint,
    NSImageSymbolConfiguration, NSClickGestureRecognizer,
    NSVisualEffectView, NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialSidebar, NSVisualEffectStateActive,
    NSBox,
)
from Foundation import NSObject, NSMakeRect, NSNotificationCenter, NSIndexSet

from . import theme

# (id, label, sf-symbol, is_group_header)
NAV = [
    ("overview", "Prezentare", "square.grid.2x2", False),
    ("__lib", "BIBLIOTECĂ", None, True),
    ("libraries", "Biblioteci", "internaldrive", False),
    ("crates", "Crate-uri", "square.stack.3d.up.fill", False),
    ("orphans", "Fișiere orfane", "questionmark.folder", False),
    ("__tools", "INSTRUMENTE", None, True),
    ("migrate", "Migrare", "shippingbox", False),
    ("metadata", "Metadata", "tag", False),
    ("__system", "SISTEM", None, True),
    ("journal", "Jurnal", "list.bullet.rectangle", False),
]
NAV_TITLES = {i: lbl for i, lbl, _s, grp in NAV if not grp}
NAV_IDS = [i for i, *_ in NAV]


def _symbol(name, point=15):
    if not name:
        return None
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        return None
    img.setTemplate_(True)
    return img


class SidebarController(NSObject):
    def initWithAppDelegate_(self, delegate):
        self = objc.super(SidebarController, self).init()
        if self is None:
            return None
        self._app = delegate
        self._rows = NAV
        self._buildView()
        return self

    # ---- public ----
    def view(self):
        return self._container

    @objc.python_method
    def selectDestination(self, dest_id):
        try:
            row = NAV_IDS.index(dest_id)
        except ValueError:
            return
        self._outline.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(row), False)

    def refreshFooter(self):
        from . import health as _health
        lib = self._app.activeLibrary()
        if lib is None:
            self._f_name.setStringValue_("Nicio bibliotecă")
            self._f_count.setStringValue_("")
            self._f_health.setStringValue_("")
            self._health_target = None
            return
        h = _health.library_health(lib, scanning=self._app.isBusy())
        self._health_target = h.target
        self._f_name.setStringValue_(lib.name)
        self._f_count.setStringValue_(f"{theme.format_int(len(lib.present_tracks))} track-uri")
        mark = {"ok": "✓", "scanning": "↻"}.get(h.key, "⚠")
        self._f_health.setStringValue_(f"{mark} {h.label}")
        self._f_health.setTextColor_(
            NSColor.secondaryLabelColor() if h.key in ("ok", "scanning")
            else NSColor.systemOrangeColor())

    # ---- build ----
    @objc.python_method
    def _buildView(self):
        from AppKit import NSWorkspace
        container = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, 224, 600))
        container.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        container.setMaterial_(NSVisualEffectMaterialSidebar)
        container.setState_(NSVisualEffectStateActive)
        container.setAutoresizingMask_((1 << 1) | (1 << 4))
        self._container = container
        self._applyTransparencyPreference_()
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"accessibilityChanged:",
            "NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification",
            NSWorkspace.sharedWorkspace())

        # outline
        ov = NSOutlineView.alloc().initWithFrame_(NSMakeRect(0, 0, 224, 500))
        col = NSTableColumn.alloc().initWithIdentifier_("main")
        col.setWidth_(206)
        ov.addTableColumn_(col)
        ov.setOutlineTableColumn_(col)
        ov.setHeaderView_(None)
        ov.setRowSizeStyle_(1)
        ov.setFloatsGroupRows_(False)
        ov.setSelectionHighlightStyle_(1)  # source list -> system accent
        ov.setIndentationPerLevel_(0)
        ov.setBackgroundColor_(NSColor.clearColor())
        ov.setDataSource_(self)
        ov.setDelegate_(self)
        self._outline = ov
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"outlineViewSelectionDidChange:",
            "NSOutlineViewSelectionDidChangeNotification", ov)

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 92, 224, 508))
        scroll.setDocumentView_(ov)
        scroll.setHasVerticalScroller_(True)
        scroll.setDrawsBackground_(False)
        scroll.setBorderType_(0)
        scroll.setAutoresizingMask_((1 << 1) | (1 << 4))
        container.addSubview_(scroll)

        # divider above footer
        sep = NSBox.alloc().initWithFrame_(NSMakeRect(0, 88, 224, 1))
        sep.setBoxType_(2)  # separator
        sep.setAutoresizingMask_((1 << 1) | (1 << 3))
        container.addSubview_(sep)

        # footer (active library)
        footer = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 224, 88))
        footer.setAutoresizingMask_((1 << 1) | (1 << 3))
        self._f_name = _lbl("", size=12, bold=True)
        self._f_count = _lbl("", size=11, secondary=True)
        self._f_health = _lbl("", size=11, secondary=True)
        stack = NSStackView.alloc().initWithFrame_(NSMakeRect(14, 12, 196, 64))
        stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        stack.setAlignment_(1)
        stack.setSpacing_(2)
        stack.setAutoresizingMask_((1 << 1))
        for x in (self._f_name, self._f_count, self._f_health):
            stack.addArrangedSubview_(x)
        footer.addSubview_(stack)
        g = NSClickGestureRecognizer.alloc().initWithTarget_action_(self, b"footerClicked:")
        footer.addGestureRecognizer_(g)
        container.addSubview_(footer)
        self._footer = footer
        self.refreshFooter()

    # ---- NSOutlineView data source ----
    def outlineView_numberOfChildrenOfItem_(self, ov, item):
        return 0 if item is not None else len(self._rows)

    def outlineView_child_ofItem_(self, ov, idx, item):
        return idx

    def outlineView_isItemExpandable_(self, ov, item):
        return False

    # (no objectValueForTableColumn: — this is a fully view-based outline)

    # ---- NSOutlineView delegate ----
    def outlineView_isGroupItem_(self, ov, item):
        return self._rows[item][3]

    def outlineView_shouldSelectItem_(self, ov, item):
        return not self._rows[item][3]

    def outlineView_heightOfRowByItem_(self, ov, item):
        return 22.0 if self._rows[item][3] else 28.0

    def outlineView_viewForTableColumn_item_(self, ov, col, item):
        rid, label, symbol, is_group = self._rows[item]
        if is_group:
            cell = ov.makeViewWithIdentifier_owner_("group", self)
            if cell is None:
                cell = NSTableCellView.alloc().initWithFrame_(NSMakeRect(0, 0, 206, 22))
                cell.setIdentifier_("group")
                tf = _lbl("", size=11, bold=True, secondary=True)
                tf.setFrame_(NSMakeRect(6, 3, 194, 15))
                cell.addSubview_(tf)
                cell.setTextField_(tf)
            cell.textField().setStringValue_(label.upper())
            return cell
        cell = ov.makeViewWithIdentifier_owner_("item", self)
        if cell is None:
            cell = NSTableCellView.alloc().initWithFrame_(NSMakeRect(0, 0, 206, 28))
            cell.setIdentifier_("item")
            iv = NSImageView.alloc().initWithFrame_(NSMakeRect(8, 4, 20, 20))
            iv.setImageScaling_(2)
            iv.setImageFrameStyle_(0)
            cell.addSubview_(iv)
            cell.setImageView_(iv)
            tf = _lbl("", size=13)
            tf.setFrame_(NSMakeRect(36, 5, 166, 18))
            cell.addSubview_(tf)
            cell.setTextField_(tf)
        cell.textField().setStringValue_(label)
        cell.imageView().setImage_(_symbol(symbol))
        return cell

    def outlineViewSelectionDidChange_(self, note):
        ov = note.object()
        row = ov.selectedRow()
        if row < 0:
            return
        rid = self._rows[row][0]
        if rid.startswith("__"):
            return
        self._app.selectDestination_(rid)

    def footerClicked_(self, gr):
        target = getattr(self, "_health_target", None) or "overview"
        self.selectDestination(target)
        self._app.selectDestination_(target)

    def accessibilityChanged_(self, note):
        self._applyTransparencyPreference_()

    @objc.python_method
    def _applyTransparencyPreference_(self):
        from AppKit import NSWorkspace
        reduce = NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency()
        # NSVisualEffectView auto-falls-back to a solid fill under Reduce
        # Transparency, but make the intent explicit and give it a matching bg.
        self._container.setState_(1 if reduce else 2)  # inactive vs active
        if reduce:
            self._container.setMaterial_(3)  # NSVisualEffectMaterialWindowBackground
        else:
            self._container.setMaterial_(NSVisualEffectMaterialSidebar)


def _lbl(text, *, size=13, bold=False, secondary=False):
    tf = NSTextField.labelWithString_(text or "")
    tf.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if secondary:
        tf.setTextColor_(NSColor.secondaryLabelColor())
    tf.setLineBreakMode_(5)  # truncate tail
    return tf
