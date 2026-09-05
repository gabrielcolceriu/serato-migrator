# Serato Migrator — UI/UX Redesign 2026

Status: **proposal — awaiting approval before any UI code changes**
Author: Claude Code, for Gabriel Colceriu
Target: a utility a Mac user would believe Apple shipped with macOS (Tahoe-era HIG).

---

## 0. TL;DR — the framework decision you have to make first

The app is **Tkinter/ttk**. Tkinter on macOS renders through Tk's `aqua`/`clam`
themes, which are a ~2010-era approximation. It has **no** access to:

- `NSToolbar` (unified/inline toolbar, the thing every modern Mac app has)
- `NSSplitViewController` source-list sidebar with vibrancy
- SF Symbols
- Liquid Glass / `NSVisualEffectView` materials
- the system accent color
- semantic `NSColor` (label, secondaryLabel, separator, controlBackground…)
- view-based `NSTableView` / `NSOutlineView`
- `NSAppearance` dark-mode switching at runtime
- standard app menu / services / About panel

No amount of ttk styling closes that gap. The current hand-drawn PNG icons,
custom modal `Toplevel`s (needed because Tk's `messagebox` ignores the parent
window on macOS) and the fixed 1300×800 window are all symptoms of fighting the
toolkit.

**Two honest paths:**

| | Path A — native UI-layer rewrite | Path B — maximal Tkinter refresh |
|---|---|---|
| What changes | `gui.py` → PyObjC/AppKit (or a thin SwiftUI shell). `main.py`, `setup.py`, `build_icon.py` adjusted. | `gui.py` restructured; ttk restyle; dark-mode via appearance polling; spacing/color tokens. |
| What is **untouched** | `serato_db.py`, `scanner.py`, `copier.py`, `metadata_editor.py` (verified: zero UI imports). | same. |
| Result | Real NSToolbar, real source-list sidebar, SF Symbols, materials, system accent, semantic colors, native tables, native About/menu. **Meets the bar.** | Cleaner, denser, dark-mode-aware Tk utility. **Does not meet the bar** — a Mac user will still read it as "a Python/Tk app". |
| Cost | High. ~13 issues, multi-session. New dependency: `pyobjc` (already a common py2app companion). | Medium. Same 13 issues, less each. |
| Risk to logic | None — logic modules are imported and called exactly as today. | None. |

**Recommendation: Path A.** The brief's own final test — *"If I removed the app
name, would a Mac user immediately believe this was designed for macOS?"* —
cannot be passed in Tkinter. Path B is a legitimate fallback if you want to keep
the stack pure-Tk, but it should be chosen with eyes open.

Everything below is written so the **information architecture, screen designs,
component behaviour and preservation checklist apply to either path.** The
per-screen "native mapping" notes assume Path A; the "Tk fallback" notes cover
Path B.

The logic layer is a clean seam either way:

```
serato_db.py    binary Serato database V2 / .crate parser + builders   (UI-free)
scanner.py      library auto-detect, orphan finder, "missing elsewhere" (UI-free)
copier.py       copy planner, execute_plan, rebuild_database_from_disk,
                write_fresh_serato, export_database, add_orphans_to_crate (UI-free)
metadata_editor.py  artist/title suggestions, apply_edits (DB + ID3)     (UI-free)
gui.py          ← the only file the redesign replaces
main.py         entry point (calls gui.main)
```

---

## 1. Current UI architecture (as-is)

### 1.1 Shell
- One `Tk` root, `SeratoMigratorApp` class, window fixed at `1300x800`, `minsize 1000x650`.
- 3.2 s custom splash (`_show_splash`) drawing the logo on a `Toplevel`.
- Top: a hand-rolled **tab bar** — plain `ttk.Label`s in a row, click-bound, with a
  pill-image "selected" background (`_build_pill_image`, cached per-tab). Not `ttk.Notebook`.
- 1 px divider frame under the tab bar.
- Content area: 7 `ttk.Frame`s stacked with `grid` in the same cell; `_select_tab`
  raises one and repaints the label pills.
- Bottom: single-line status bar (`status_var`, `Status.TLabel`).
- No menu bar. No accelerators. `WM_DELETE_WINDOW` → `_on_close`.

### 1.2 Destinations (tabs), in bar order
| key | title | build method |
|---|---|---|
| `libs` | Biblioteci | `_build_tab_libraries` |
| `crates` | Crate-uri | `_build_tab_crates` |
| `orphans` | Fisiere orfane | `_build_tab_orphans` |
| `migrate` | Migrare / Reorganizare | `_build_tab_migrate` |
| `metadata` | Metadata | `_build_tab_metadata` |
| `log` | Jurnal | `_build_tab_log` |
| `about` | Despre | `_build_tab_about` |

### 1.3 Visual system
- ttk theme `clam`. Custom styles: `TabItem.TLabel`, `Divider.TFrame`,
  `Status.TLabel`, `Icon.TButton`, `Warn.TLabel`, `Ok.TLabel`,
  `Treeview`/`Treeview.Heading`, dot-indicator element for tree expanders.
- **Hardcoded colors** (module constants): `ACCENT #3B8FDA`, `ACCENT_DARK`,
  `ACCENT_2 #00CEC9`, `APP_BG #E7E7ED`, `SURFACE #FFFFFF`, `BORDER #E3E3EA`,
  `TEXT_MAIN #1C1C1E`, `TEXT_MUTED #6E6E76`, `DISABLED_BG`, splash colors, logo
  gradient stops. **No dark mode. No system accent.**
- Fonts: `TkDefaultFont` family forced to size 14 (`BASE_FONT_SIZE`), a Menlo
  mono font at 13 for the log. Manual `(None, N, "bold")` in a few places.
- Icons: procedurally drawn `PhotoImage`s — `_build_refresh_icon`,
  `_build_locate_icon`, `_build_database_icon`, `_build_export_icon`,
  `_build_dot_icon`, `_build_app_icon` (also the `.icns` source via `build_icon.py`).

### 1.4 Background operations (all: `threading.Thread(daemon=True)` + `queue.Queue` + `root.after` polling)
| op | trigger | poll method | busy label |
|---|---|---|---|
| library scan | `refresh_libraries` (also on launch) | `_on_libraries_scanned` | `scanare biblioteci` |
| "missing elsewhere" scan | `_check_missing_elsewhere` | `_poll_missing_progress` → `_show_missing_results` | `cautare track-uri lipsa` |
| orphan scan | `_scan_orphans` | `_poll_orphan_progress` → `_on_orphans_found` | `scanare fisiere orfane` |
| rebuild database | `_rebuild_database` | `_poll_rebuild` | `reconstruire baza de date` |
| add orphans to crate | `_add_orphans_to_crate` | inline `poll()` | `adaugare orfane in crate` |
| migration copy | `_run_migration` | `_poll_progress` | `migrare` |
| per-crate size calc | `_start_mig_size_computation` | `_poll_mig_sizes` | (not busy-gated) |

`_begin_busy` / `_end_busy` maintain `_busy_count` + `_busy_labels`; while > 0,
`_on_close` refuses to close and names the running op. This is the only
"is work happening" signal — there is **no global progress UI**, only the
status-bar string and, for migration, a single `ttk.Progressbar`.

### 1.5 Dialogs
- `_show_dialog` (custom `Toplevel`, centered over parent) → `show_info`,
  `show_warning`, `ask_yesno`. Buttons now centered.
- Native pickers: `filedialog.askdirectory` (choose library root / scan root /
  migration destination), `filedialog.asksaveasfilename` (export .zip).
- Result windows (`Toplevel`, 1000×600): `_show_missing_results` (2-tab notebook:
  found-elsewhere / still-missing), `_show_artist_title_review` (checklist tree +
  "write ID3" toggle + apply).
- Tooltips: custom `_Tooltip` on `<Enter>`/`<Leave>` with 400 ms delay.

### 1.6 Keyboard / menu / persistence
- **Shortcuts:** none global. Widget-level only: `<Return>` in the two search
  entries; `<<TreeviewSelect>>`; `<Button-1>` on tab labels and the migrate crate tree.
- **Menu:** none (Tk default only).
- **State persistence:** none. Window size, sidebar/inspector state, last
  library, last destination, column widths, sort order — nothing is saved.
- **Dark mode:** none.

### 1.7 Per-screen inventory

**Biblioteci** — toolbar row: refresh (icon), "verifică lipsă" (icon),
rebuild-db (icon), export-db (icon). A 6-column `Treeview` (`nume, radacina,
tracks, prezente, lipsa, crate_uri`), `height=10`, full border, no summary, no
selection detail, no context menu. Populated by `_on_libraries_scanned`.
`_check_missing_elsewhere` needs a selected row.

**Crate-uri** — horizontal `PanedWindow`. Left: `crates_tree` (`show="tree"`,
hierarchical via `%%`-split names, dot expanders). Right: filter radios
(Toate / Doar OK / Doar lipsă) + `tracks_tree` (Status icon + Artist/Titlu/Cale,
click-sortable via `_sort_tracks`, sort persists through the filter). Selecting a
crate node fills the track list (`_on_crate_selected` → `_render_tracks_tree`).

**Fisiere orfane** — toolbar: root combobox (library volume roots) + "Alege
folder…" + "Scanează după orfane" + "Adaugă în crate «Orfane»" (enabled only
after a scan finds orphans under a known library). Info line (count + total
size). `orphans_list` (Cale / Mărime, sortable, Mărime numeric). No search, no
per-row actions, no reveal-in-Finder, no empty state.

**Migrare / Reorganizare** — most complex screen. Left column: "Biblioteci de
inclus" checkboxes + "Crate-uri de migrat" (`mig_crates_tree` with ☑/☐/▣
click-toggle glyphs, background size calc, "Toate/Niciunul", "include
ne-încadrate", live "K/N crate • ~X GB" summary). Right column: destination
entry + "Alege…", checkboxes (copy `_Serato_`, rewrite paths, **generate fresh
DB**, normalize CAPS names), "Previzualizare" / "Copiază acum". Below: plan
summary label, space-fit label (green "Încape" / red "NU ÎNCAPE"),
`ttk.Progressbar`, "details in Jurnal" hint. `_run_migration` shows a
space-doesn't-fit confirm, then a final confirm listing counts + what happens,
then runs; `_poll_progress` streams `[done/total] (copiat|hardlink) path` to the
log and drives the progress bar; emits `fresh_start/done`, `serato_start/done`,
`rewrite_start/done`, `error`.

**Metadata** — top: library combobox + "Deschide folder…" + search entry +
"Caută" + "Analizează Artist/Titlu lipsă". `PanedWindow`: left `metadata_tree`
(Artist/Titlu/Album/Gen/Fișier, sortable, multi-select `extended`); right an
"Editare" `LabelFrame` with 4 entries + "Salvează" (single-track applies all 4
fields; multi-track applies only filled fields) + "scrie și ID3" toggle.
`_analyze_artist_title` → `_show_artist_title_review` checklist window.

**Jurnal** — a read-only `Text` widget (Menlo 13) + "Curăță jurnalul" button +
scrollbar. `self.log(msg)` timestamps `[HH:MM:SS] …` and appends. No levels, no
filter, no search, no export. It is the *de facto* progress/detail view for
migration and rebuild.

**Despre** — centered logo + name + version + a paragraph + a bulleted
feature list. Not a real destination; belongs in the app menu.

---

## 2. Problems found

1. **Reads as a Python/Tk app**, not a Mac app — flat pills instead of a
   sidebar, loose icon buttons, rectangular accent button, hard borders around
   every table, fixed non-persisted window.
2. **No dark mode.** Hardcoded light palette; unusable at night, ignores the OS.
3. **No system accent color.** Blue is baked in.
4. **Wasted horizontal space** in the top tab bar; 7 flat tabs with no grouping.
5. **"Despre" is a primary destination.** Should be the app menu's About item.
6. **Weak hierarchy on Biblioteci** — a big empty bordered table, no title,
   no summary, no selection detail, no context menu.
7. **The Journal is load-bearing.** Migration/rebuild progress detail only
   exists as log text; there is no proper progress surface.
8. **No global "work in progress" affordance** beyond a status string.
9. **Migration is a dense form**, not a task flow; destructive confirmation is a
   plain yes/no dialog visually identical to navigation.
10. **Orphans screen is a bare list** — no search/filter/reveal/empty state,
    though it is fundamentally a diagnostics screen.
11. **Crates hierarchy** is real but rendered with a generic tree + dot glyphs;
    no counts, no context actions.
12. **Metadata editor** is a form beside a list; multi-select exists but the
    "these fields will change" intent is not shown before applying.
13. **No keyboard model** — no ⌘-shortcuts, no menu, no focus ring discipline.
14. **No state persistence** — every launch resets everything.
15. **Numbers not localized** (`23100`, not `23.100` / `23,100`).
16. **Custom modal Toplevels** instead of sheets attached to the window.
17. **Typography is one size** (14) with occasional bold; no text-style hierarchy.
18. **Two long-lived result windows** (missing / artist-title) float free
    instead of being sheets or an inspector.

---

## 3. Proposed information architecture

### 3.1 Window shell
`Sidebar | Content | Inspector` (three-column, HIG). Inspector is optional and
per-screen; it appears only where it adds value (Biblioteci, Metadata) and is
collapsible. Toolbar is unified with the title bar.

### 3.2 Sidebar (replaces the tab bar)

```
SERATO MIGRATOR                     (app name, small, top — not a nav item)

BIBLIOTECĂ
  ●  Biblioteci            internaldrive / rack
  ●  Crate-uri             square.stack / rectangle.stack
  ●  Fișiere orfane        questionmark.folder / exclamationmark.triangle

INSTRUMENTE
  ●  Migrare               arrow.right.doc.on.clipboard / shippingbox
  ●  Metadata              tag / text.badge.checkmark

SISTEM
  ●  Jurnal                list.bullet.rectangle / text.alignleft
```

- Native source list, vibrant material, system accent for the selection.
- Collapsible (toolbar sidebar-toggle + ⌘⌥S). Selected destination persisted.
- SF Symbol per row (names above are candidates; final pick during UI-02).
- **"Despre" is removed as a destination** → `Serato Migrator ▸ About Serato Migrator`
  in the app menu, standard About panel (icon, name, version, one-line credit).
- A tiny footer row in the sidebar may show global busy state
  (`↻ Se scanează…` / spinner) so activity is visible from anywhere.

Narrow-window behaviour: sidebar auto-collapses to icons, then overlays.

### 3.3 Toolbar (per screen, contextual)
- **Leading:** sidebar toggle · screen title.
- **Center:** the primary verbs for the visible screen (icon + tooltip).
- **Trailing:** search field where it helps · a genuine primary action only when
  one exists (e.g. **Migrează** on the migration review step) · `•••` overflow
  for secondary actions.
- No large colored rectangles except a true primary action.

Screen → toolbar map:

| Screen | Center | Trailing |
|---|---|---|
| Biblioteci | Reîmprospătează · Rescanează · Verifică lipsă | Export… · ••• (Rebuild DB, Reveal in Finder) · inspector toggle |
| Crate-uri | Expand all · Collapse all | search · filter (Toate/OK/Lipsă) |
| Fișiere orfane | Alege folder · Scanează | search · Adaugă în «Orfane» · ••• (Reveal, Copy paths) |
| Migrare | (wizard-step nav) | **Migrează** (only on Review) |
| Metadata | Analizează Artist/Titlu | search · inspector toggle |
| Jurnal | scope segmented (Toate/Info/Avertismente/Erori) | search · Copiază · Golește · Export… |

### 3.4 Status & health vocabulary (icon + label, never color-only)
`✓ Sănătoasă` · `⚠ Fișiere lipsă` · `⚠ Problemă bază de date` · `↻ Se scanează` ·
`✓ Migrare finalizată` · `✕ Migrare eșuată` · `● Nesalvat`.
SF Symbols: `checkmark.circle`, `exclamationmark.triangle`,
`exclamationmark.octagon`, `arrow.triangle.2.circlepath`, `xmark.octagon`.

---

## 4. Screen-by-screen redesign

### 4.1 Biblioteci
- **Header:** title `Biblioteci` + subtitle `Biblioteci Serato detectate pe acest Mac`.
- **Summary strip** (subtle, single row of label/value pairs — not cards):
  `1 Bibliotecă · 23.100 Track-uri · 23.100 Disponibile · 0 Lipsă · 145 Crate-uri`.
  Localized numbers.
- **Table:** columns `Bibliotecă · Locație · Track-uri · Disponibile · Lipsă · Crate-uri`.
  Numeric columns right-aligned, monospaced digits. Hover + selection states,
  sortable headers, subtle row separators, no outer border, automatic column
  sizing, alternating rows only if it reads well.
- **Context menu (right-click):** Reveal in Finder · Rescan Library ·
  Verifică fișiere lipsă · Rebuild Database · Export Database.
- **Double-click:** reveal the volume root in Finder.
- **Inspector (when a row is selected, collapsible):**
  `Locație`, `Track-uri`, `Disponibile`, `Lipsă`, `Crate-uri`, `Status ✓ Bibliotecă OK`,
  then actions: `Deschide în Finder`, `Rescanează`, `Verifică lipsă`,
  `Rebuild Database`, `Export Database`.
- **Empty state:** `Nu a fost detectată nicio bibliotecă Serato.` +
  `Conectează un volum cu un folder _Serato_ sau alege manual unul.` +
  button `Alege bibliotecă…` (→ existing `filedialog.askdirectory` + `load_library_at`).
- Native mapping: view-based `NSTableView`, `NSMenu` for context, right pane is a
  form in the split view.
- Tk fallback: `Treeview` with `tag_configure` hover/stripes, a real
  right-click `Menu`, a right frame that shows/hides.

### 4.2 Crate-uri
- Source-list / outline for the crate hierarchy (parents, subcrates), each row:
  crate name + track count badge + a small `⚠` when it has missing tracks.
  Expand/collapse, expand-all / collapse-all, search filters the outline.
- Right: the track list keeps Status · Artist · Titlu · Cale, sortable, with the
  Toate/OK/Lipsă filter as a segmented control in the toolbar.
- Context menu on a crate: Reveal folder in Finder · Copy track paths ·
  (future) Export crate.
- Empty state: `Biblioteca nu conține crate-uri.`
- Native mapping: `NSOutlineView` left, `NSTableView` right.
- Tk fallback: keep the `Treeview` but add count text per node + a real context menu.

### 4.3 Fișiere orfane
- Diagnostics layout: header + count + **search** + **sort** + list
  (`Fișier · Locație · Mărime`, size numeric-sorted, localized).
- Row / bulk actions: select (⌘-click, shift-click, ⌘A), **Reveal in Finder**,
  **Copy paths**, **Adaugă în crate «Orfane»** (existing `add_orphans_to_crate`),
  and — only if `scanner.find_missing_elsewhere`-style relink is wired — a
  "Reconectează…" that maps an orphan onto a DB "missing" entry.
- **Empty state:** `✓ Nu există fișiere orfane` /
  `Toate fișierele din bibliotecă sunt disponibile.`
- Warning indicators used sparingly (one summary `⚠`, not per row).

### 4.4 Migrare — task workflow
Replace the dense form with a stepped flow (segmented pager in the toolbar or a
left rail):

```
1 Sursă  →  2 Destinație  →  3 Opțiuni  →  4 Verificare  →  (Migrează)
```

- **1 Sursă:** pick library/libraries; then the crate picker (the existing
  ☑/☐/▣ tree, size calc, Toate/Niciunul, include-unsorted) lives here.
  Live footer: `K/N crate • ~X GB`.
- **2 Destinație:** folder well + "Alege…" (native picker). Show target volume,
  free space, and the fit verdict inline (`Încape — rămâne ~Y` / `NU ÎNCAPE —
  lipsesc ~Z`, red, with the icon).
- **3 Opțiuni:** the four existing switches, grouped and labelled by consequence:
  - *Structură bază de date* (radio-ish): **Copiază `_Serato_` + rescrie căile**
    vs **Generează bază de date nouă (doar ce migrez)**.
  - *Fișiere:* Normalizează numele SCRISE CU MAJUSCULE.
  - Each with a one-line "ce face" caption.
- **4 Verificare:** the summary the brief asks for —
  ```
  Sursă        Music — /Volumes/Music · 23.100 track-uri · 145 crate-uri · 0 lipsă
  Destinație   /Volumes/NewSSD · liber 812 GB
  Ce se copiază 76.994 fișiere (1.04 TB) + 5.273 hardlink-uri
  Bază de date  Generează una nouă, doar cu crate-urile alese
  Nume         Normalizate
  ```
  Explicitly: **fișierele originale NU sunt șterse / mutate / redenumite.**
- **Migrează** is the only primary button, on step 4, and still triggers the
  existing final `ask_yesno` (as a **sheet**), plus the "doesn't fit" sheet when
  relevant.
- **During migration:** a dedicated progress surface (not the log): determinate
  bar, `Se copiază 12.340 / 76.994`, current file, elapsed, and ETA when the
  rate is stable. Phase labels for `_Serato_` copy / path rewrite / fresh-DB.
  Cancel button **only** wired if a safe cancel exists (today `execute_plan` has
  no cancel hook — so: no Cancel, or add a cooperative flag in `copier` in a
  separate issue; do **not** fake it).
- **After:** `✓ Migrare finalizată` result panel (counts, destination,
  "Deschide în Finder") or `✕ Migrare eșuată` with the error and the log link.

### 4.5 Metadata — inspector editor
- `track list | inspector`. List = current `metadata_tree` (sortable,
  multi-select). Inspector = the four fields + "scrie și ID3" + Salvează.
- **Multi-select intent:** show, per field, `— (neschimbat)` placeholder;
  a field only applies if the user typed into it; the Save button says
  `Aplică pe 37 track-uri` and the confirm sheet lists exactly which fields
  change. (Matches current logic: single applies all four, multi applies filled.)
- `Analizează Artist/Titlu lipsă` stays; its review list becomes a **sheet**
  (or an inline panel), not a free window.
- Empty state: `Nicio bibliotecă selectată.` / after search with no hits:
  `Niciun rezultat.`

### 4.6 Jurnal — activity log
- Toolbar: segmented `Toate · Info · Avertismente · Erori` + search + `Copiază` +
  `Golește` + `Export…`.
- Content: a table — `Oră · Nivel · Operațiune · Mesaj` — monospaced **only** in
  the Message column. Selectable rows, ⌘A, ⌘C.
- This means `self.log(...)` gains a level + optional operation tag (small,
  backward-compatible signature change: `log(msg, level="info", op=None)`).
- Empty state: `Nu există evenimente în jurnal.`

### 4.7 About
- Removed from navigation. `App menu ▸ Despre Serato Migrator` → standard About
  panel: icon, `Serato Migrator`, `Versiunea X.Y.Z`, one line
  `Gabriel Colceriu · cu Claude Code`. The long feature paragraph moves to the
  repo README (already modernised) — not the app.

---

## 5. Component strategy

| Concern | Path A (native) | Path B (Tk) |
|---|---|---|
| Shell | `NSWindow` + `NSSplitViewController` (sidebar / content / inspector) + unified `NSToolbar` | `PanedWindow`/frames; custom toolbar frame; keep single `Tk` |
| Sidebar | `NSOutlineView` source list, `.sidebar` material, SF Symbols | vertical frame, grouped labels, dot/symbol PNGs, accent from `NSColor` read once |
| Tables | view-based `NSTableView`, `NSMenu` context | `ttk.Treeview` + `tag_configure` + `Menu`; the `_attach_column_sort` helper stays |
| Outline (crates) | `NSOutlineView` | `Treeview` `show=tree` (as today) + counts |
| Dialogs | window-attached **sheets** (`beginSheet`) | keep `_show_dialog` `Toplevel` but restyle; still centered on parent |
| Pickers | `NSOpenPanel` / `NSSavePanel` | `filedialog` (already native) |
| Progress | `NSProgressIndicator` + a progress panel/sheet | `ttk.Progressbar` in a dedicated panel, not the log |
| Colors | semantic `NSColor.*` + `controlAccentColor` | a token module resolved at runtime from `NSColor` via PyObjC-lite or `tk::unsupported` appearance; **no** hardcoded hex in widgets |
| Type | `NSFont.preferredFont(forTextStyle:)` | map to Tk named fonts: `largeTitle→22`, `headline→15 semibold`, `body→13`, `secondary→12 muted`, `caption→11` — via *style names*, not literals |
| Icons | SF Symbols | keep procedural PNGs, restyle to accent + secondaryLabel; regenerate `.icns` (already inset to 80 %) |
| Dark mode | automatic via `NSAppearance` | subscribe to `AppleInterfaceThemeChangedNotification` (or poll `defaults read -g AppleInterfaceStyle`); swap the token set + repaint |
| State | `NSUserDefaults` (`~/Library/Preferences`) | a small `~/Library/Application Support/Serato Migrator/state.json` |

Spacing tokens (both paths): **4 / 8 / 12 / 16 / 24 / 32**. Corner radii: 6 for
controls, 10 for panels, nothing larger. Control heights: native where possible;
Tk fallback ≈ 22–24 px rows, 28 px toolbar buttons.

State to persist: window frame, sidebar collapsed, inspector collapsed, selected
destination, per-table sort column/direction, last migration destination, last
orphan scan root, Jurnal scope filter.

---

## 6. Implementation plan (Phase 4)

Incremental, one screen at a time, `build → run → verify checklist → commit → PR`.

| Issue | Scope | Depends on |
|---|---|---|
| **UI-01** | Window shell + unified toolbar + app menu + About panel + state persistence scaffolding | — |
| **UI-02** | Sidebar navigation (grouped, SF Symbols, accent, collapse, persisted selection) + retire "Despre" tab | UI-01 |
| **UI-09** | Inspector architecture (three-column split, per-screen inspector, collapse + persist) | UI-01 |
| **UI-10** | Dark Mode + system accent + semantic color tokens + Reduce Transparency / Increase Contrast + font-style hierarchy | UI-01 |
| **UI-03** | Biblioteci: header, summary strip, table upgrade, context menu, inspector content, empty state | UI-02, UI-09, UI-10 |
| **UI-04** | Crate-uri: outline + counts + context actions + toolbar filter/search + empty state | UI-02, UI-10 |
| **UI-05** | Fișiere orfane: diagnostics layout, search/sort, bulk + reveal actions, empty state | UI-02, UI-10 |
| **UI-06** | Migrare: Sursă→Destinație→Opțiuni→Verificare→Migrează flow, destructive-action treatment, dedicated progress surface | UI-02, UI-10; (optional) a `copier` cancel hook as its own sub-issue |
| **UI-07** | Metadata: list + inspector editor, multi-select "what will change", review as sheet | UI-02, UI-09, UI-10 |
| **UI-08** | Jurnal: level+op-tagged `log()`, filterable/searchable table, copy/clear/export, empty state | UI-01, UI-10 |
| **UI-11** | Empty / error / loading / progress states pass across every screen | UI-03…UI-08 |
| **UI-12** | Final visual consistency pass (spacing, type, radii, icon weight, alignment) vs Finder/Music/Disk Utility | UI-03…UI-11 |
| **UI-13** | Functional regression testing against the Section 7 checklist; fix regressions | all |

No placeholder UI, no TODO handlers land on `main`. Each PR closes its issue and
keeps the app runnable.

---

## 7. Functionality-preservation checklist

Every item below must still work after the redesign. `handler` = current method.

### Navigation & shell
- [ ] Reach all 6 real destinations (Biblioteci, Crate-uri, Fișiere orfane, Migrare, Metadata, Jurnal) — was `_select_tab`
- [ ] About reachable (now app menu) — was `_build_tab_about`
- [ ] Launch runs an initial library scan — `refresh_libraries` in `__init__`
- [ ] Window cannot be closed while a background op runs; the running op is named — `_on_close` + `_busy_labels`
- [ ] "Serato DJ Pro is running" guard before DB writes — `_guard_serato_not_running` (used by rebuild, add-orphans, save-metadata, apply artist/title, migration when copying `_Serato_`)
- [ ] Status line reflects current activity — `set_status`

### Biblioteci
- [ ] Auto-detected libraries listed with name / root / tracks / present / missing / crates — `_on_libraries_scanned`
- [ ] Manual "choose a library folder" (validates a `_Serato_` exists) — via `_open_metadata_folder`'s `askdirectory` pattern + `scanner.load_library_at`
- [ ] Refresh / rescan — `refresh_libraries`
- [ ] Verifică fișiere lipsă (needs selection) → results window with "found elsewhere" + "still missing" — `_check_missing_elsewhere` → `_show_missing_results`
- [ ] Rebuild Database (needs selection) → confirm → lightweight `_Serato_ (backup …)` → new `database V2` keeping only on-disk tracks; drop empty crates; result counts + backup path — `_rebuild_database` → `copier.rebuild_database_from_disk` → `_poll_rebuild`
- [ ] Export Database (needs selection) → `asksaveasfilename` → ~2 MB `.zip` (database V2 + prefs + Subcrates/SmartCrates) — `_export_database` → `copier.export_database`

### Crate-uri
- [ ] Hierarchical crate tree (parents/subcrates via `%%`) — `_refresh_crates_tree`
- [ ] Selecting a crate shows its tracks with present/missing status — `_on_crate_selected` → `_render_tracks_tree`
- [ ] Filter Toate / Doar OK / Doar lipsă — `track_filter_var`
- [ ] Click-sort Artist / Titlu / Cale, sort survives filter change — `_sort_tracks` + `_tracks_sort`

### Fișiere orfane
- [ ] Scan root = a library volume root (combobox) or a chosen folder — `orphan_combo` + `_browse_orphan_root`
- [ ] Scan for audio files unknown to Serato, with live progress — `_scan_orphans` → `_poll_orphan_progress` → `_on_orphans_found`
- [ ] Result list: path + size, size sorts numerically — `orphans_list` + `_attach_column_sort(numeric_cols=("marime",))`
- [ ] "Adaugă în crate «Orfane»" — enabled only after a scan finds orphans under a known library; confirm; backs up `database V2`; idempotent; refreshes libraries — `_add_orphans_to_crate` → `copier.add_orphans_to_crate`

### Migrare / Reorganizare
- [ ] Choose one or more source libraries (checkboxes) — `lib_vars` / `_selected_libraries`
- [ ] Crate picker: per-crate + per-group ☑/☐/▣ toggle, Toate/Niciunul, background per-crate size, live "K/N • ~X GB" — `_build_migrate_crate_tree` … `_poll_mig_sizes`
- [ ] "Include și track-urile care nu-s în niciun crate" — `migrate_unsorted_var`
- [ ] `_selected_crate_keys()` returns `None` (full) or a set (subset)
- [ ] Destination picker — `_browse_dest`
- [ ] Options: copy `_Serato_`, rewrite paths, **generate fresh DB**, normalize CAPS — `copy_serato_var`, `rewrite_paths_var`, `fresh_db_var`, `normalize_names_var`
- [ ] Previzualizare builds a `CopyPlan` off-thread — `_preview_migration` → `copier.plan_copy(selected_crate_keys=…, include_unsorted=…)`
- [ ] Plan summary (copies / hardlinks / total size / skipped-missing) — `_on_plan_ready`
- [ ] Space-fit verdict incl. cross-volume hardlink cost + `_Serato_` dir size — `_space_report` → `copier.estimate_required_bytes`; green/red label — `_refresh_space_label`
- [ ] "Doesn't fit" confirm before running — `_run_migration`
- [ ] Guard: copy `_Serato_` requires exactly one library — `_run_migration`
- [ ] Final confirm lists file/hardlink counts, size, DB action, "originals not deleted" — `_run_migration`
- [ ] Runs `copier.execute_plan` + then `write_fresh_serato` **or** `copy_serato_folder` (+`rewrite_serato_database` if enabled)
- [ ] Progress: determinate bar + per-file detail + phase labels (`fresh_start/done`, `serato_start/done`, `rewrite_start/done`) — `_poll_progress`
- [ ] Error path surfaces the exception and re-enables the button — `_poll_progress` `("error", …)`
- [ ] Success confirmation — `_poll_progress` `None`

### Metadata
- [ ] Library selector (auto libs + "Deschide folder…") — `_refresh_metadata_lib_choices` / `_open_metadata_folder`
- [ ] Text search across artist/title/album/genre/filename — `_search_metadata_tracks`
- [ ] Multi-select list, sortable columns — `metadata_tree` (`selectmode="extended"`) + `_attach_column_sort`
- [ ] Single-track edit applies all 4 fields (incl. deliberate blanks) — `_save_metadata_edit`
- [ ] Multi-track edit applies only filled fields — `_save_metadata_edit`
- [ ] "Scrie și în ID3" toggle — `metadata_write_id3_var`
- [ ] Writes reach `database V2` **and** file tags — `metadata_editor.apply_edits`
- [ ] Post-write reload of affected tracks — `_save_metadata_edit` tail
- [ ] Analizează Artist/Titlu lipsă → review checklist → apply selected (+ID3 toggle) → reload — `_analyze_artist_title` → `_show_artist_title_review`

### Jurnal
- [ ] Every op appends a timestamped line — `self.log`
- [ ] Migration/rebuild detail visible somewhere (log or new progress surface)
- [ ] Clear the journal — `_clear_log`
- [ ] (new) filter by level, search, copy, export — must not regress existing append behaviour

### Cross-cutting
- [ ] Native folder/file pickers everywhere they exist today
- [ ] Confirmations for: close-during-op, rebuild DB, add-orphans, doesn't-fit, final migration, "nothing to save", "nothing selected"
- [ ] Tooltips on every icon-only control
- [ ] Splash on launch (may become a shorter fade or drop entirely if the shell loads fast — decide in UI-01)
- [ ] `.icns` still generated by `build_icon.py`; py2app bundle still builds (`setup.py`)
- [ ] No change to `serato_db.py`, `scanner.py`, `copier.py`, `metadata_editor.py` public functions/signatures (except the additive `log()` level/op params and, if approved, a cooperative-cancel flag in `copier.execute_plan`)

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Path A adds `pyobjc` and a much larger `gui.py` surface | Keep it one file or a small `ui/` package; logic modules frozen; each screen shipped behind its own PR that keeps the app runnable |
| py2app + PyObjC packaging quirks | UI-01 includes a `setup.py` build + launch check before any screen work |
| Regressions in the 6 background flows | UI-13 runs the Section 7 checklist end-to-end on the real Music library; every prior PR also spot-checks its screen |
| "Cancel migration" expectation vs. no safe cancel today | Do not fake it. Either omit Cancel or land a cooperative flag in `copier.execute_plan` as an explicit sub-issue with its own review |
| Scope creep into logic ("relink orphan to missing entry") | Out of scope for the redesign; note as a future feature, keep the checklist to existing behaviour |
| Localised number formatting changing test expectations | Central `format_int(n)` helper (locale-aware, `%d` fallback); apply only in display code |
| Dark-mode contrast on the hand-drawn icons / gradient logo | UI-10 verifies each icon in both appearances; recolor to semantic tokens |
| If you pick Path B, the final quality bar (Section 21 of the brief) will not be met | Documented here; your call at approval |

---

## 9. What happens next

1. **You approve a path (A or B)** and the IA in Section 3.
2. I open issues **UI-01 … UI-13** (Section 6) on `gabrielcolceriu/serato-migrator`.
3. Phase 4: implement issue by issue, PR by PR, each keeping the app runnable and
   the Section 7 checklist green.

No UI code changes until step 1.
