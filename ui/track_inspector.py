"""UI-15 — Track Inspector, one reusable right-hand component.

Used from Crate-uri, Metadata (single edit) and the missing / orphan views.
Contextual and collapsible: a screen returns ``inspector.view()`` from its
``inspectorView()`` while a single track is selected and ``None`` otherwise,
then calls ``app._router.refreshInspector()`` on every selection change.

No new parsing and no duplicated business logic: the fields come straight off
the existing ``serato_db.Track`` and *Salvează* routes through
``metadata_editor.apply_edits`` exactly like the Metadata single-edit.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

import objc
from AppKit import (
    NSView, NSStackView, NSTextField, NSButton, NSBox, NSColor, NSFont,
    NSUserInterfaceLayoutOrientationVertical, NSUserInterfaceLayoutOrientationHorizontal,
    NSLayoutConstraint, NSWorkspace, NSPasteboard, NSPasteboardTypeString,
    NSBezelStyleRounded, NSSwitchButton, NSLineBreakByTruncatingMiddle,
)
from Foundation import NSObject, NSMakeRect, NSURL
from PyObjCTools import AppHelper

import metadata_editor
from . import theme

# serato tag <- field key, mirrors metadata_editor.EDITABLE_FIELDS
_FIELDS = [
    ("artist", "tart", "Artist"),
    ("title", "tsng", "Titlu"),
    ("album", "talb", "Album"),
    ("genre", "tgen", "Gen"),
]


def _strut(h):
    v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, h))
    v.setTranslatesAutoresizingMaskIntoConstraints_(False)
    v.addConstraint_(
        NSLayoutConstraint.constraintWithItem_attribute_relatedBy_toItem_attribute_multiplier_constant_(
            v, 8, 0, None, 0, 1.0, float(h)))
    return v


def _section(title):
    return theme.make_label(title, style="caption",
                            color=NSColor.tertiaryLabelColor())


class TrackInspector(NSObject):
    def initWithApp_(self, app):
        self = objc.super(TrackInspector, self).init()
        if self is None:
            return None
        self._app = app
        self._lib = None
        self._track = None
        self._on_saved = None
        self._build()
        self.set_track(None, None)
        return self

    # ---- public ---------------------------------------------------------
    def view(self):
        return self._container

    @objc.python_method
    def set_track(self, lib, track, on_saved=None):
        """Point the inspector at one track (or clear it with ``track=None``)."""
        self._lib = lib
        self._track = track
        self._on_saved = on_saved
        if track is None:
            self._detail.setHidden_(True)
            self._empty.setHidden_(False)
            return
        self._empty.setHidden_(True)
        self._detail.setHidden_(False)
        self._title.setStringValue_((track.title or "—"))
        self._artistLine.setStringValue_((track.artist or "—"))
        self._album.setStringValue_(track.album or "—")
        self._genre.setStringValue_(track.genre or "—")
        self._loc.setStringValue_(track.abs_path or "—")
        self._loc.setToolTip_(track.abs_path or "")
        present = bool(track.abs_path) and Path(track.abs_path).exists()
        self._status.setStringValue_(
            "✓ Fișier disponibil" if present else "⚠ Fișier lipsă")
        self._status.setTextColor_(
            theme.ok_color() if present else theme.warn_color())
        for key, _tag, _lbl in _FIELDS:
            self._edits[key].setStringValue_(getattr(track, key) or "")
        self._saveBtn.setEnabled_(True)

    # ---- build --------------------------------------------------------
    @objc.python_method
    def _build(self):
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 600))
        container.setAutoresizingMask_((1 << 1) | (1 << 4))
        self._container = container

        # empty state
        empty = theme.make_label("Niciun track selectat", style="secondary",
                                 color=NSColor.tertiaryLabelColor())
        empty.setFrame_(NSMakeRect(16, 300, 248, 20))
        empty.setAutoresizingMask_((1 << 0) | (1 << 3) | (1 << 5) | (1 << 1))
        empty.setAlignment_(2)  # center
        container.addSubview_(empty)
        self._empty = empty

        stack = NSStackView.alloc().initWithFrame_(NSMakeRect(0, 0, 280, 600))
        stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        stack.setAlignment_(1)  # leading
        stack.setSpacing_(6)
        stack.setEdgeInsets_((16, 16, 16, 16))
        stack.setAutoresizingMask_((1 << 1) | (1 << 4))
        container.addSubview_(stack)
        self._detail = stack
        add = stack.addArrangedSubview_

        # -- INFORMAȚII TRACK
        add(_section("INFORMAȚII TRACK"))
        self._title = theme.make_label("", style="headline")
        self._title.setLineBreakMode_(0)  # wrap
        self._title.setUsesSingleLineMode_(False)
        add(self._title)
        self._artistLine = theme.make_label("", style="body",
                                            color=theme.secondary_label())
        add(self._artistLine)
        add(_strut(4))
        self._album = self._infoRow_(stack, "Album")
        self._genre = self._infoRow_(stack, "Gen")
        self._loc = self._infoRow_(stack, "Locație", middle_truncate=True)
        self._status = self._infoRow_(stack, "Status")
        add(_strut(10))

        # -- METADATA
        add(_section("METADATA"))
        self._edits = {}
        for key, _tag, label in _FIELDS:
            self._edits[key] = self._editRow_(stack, label)
        id3 = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 200, 18))
        id3.setButtonType_(NSSwitchButton)
        id3.setTitle_("Scrie și în ID3")
        id3.setState_(1)
        add(id3)
        self._id3 = id3
        add(_strut(2))
        save = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 120, 28))
        save.setBezelStyle_(NSBezelStyleRounded)
        save.setTitle_("Salvează")
        save.setKeyEquivalent_("\r")
        save.setTarget_(self)
        save.setAction_(b"save:")
        add(save)
        self._saveBtn = save
        add(_strut(10))

        # -- ACȚIUNI
        add(_section("ACȚIUNI"))
        add(self._linkButton_("Editează metadata", b"editMeta:"))
        add(self._linkButton_("Deschide în Finder", b"revealInFinder:"))
        add(self._linkButton_("Copiază calea", b"copyPath:"))

    @objc.python_method
    def _infoRow_(self, stack, label, middle_truncate=False):
        row = NSStackView.alloc().init()
        row.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        row.setSpacing_(6)
        row.setAlignment_(12)  # firstBaseline
        cap = theme.make_label(label, style="caption", color=theme.secondary_label())
        cap.setFrame_(NSMakeRect(0, 0, 58, 14))
        cap.setContentHuggingPriority_forOrientation_(252, 0)
        cap.setContentCompressionResistancePriority_forOrientation_(750, 0)
        val = theme.make_label("", style="callout")
        if middle_truncate:
            val.setLineBreakMode_(NSLineBreakByTruncatingMiddle)
        row.addArrangedSubview_(cap)
        row.addArrangedSubview_(val)
        stack.addArrangedSubview_(row)
        return val

    @objc.python_method
    def _editRow_(self, stack, label):
        row = NSStackView.alloc().init()
        row.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        row.setSpacing_(6)
        row.setAlignment_(10)  # centerY
        cap = theme.make_label(label, style="caption", color=theme.secondary_label())
        cap.setContentHuggingPriority_forOrientation_(252, 0)
        cap.setContentCompressionResistancePriority_forOrientation_(750, 0)
        cap.addConstraint_(
            NSLayoutConstraint.constraintWithItem_attribute_relatedBy_toItem_attribute_multiplier_constant_(
                cap, 7, 0, None, 0, 1.0, 46.0))  # width == 46
        tf = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 190, 22))
        tf.setFont_(theme.font("body"))
        tf.setContentHuggingPriority_forOrientation_(250, 0)
        row.addArrangedSubview_(cap)
        row.addArrangedSubview_(tf)
        stack.addArrangedSubview_(row)
        row.setContentHuggingPriority_forOrientation_(250, 0)
        return tf

    @objc.python_method
    def _linkButton_(self, title, action):
        b = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 18))
        b.setBordered_(False)
        b.setButtonType_(7)
        from AppKit import (NSAttributedString, NSForegroundColorAttributeName,
                            NSFontAttributeName)
        b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
            title, {NSForegroundColorAttributeName: NSColor.linkColor(),
                    NSFontAttributeName: NSFont.systemFontOfSize_(12)}))
        b.setTarget_(self)
        b.setAction_(action)
        return b

    # ---- actions ----------------------------------------------------
    def save_(self, sender):
        if self._track is None or self._lib is None:
            return
        edits = {}
        prev = {}
        for key, tag, _lbl in _FIELDS:
            new = self._edits[key].stringValue().strip()
            old = (getattr(self._track, key) or "")
            if new != old:
                edits[tag] = new
                prev[tag] = old
        if not edits:
            self._app.log_("Metadata: nicio schimbare de salvat", "info", "metadata")
            return
        raw = self._track.raw_path
        write_id3 = self._id3.state() == 1
        lib = self._lib
        self._pending_undo = (str(lib.volume_root), {raw: prev}, write_id3,
                              f"editare {Path(self._track.abs_path).name}")
        self._saveBtn.setEnabled_(False)
        self._app.log_(
            f"Salvez metadata pentru {Path(self._track.abs_path).name}…",
            "info", "metadata")

        def work():
            err = None
            try:
                metadata_editor.apply_edits(lib, {raw: edits}, write_id3=write_id3)
            except Exception:
                err = traceback.format_exc()
            AppHelper.callAfter(self._saved_, err)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _saved_(self, err):
        self._saveBtn.setEnabled_(True)
        if err:
            self._app.log_("Eroare la salvarea metadata:\n" + err, "error", "metadata")
            return
        # reflect the new values on the in-memory Track so the row + inspector agree
        for key, _tag, _lbl in _FIELDS:
            setattr(self._track, key, self._edits[key].stringValue().strip() or None)
        pu = getattr(self, "_pending_undo", None)
        if pu is not None and hasattr(self._app, "pushMetaUndo"):
            self._app.pushMetaUndo(*pu)
            self._pending_undo = None
        self._app.log_("Metadata salvată", "info", "metadata")
        if callable(self._on_saved):
            try:
                self._on_saved()
            except Exception:
                pass

    def editMeta_(self, sender):
        self._container.window().makeFirstResponder_(self._edits["artist"])

    def revealInFinder_(self, sender):
        if not self._track:
            return
        p = self._track.abs_path
        if p and Path(p).exists():
            NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(
                [NSURL.fileURLWithPath_(p)])
        else:
            self._app.log_("Fișierul nu există pe disc", "warn", "metadata")

    def copyPath_(self, sender):
        if not self._track:
            return
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(self._track.abs_path or "", NSPasteboardTypeString)
        self._app.log_("Cale copiată în clipboard", "info", "metadata")
