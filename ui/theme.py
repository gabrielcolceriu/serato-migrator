"""UI-00 — design-system foundation.

A single place for spacing, corner radii, the type-style hierarchy, semantic
colors and locale-aware number formatting. Screens reference styles by name, not
literals, so light/dark and accent changes are automatic and the whole app reads
as one product.
"""
from __future__ import annotations

from AppKit import NSFont, NSColor, NSTextField, NSFontWeightSemibold
from Foundation import NSNumberFormatter, NSNumberFormatterDecimalStyle

# --- spacing / geometry ----------------------------------------------------
SPACE = (0, 4, 8, 12, 16, 24, 32)


def space(step: int) -> int:
    """step 1..6 -> 4/8/12/16/24/32 (0 -> 0)."""
    return SPACE[max(0, min(step, len(SPACE) - 1))]


RADIUS_CONTROL = 6.0
RADIUS_PANEL = 10.0
ROW_HEIGHT = 24.0
TOOLBAR_CONTROL = 28.0

# --- type styles ---------------------------------------------------------
# name -> (point size, semibold?)
_TYPE = {
    "largeTitle": (26, True),
    "title": (20, True),
    "title2": (17, True),
    "headline": (15, True),
    "body": (13, False),
    "callout": (12, False),
    "secondary": (12, False),
    "caption": (11, False),
}


def font(style: str = "body") -> NSFont:
    size, semibold = _TYPE.get(style, _TYPE["body"])
    if semibold:
        return NSFont.systemFontOfSize_weight_(size, NSFontWeightSemibold)
    return NSFont.systemFontOfSize_(size)


# --- semantic colors ---------------------------------------------------
def label_color():
    return NSColor.labelColor()


def secondary_label():
    return NSColor.secondaryLabelColor()


def tertiary_label():
    return NSColor.tertiaryLabelColor()


def separator():
    return NSColor.separatorColor()


def accent():
    return NSColor.controlAccentColor()


def control_bg():
    return NSColor.controlBackgroundColor()


def window_bg():
    return NSColor.windowBackgroundColor()


# status hues (used with an icon + label, never color alone)
def ok_color():
    return NSColor.systemGreenColor()


def warn_color():
    return NSColor.systemOrangeColor()


def error_color():
    return NSColor.systemRedColor()


# --- widgets ---------------------------------------------------------
def make_label(text: str = "", *, style: str = "body", color=None) -> NSTextField:
    tf = NSTextField.labelWithString_(text or "")
    tf.setFont_(font(style))
    if color is not None:
        tf.setTextColor_(color)
    elif style in ("secondary", "caption"):
        tf.setTextColor_(NSColor.secondaryLabelColor())
    tf.setLineBreakMode_(5)  # truncate tail
    return tf


# --- numbers -------------------------------------------------------
_nf = NSNumberFormatter.alloc().init()
_nf.setNumberStyle_(NSNumberFormatterDecimalStyle)
_nf.setMaximumFractionDigits_(0)


def format_int(n) -> str:
    """Locale-aware grouped integer, e.g. 23.100 / 23,100 per the user's Mac."""
    try:
        s = _nf.stringFromNumber_(int(n))
        return str(s) if s is not None else str(int(n))
    except Exception:
        return str(n)


def human_size(n: int) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return (f"{size:.0f} {unit}" if unit == "B"
                    else f"{size:.1f} {unit}")
        size /= 1024
    return f"{size:.1f} PB"
