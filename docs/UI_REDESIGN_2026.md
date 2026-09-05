# Serato Migrator — UI/UX Redesign 2026

Status: **proposal — awaiting approval before any UI code changes**
Author: Claude Code, for Gabriel Colceriu
Target: a utility a Mac user would believe Apple shipped with macOS (Tahoe-era HIG).

This document was written in two passes and merged:
1. inspection + shell/navigation/screen redesign + preservation checklist;
2. product-level UX requirements (Overview, Library/Crate Health, Track Inspector,
   hero migration flow with backup + verification, Activity vs Raw log, context
   menus, drag & drop, keyboard-first, empty-state discipline, design system).

---

## 0. TL;DR — the framework decision you have to make first

The app is **Tkinter/ttk**. Tkinter on macOS renders through Tk's `aqua`/`clam`
themes, a ~2010-era approximation. It has **no** access to `NSToolbar`,
`NSSplitViewController` source-list sidebars with vibrancy, SF Symbols, Liquid
Glass / `NSVisualEffectView` materials, the system accent color, semantic
`NSColor`, view-based `NSTableView` / `NSOutlineView`, runtime `NSAppearance`
dark-mode switching, the standard app menu / About panel, `NSDraggingDestination`,
`QLPreviewPanel`, or `NSUserDefaults`-native window restoration. The current
hand-drawn PNG icons, custom modal `Toplevel`s (Tk's `messagebox` ignores the
parent window on macOS) and the fixed 1300×800 window are symptoms of fighting
the toolkit.

**Two honest paths:**

| | Path A — native UI-layer rewrite | Path B — maximal Tkinter refresh |
|---|---|---|
| What changes | `gui.py` → PyObjC/AppKit (or a thin SwiftUI shell over the Python logic). `main.py`, `setup.py`, `build_icon.py` adjusted. | `gui.py` restructured; ttk restyle; dark mode via appearance polling; spacing/color tokens. |
| What is **untouched** | `serato_db.py`, `scanner.py`, `copier.py`, `metadata_editor.py` (verified: zero UI imports). | same. |
| Result | Real toolbar, source-list sidebar, SF Symbols, materials, system accent, semantic colors, native tables, sheets, drag & drop, Quick Look, native About/menu. **Meets the bar.** | Cleaner, denser, dark-mode-aware Tk utility. **Does not meet the bar** — a Mac user still reads "a Python/Tk app". Drag & drop needs `tkdnd`; Quick Look / command palette / true sheets are not available. |
| Cost | High. ~20 issues, multi-session. New dependency: `pyobjc` (a common py2app companion). | Medium. Fewer of the power-user items are feasible. |
| Risk to logic | None — logic modules imported and called exactly as today. | None. |

**Recommendation: Path A.** The brief's own final test — *"If I removed the app
name, would a Mac user immediately believe this was designed for macOS?"* —
cannot be passed in Tkinter, and roughly a third of the second-pass requirements
(Quick Look, command palette, true window-attached sheets, native drag & drop,
Undo menu integration) are AppKit-only. Path B is a legitimate fallback if the
stack must stay pure-Tk, chosen with eyes open.

Everything below applies to **either path**. Per-screen "native mapping" notes
assume Path A; "Tk fallback" notes cover Path B.

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

## 1. Product model

Serato Migrator is **not a set of tabs**. It is a professional **DJ library
management + migration utility**. The mental model, per component:

| Reference | What we borrow |
|---|---|
| **Finder** | source-list navigation, three-column layout, context menus, Reveal-in-Finder, drag & drop, Quick Look |
| **Music** | library → crates → tracks → metadata; a track inspector; bulk metadata editing |
| **Disk Utility** | migration/verification as a guided, safety-first operation with clear before/after state and a health verdict |
| **Console** | a filterable activity log with a raw-output escape hatch for troubleshooting |

Every UX decision below is checked against this model.

---

## 2. Current UI architecture (as-is)

### 2.1 Shell
- One `Tk` root, `SeratoMigratorApp` class, window fixed at `1300x800`, `minsize 1000x650`.
- 3.2 s custom splash (`_show_splash`).
- Top: a hand-rolled **tab bar** — plain `ttk.Label`s, click-bound, with a
  cached pill-image "selected" background. Not `ttk.Notebook`.
- Content: 7 `ttk.Frame`s stacked in one `grid` cell; `_select_tab` raises one.
- Bottom: single-line status bar (`status_var`).
- No menu bar. No accelerators. `WM_DELETE_WINDOW` → `_on_close`.

### 2.2 Destinations (tabs), in bar order
`libs` Biblioteci · `crates` Crate-uri · `orphans` Fisiere orfane ·
`migrate` Migrare / Reorganizare · `metadata` Metadata · `log` Jurnal ·
`about` Despre — built by `_build_tab_*`.

### 2.3 Visual system
- ttk `clam`. Custom styles: `TabItem.TLabel`, `Divider.TFrame`, `Status.TLabel`,
  `Icon.TButton`, `Warn.TLabel`, `Ok.TLabel`, `Treeview*`, dot expander element.
- **Hardcoded colors** (module constants): `ACCENT #3B8FDA`, `ACCENT_2 #00CEC9`,
  `APP_BG #E7E7ED`, `SURFACE #FFFFFF`, `BORDER #E3E3EA`, `TEXT_MAIN #1C1C1E`,
  `TEXT_MUTED #6E6E76`, splash + logo-gradient stops. **No dark mode. No system accent.**
- Fonts: `TkDefaultFont` forced to 14 (`BASE_FONT_SIZE`), Menlo 13 for the log.
- Icons: procedurally drawn `PhotoImage`s (`_build_refresh_icon`,
  `_build_locate_icon`, `_build_database_icon`, `_build_export_icon`,
  `_build_dot_icon`, `_build_app_icon`).

### 2.4 Background operations (all: `threading.Thread(daemon=True)` + `queue.Queue` + `root.after` polling)
| op | trigger | poll | busy label |
|---|---|---|---|
| library scan | `refresh_libraries` (also on launch) | `_on_libraries_scanned` | `scanare biblioteci` |
| "missing elsewhere" scan | `_check_missing_elsewhere` | `_poll_missing_progress` → `_show_missing_results` | `cautare track-uri lipsa` |
| orphan scan | `_scan_orphans` | `_poll_orphan_progress` → `_on_orphans_found` | `scanare fisiere orfane` |
| rebuild database | `_rebuild_database` | `_poll_rebuild` | `reconstruire baza de date` |
| add orphans to crate | `_add_orphans_to_crate` | inline `poll()` | `adaugare orfane in crate` |
| migration copy | `_run_migration` | `_poll_progress` | `migrare` |
| per-crate size calc | `_start_mig_size_computation` | `_poll_mig_sizes` | (not busy-gated) |

`_begin_busy`/`_end_busy` maintain `_busy_count` + `_busy_labels`; while > 0
`_on_close` refuses and names the running op. No global progress UI — only the
status string plus, for migration, one `ttk.Progressbar`.

### 2.5 Dialogs
- `_show_dialog` custom `Toplevel` → `show_info`, `show_warning`, `ask_yesno` (buttons centered).
- Native pickers: `filedialog.askdirectory`, `filedialog.asksaveasfilename`.
- Result windows (1000×600 `Toplevel`): `_show_missing_results`,
  `_show_artist_title_review`.
- Custom `_Tooltip` (400 ms).

### 2.6 Keyboard / menu / persistence / dark mode
- **Shortcuts:** none global. Widget-level `<Return>` in the two search entries; `<<TreeviewSelect>>`.
- **Menu:** none. **State persistence:** none. **Dark mode:** none. **Undo:** none.

### 2.7 Per-screen inventory (condensed)

**Biblioteci** — icon toolbar (refresh · verifică-lipsă · rebuild-db · export-db)
+ 6-col `Treeview` (`nume, radacina, tracks, prezente, lipsa, crate_uri`), full
border, no summary, no selection detail, no context menu.

**Crate-uri** — `PanedWindow`. Left: hierarchical `crates_tree` (`%%`-split
names, dot expanders). Right: Toate/OK/Lipsă radios + `tracks_tree` (Status ·
Artist · Titlu · Cale, click-sortable, sort survives filter).

**Fisiere orfane** — root combobox (library volume roots) + "Alege folder…" +
"Scanează" + "Adaugă în crate «Orfane»" (enabled only after a scan finds orphans
under a known library). Info line. `orphans_list` (Cale · Mărime, sortable).
No search, no per-row actions, no reveal, no empty state.

**Migrare / Reorganizare** — dense two-column form: source-library checkboxes +
crate picker (☑/☐/▣ toggle, bg size calc, Toate/Niciunul, include-unsorted, live
"K/N • ~X GB") · destination entry + "Alege…" · options (copy `_Serato_`,
rewrite paths, generate fresh DB, normalize CAPS) · Previzualizare / Copiază acum
· plan summary · space-fit label (green/red) · `ttk.Progressbar` · "details in
Jurnal". `_run_migration`: doesn't-fit confirm → final confirm → run;
`_poll_progress` streams per-file lines to the log; phase signals
`fresh_start/done`, `serato_start/done`, `rewrite_start/done`, `error`.

**Metadata** — library combobox + "Deschide folder…" + search + "Analizează
Artist/Titlu lipsă". `PanedWindow`: left `metadata_tree`
(Artist/Titlu/Album/Gen/Fișier, sortable, multi-select `extended`); right an
"Editare" frame (4 entries + Salvează + "scrie și ID3"). Single-track applies all
4 fields; multi applies only filled fields. `_analyze_artist_title` →
`_show_artist_title_review` checklist window.

**Jurnal** — read-only `Text` (Menlo 13) + "Curăță jurnalul". `self.log(msg)`
timestamps `[HH:MM:SS] …`. No levels, filter, search or export. De facto the
progress/detail view for migration + rebuild.

**Despre** — centered logo + name + version + paragraph + bullet list.

---

## 3. Problems found

Shell/visual: reads as a Python/Tk app; no dark mode; no system accent; wasted
horizontal space in a flat 7-tab bar with no grouping; "Despre" is a primary
destination; custom modal `Toplevel`s instead of sheets; one font size; free-
floating result windows.

Product/UX: **no Overview** — the app never answers "which library, is it
healthy, what next"; **no persistent active-library status**; **no Library or
Crate Health concept**; weak hierarchy on Biblioteci (empty bordered table, no
title/summary/detail/context menu); the **Journal is load-bearing** for progress
detail; **no global "work in progress" affordance** beyond a string; **migration
is a form, not a flow**, its destructive confirm is visually identical to a
navigation dialog, and there is **no backup option and no post-migration
verification**; Orphans is a bare list with **no state design** (before /
scanning / nothing-found / results); Metadata bulk edit can **silently
overwrite** ambiguous fields (today: multi applies every non-empty field with no
per-field opt-in shown); **no keyboard model / no menu / no ⌘,**; **no state
persistence**; numbers not localized; **no context menus**; **no drag & drop**;
**no track preview**; **no reusable component system** — every screen is bespoke.

---

## 4. Proposed information architecture

### 4.1 Window shell
`Sidebar | Content | Inspector` (three-column, HIG). Inspector is per-screen and
collapsible; it appears where it adds value (Overview/Biblioteci detail,
Crate-uri track detail, Metadata single-track) and is hidden elsewhere. Toolbar
unified with the title bar. Minimum window ~980×620; frame persisted.

### 4.2 Sidebar (replaces the tab bar)

```
Serato Migrator                    (app name, small, non-interactive header)

  ●  Prezentare              square.grid.2x2  / house
─────────────────────────────
BIBLIOTECĂ
  ●  Biblioteci              internaldrive
  ●  Crate-uri               square.stack.3d.up
  ●  Fișiere orfane          questionmark.folder
INSTRUMENTE
  ●  Migrare                 shippingbox / arrow.right.doc.on.clipboard
  ●  Metadata                tag
SISTEM
  ●  Jurnal                  list.bullet.rectangle
─────────────────────────────
  Music                              ← ACTIVE-LIBRARY STATUS (see 4.4)
  23.100 track-uri
  ✓ Totul este în regulă
```

- Native source list, `.sidebar` material, **system accent** for selection.
- Collapsible (toolbar sidebar-toggle + ⌘⌥S). Selected destination persisted.
- SF Symbols per row (names above are candidates; finalised in UI-02).
- **"Despre" removed as a destination** → `Serato Migrator ▸ Despre Serato
  Migrator` (standard About panel: icon, name, version, one credit line).
- **Settings** → `Serato Migrator ▸ Setări…` (⌘,) — a small preferences window
  (see 4.11), not a sidebar row.
- Narrow window: sidebar auto-collapses to icons, then overlays.

### 4.3 Toolbar (per screen, contextual)
- **Leading:** sidebar toggle · screen title.
- **Center:** the primary verbs for the visible screen (icon + tooltip).
- **Trailing:** search field (⌘F focuses it) where it helps · **one** true primary
  action only when one exists · `•••` overflow for secondary actions ·
  inspector toggle where an inspector exists.
- No large colored rectangles except a genuine primary action.

| Screen | Center | Trailing |
|---|---|---|
| Prezentare | Scanează din nou | (none) |
| Biblioteci | Reîmprospătează · Rescanează · Verifică lipsă | Export… · ••• (Rebuild DB, Reveal in Finder) · inspector |
| Crate-uri | Expand all · Collapse all | search · segmented Toate/OK/Lipsă · inspector |
| Fișiere orfane | Alege folder · Scanează | search · **Adaugă N în «Orfane»** (selection-aware) · ••• (Reveal, Copy paths) |
| Migrare | step pager (Sursă…Complet) | **Începe migrarea** (Review step only) |
| Metadata | Analizează Artist/Titlu | search · segmented Toate/Incomplete/Fără artist/Fără titlu · inspector |
| Jurnal | segmented **Activitate / Raw** · (in Activitate) Toate/Info/Avertismente/Erori | search · Copiază · Golește · Export… |

### 4.4 Active-library status + Library Health (global)

A subtle block pinned to the **sidebar footer**, always visible:

```
Music
23.100 track-uri
✓ Totul este în regulă
```

or, when there is a problem:

```
Music
23.100 track-uri
⚠ 37 fișiere lipsă        [Vezi]
```

- Not visually heavy: caption-size text, one status line (icon + label, never
  color-only), an optional inline `[Vezi]` link.
- Clicking the block → **Prezentare**. Clicking `[Vezi]` → the relevant filtered
  screen (missing files → Crate-uri filtered to "Doar lipsă" / a dedicated
  missing view; incomplete metadata → Metadata filtered to "Incomplete").
- With a **single** detected library, no library-picker chrome anywhere — the
  footer *is* the selector context.
- With multiple libraries, the footer shows the active one; switching happens in
  Prezentare / Biblioteci (selecting a row makes it active).

**Library Health** is a derived value (no new persisted model, no logic change):

| State | Derivation (existing data) |
|---|---|
| `↻ Se scanează` | a scan busy-op is running for this library |
| `⚠ Fișiere lipsă` | `len(lib.missing_tracks) > 0` |
| `⚠ Metadata incompletă` | count of tracks with empty artist **or** empty title > 0 (cheap pass over `lib.tracks`) |
| `⚠ Probleme detectate` | `database V2` missing/unparseable, or `_Serato_` unreadable |
| `✓ Biblioteca este în regulă` | none of the above |
| plus `Ultima scanare: …` | timestamp captured when `_on_libraries_scanned` runs (persisted per library root) |

Health is shown on: Prezentare (headline), Biblioteci (row badge + inspector),
sidebar footer. Each problem state is a link to its filtered screen.

### 4.5 Status & health vocabulary (icon + label, never color-only)
`✓ Sănătoasă` · `⚠ Fișiere lipsă` · `⚠ Metadata incompletă` · `⚠ Problemă bază
de date` · `↻ Se scanează` · `✓ Migrare finalizată` · `⚠ Finalizată cu
avertismente` · `✕ Migrare eșuată` · `● Nesalvat`. SF Symbols:
`checkmark.circle`, `exclamationmark.triangle`, `exclamationmark.octagon`,
`arrow.triangle.2.circlepath`, `xmark.octagon`.

---

## 5. Screen-by-screen redesign

### 5.0 Prezentare (Overview) — new initial screen

Purpose: answer, at a glance — *which library is active, is it healthy, how big,
any problems, when last scanned, what to do next.* **Not** a dashboard of cards.

```
Music
/Volumes/Music

✓ Biblioteca este în regulă

23.100 track-uri     145 crate-uri     0 lipsă

Ultima scanare: astăzi, 02:02

[ Scanează din nou ]

Acțiuni rapide
  Migrează biblioteca
  Verifică fișierele
  Analizează metadata
```

- Headline = library name + path + the Health line (large).
- One quiet row of `value + label` pairs (localized numbers) — **not** four KPI tiles.
- `Ultima scanare` from the persisted timestamp.
- One primary button (`Scanează din nou` → `refresh_libraries`).
- "Acțiuni rapide" = three plain links that navigate to Migrare / (missing view) /
  Metadata, pre-filtered where sensible.
- If Health is a warning, the headline shows it and offers `[Vezi fișierele]` etc.
- **Single library:** no selector. **Multiple:** a compact switcher at the top;
  selecting changes the active library everywhere.
- Empty (no library): `Nu a fost detectată nicio bibliotecă Serato.` +
  `Conectează un volum cu un folder _Serato_ sau alege manual unul.` +
  `[ Alege bibliotecă… ]` (existing `askdirectory` + `scanner.load_library_at`).
- Native: content view + optional inspector. Tk fallback: a centered column,
  restrained.

### 5.1 Biblioteci
- Header `Biblioteci` + subtitle `Biblioteci Serato detectate pe acest Mac`.
- Subtle summary strip (one row, label/value pairs, localized) —
  `1 Bibliotecă · 23.100 Track-uri · 23.100 Disponibile · 0 Lipsă · 145 Crate-uri`.
- Table `Bibliotecă · Locație · Track-uri · Disponibile · Lipsă · Crate-uri` +
  a **Health** badge column. Numeric columns right-aligned, monospaced digits.
  Hover + selection states, sortable headers, subtle separators, **no outer
  border**, auto column sizing.
- **Context menu:** Reveal in Finder · Rescan Library · Verifică fișiere lipsă ·
  Rebuild Database · Export Database.
- **Double-click:** reveal the volume root in Finder.
- **Inspector** (row selected, collapsible): Locație · Track-uri · Disponibile ·
  Lipsă · Crate-uri · `Status: ✓ Bibliotecă OK` / warning link · Ultima scanare;
  then Deschide în Finder · Rescanează · Verifică lipsă · Rebuild Database ·
  Export Database.
- Selecting a row sets the **active library**.
- Empty state as in 5.0.
- Preserve: `_on_libraries_scanned`, `refresh_libraries`,
  `_check_missing_elsewhere`/`_show_missing_results`, `_rebuild_database`,
  `_export_database`, manual `load_library_at`.

### 5.2 Crate-uri + Crate Health
- Left: outline / source list of the crate hierarchy (parents, subcrates). Each
  row: **crate name · right-aligned track count · a small `⚠ N` when the crate
  has missing tracks** (N = count of missing in that crate). Nothing else on the
  row.
  ```
  Music
    House                 184
    Tech House            312
    Wedding               421   ⚠ 3
    Oldies                817   ⚠ 12
  ```
- Expand-all / collapse-all; toolbar search filters the outline; segmented
  Toate/OK/Lipsă in the toolbar controls the right-hand track list.
- Right: track list — Status · Artist · Titlu · Cale, sortable (sort survives the
  filter). Selecting a track opens the **Track Inspector** (5.8).
- **Crate context menu:** Deschide folderul în Finder · Copiază căile track-urilor
  · Rescanează · (future) Exportă crate.
- **Track context menu:** see 5.8.
- Empty: `Biblioteca nu conține crate-uri.` / no crate selected:
  `Selectează un crate pentru a vedea track-urile.`
- Preserve: `_refresh_crates_tree`, `_on_crate_selected`/`_render_tracks_tree`,
  `track_filter_var`, `_sort_tracks`.

### 5.3 Fișiere orfane — state-driven diagnostics

Explicit states, one visible at a time:

**BEFORE SCAN** — a short explanation of what an orphan is + the selected
location (volume-root combobox or a chosen/dropped folder) + primary
`[ Scanează ]`.

**SCANNING** — progress; current location if the scanner reports it; files
inspected count; **Cancel only if safe** (`find_orphan_files` has no cancel hook
today → either omit Cancel or add a cooperative flag as a sub-issue; do not fake it).

**NOTHING FOUND** — no empty table:
```
✓ Nu au fost găsite fișiere orfane
Toate fișierele audio scanate sunt asociate bibliotecii Serato.
```

**RESULTS FOUND** —
```
142 fișiere orfane · 3.7 GB
```
then the table (`Fișier · Locație · Mărime`, size numeric-sorted, localized),
search over it, bulk selection (⌘-click, shift, ⌘A). Actions reflect the
selection: **`Adaugă 23 în crate-ul Orfane`** (falls back to the full count when
nothing is selected). Plus Reveal in Finder, Copy paths.

- Preserve: `_scan_orphans`/`_poll_orphan_progress`/`_on_orphans_found`,
  `orphan_combo` + `_browse_orphan_root`, `_add_orphans_to_crate` →
  `copier.add_orphans_to_crate` (idempotent, backs up `database V2`).
- Drag & drop: dropping a folder onto this screen sets the scan location and (if
  the user confirms) starts a scan.

### 5.4 Migrare — the hero workflow

The app is called *Serato Migrator*; this must be the most polished, most
trustworthy flow. A guided pager:

```
Sursă → Destinație → Opțiuni → Verificare → Migrare → Verificare-post → Complet
```

**Sursă** — pick library/libraries; then the crate picker (existing ☑/☐/▣ tree,
per-crate size, Toate/Niciunul, include-unsorted). Footer: `K/N crate • ~X GB`.
Shows the source summary: `Music · /Volumes/Music · 23.100 track-uri · 145
crate-uri`.

**Destinație** — folder well + `Alege…` (native picker; drag & drop a folder/volume
accepted). Shows destination path, **volume name**, **available storage**,
**required storage** (from `copier.estimate_required_bytes`), and the fit verdict
inline (`✓ Spațiu suficient` / `✕ NU ÎNCAPE — lipsesc ~Z`, icon + label).

**Opțiuni** — grouped and labelled by consequence, each with a one-line caption:
- *Structură bază de date:* **Copiază `_Serato_` + rescrie căile** vs
  **Generează bază de date nouă (doar ce migrez)**.
- *Fișiere:* Normalizează numele SCRISE CU MAJUSCULE.
- *Siguranță:* **☑ Creează backup înainte de migrare** — reuses
  `copier.export_database` to write a timestamped
  `Serato DB - <lib> - <date>.zip` next to the destination (or a chosen folder)
  **before** any copy. This is real, existing, verified functionality — not a new
  backup engine. Default on.

**Verificare** (nothing changed yet):
```
Music  ↓  Samsung T7

23.100 track-uri · 145 crate-uri · 184 GB

Spațiu necesar:     184 GB
Spațiu disponibil:  684 GB
✓ Spațiu suficient
✓ 0 fișiere lipsă
Bază de date:       Generează una nouă, doar cu crate-urile alese
Nume:               Normalizate
Backup:             Serato DB - Music - 2026-09-06.zip

Fișierele originale NU sunt șterse, mutate sau redenumite.

[ Începe migrarea ]
```
`[ Începe migrarea ]` is the only primary button, only here. It still triggers
the existing final `ask_yesno` (as a **sheet**) and the doesn't-fit sheet when relevant.

**Migrare** — a dedicated progress surface (not the log): determinate bar,
`Copiere 1.482 / 23.100 fișiere · 18%`, current file, elapsed, ETA when the rate
is stable; phase labels for backup / copy / `_Serato_` copy / path rewrite /
fresh-DB (existing `serato_start/done`, `rewrite_start/done`, `fresh_start/done`
signals, plus a new `backup_start/done`). **Cancel** only if a cooperative flag
is added to `copier.execute_plan` (its own opt-in sub-issue) — otherwise omit it.

**Verificare-post** — after the copy, a lightweight verification pass (feasible
without touching migration logic): for each planned primary op, confirm the
destination file exists and its size matches the source; confirm the new
`database V2` parses and its track count matches. Report:
```
Migrare finalizată

✓ 23.100 track-uri procesate
✓ 145 crate-uri migrate
✓ Fișiere verificate (23.100 / 23.100)
✓ Baza de date poate fi citită

Durată: 18m 42s
```
On failures:
```
Migrare finalizată cu avertismente
23.097 reușite · 3 eșuate
[ Vezi problemele ]   →  list of the failed source→dest pairs + reasons
```

**Complet** — the result panel above, with `Deschide în Finder` and a link to
the raw log for this run.

- Destructive/irreversible framing: originals are only ever **copied**; the flow
  states this on the Review step and the confirm sheet. Nothing in this flow
  moves, renames or deletes source files — say so.
- Preserve every migrate handler in the §7 checklist.

### 5.5 Metadata — single vs bulk

Two related workflows sharing one editor component.

**Single track** → the **Track Inspector** (5.8): edit the four fields there,
Save applies them (including deliberate blanks, matching current single-edit logic).

**Bulk** → the Metadata screen, optimised for find-and-fix:
- Toolbar segmented filter: **Toate · Incomplete · Fără artist · Fără titlu**
  (only these — all reliably derivable from `lib.tracks`: empty artist/title;
  "Incomplete" = empty artist or title or genre).
- List = current `metadata_tree` (sortable, `selectmode="extended"`), plus search.
- Multi-select editor — **never silently overwrite an ambiguous field:**
  ```
  20 track-uri selectate

  Artist   — Valori multiple —          ☐ Actualizează Artist
  Titlu    — Valori multiple —          ☐ Actualizează Titlu
  Album    (gol)                        ☐ Actualizează Album
  Gen      House                        ☑ Actualizează Gen   → [ House            ]

  ☑ Scrie modificările și în tag-urile ID3

  [ Aplică la 20 track-uri ]
  ```
  A field changes **only** if its `Actualizează …` box is ticked. Fields with one
  common value across the selection prefill and pre-tick nothing;
  `— Valori multiple —` for mixed. The confirm sheet lists exactly which fields
  change and on how many tracks.
- `Analizează Artist/Titlu lipsă` stays; its review list becomes a **sheet /
  inline panel**, not a free window.
- Empty: `Nicio bibliotecă selectată.` / after search: `Niciun rezultat pentru „<q>".`
- Preserve: `_search_metadata_tracks`, `_save_metadata_edit` (single=all,
  multi=selected-fields — the multi path changes from "filled" to "ticked", an
  intentional UX fix), `metadata_write_id3_var`, `metadata_editor.apply_edits`,
  `_analyze_artist_title`/`_show_artist_title_review`, post-write reload.

### 5.6 Jurnal — Activitate + Raw Log

Do **not** remove the technical log. Two representations, switchable
(`[ Activitate | Raw Log ]`), default **Activitate**:

**Activitate** — human-readable, grouped by day:
```
ASTĂZI
  ✓ 02:02  Scanare finalizată        Music · 23.100 track-uri · 0 lipsă
  ✓ 01:54  Baza de date exportată    Music
  ⚠ 01:48  3 fișiere nu au putut fi găsite
```
Rows are `severity icon · time · operation · one-line detail`, selectable, ⌘A/⌘C.
In-view sub-filter Toate/Info/Avertismente/Erori + search. Built from
structured entries.

**Raw Log** — the current console output verbatim (monospaced), for
troubleshooting. Copy · Golește · Export….

Implementation: `self.log(...)` gains **additive** params
`log(msg, level="info", op=None, detail=None)`; existing single-arg calls keep
working. Structured entries feed Activitate; the plain lines still feed Raw.

- Empty: `Nu există evenimente în jurnal.`
- Preserve: append-on-every-op, `_clear_log`.

### 5.7 About
Removed from navigation → `App menu ▸ Despre Serato Migrator` (standard About
panel). The feature paragraph lives in the README, not the app.

### 5.8 Track Inspector — reusable component

One component, used from Crate-uri, Metadata (single), and the missing/orphan
views. Contextual, collapsible, right-hand.

```
INFORMAȚII TRACK

Lady (Hear Me Tonight)
Modjo

Album      Modjo
Gen        French House
Locație    /Volumes/Music/House/Modjo - Lady…mp3
Status     ✓ Fișier disponibil        (or  ⚠ Fișier lipsă)

METADATA
Artist   [ Modjo                    ]
Titlu    [ Lady (Hear Me Tonight)   ]
Album    [ Modjo                    ]
Gen      [ French House             ]
☑ Scrie și în ID3      [ Salvează ]

ACȚIUNI
Editează metadata   ·   Deschide în Finder   ·   Copiază calea
```

- Reads track fields from the existing `sdb.Track` / library data — **no new
  parsing**. Save routes through `metadata_editor.apply_edits` exactly like the
  current Metadata single-edit.
- Status derived from `Path(track.abs_path).exists()`.
- Same component instance/logic wherever a single track is selected — no
  duplicated business logic.

---

## 6. Component & interaction strategy

### 6.1 Reusable components (design system — build once, use everywhere)
The app must feel like **one product**. Application-level components/patterns:

1. **Sidebar** — grouped source list + footer active-library status block.
2. **Toolbar** — leading title / contextual center verbs / trailing search +
   primary + `•••` + inspector toggle.
3. **Search field** — one style; ⌘F focuses the current view's search.
4. **Segmented filter** — Toate/OK/Lipsă, Toate/Incomplete/…, Activitate/Raw.
5. **Data table / list** — hover, selection, sortable headers (reuse
   `_attach_column_sort` logic), right-aligned monospaced numerics, subtle
   separators, no outer border, context menu.
6. **Outline** — crate hierarchy with count + `⚠ N` affordance.
7. **Empty state** — icon + title + one sentence + optional single action.
8. **Status indicator** — icon + label, semantic, never color-only.
9. **Progress surface** — determinate bar + N/total + current item + elapsed +
   ETA-when-stable + phase label; used by migration, rebuild, big scans.
10. **Global operation status** — transient sidebar-footer / toolbar strip
    (`↻ Se scanează Music… 12.821 / 23.100   Anulează`); shown **only** while an
    op runs, never a permanent empty bar.
11. **Inspector** — collapsible right pane; Track Inspector + Library Inspector
    are instances.
12. **Confirmation** — sheet attached to the window; destructive actions look
    distinct from navigation (icon, wording, default button).
13. **Context menu** — per object type (see 6.2).
14. **Activity item** — `severity · time · operation · detail`, reused in Jurnal
    and any inline "recent activity".
15. **Error / warning presentation** — one consistent block (icon, summary,
    optional `[ Vezi… ]`, optional details disclosure).

Tokens (both paths): spacing **4 / 8 / 12 / 16 / 24 / 32**; radii **6** controls
/ **10** panels, nothing larger; type styles referenced by **name**
(`largeTitle`, `headline`, `body`, `secondary`, `caption`), not literals;
colors from **semantic system values** + `controlAccentColor`, resolved at
runtime, swapped on appearance change; number formatting via one locale-aware
`format_int` helper used only in display code.

### 6.2 Context menus (reduce permanent button clutter)
- **Track:** Deschide în Finder · Editează metadata · Adaugă în crate ▸ · Copiază
  calea · Rescanează.
- **Crate:** Deschide · Deschide folderul în Finder · Copiază căile · Rescanează
  · (future) Exportă.
- **Library:** Rescanează · Verifică fișiere lipsă · Rebuild Database · Export
  Database · Deschide în Finder.
Only actions that exist today (or land safely in a scoped issue) appear.

### 6.3 Drag & drop (only where it does real work, with feedback)
- Folder → **Fișiere orfane**: set scan location (+ optional auto-start).
- Folder / volume → **Migrare ▸ Destinație**: set the destination.
- (Path A) `NSDraggingDestination` with a highlight + a "will scan / will set
  destination" hint. (Path B) needs `tkdnd`; if unavailable, drag & drop is
  dropped from scope for B.

### 6.4 Keyboard-first
- `⌘F` focus the current view's search · `⌘R` rescan/refresh the current view ·
  `⌘,` Settings · `Space` Quick Look / audio preview where supported · `⌘K`
  command palette (optional, last) · standard `⌘W`/`⌘Q`/`⌘M` unchanged ·
  `⌘C`/`⌘A` in tables/log.
- Never override a standard shortcut with surprising behaviour.
- A proper **menu bar**: Serato Migrator (About, Setări…, Quit) · Fișier (Alege
  bibliotecă…, Export bază de date…) · Editare (Undo/Redo where safe, Cut/Copy/
  Paste, Selectează tot, Găsește) · Bibliotecă (Rescanează, Verifică lipsă,
  Rebuild, Scanează orfane) · Fereastră · Ajutor.

### 6.5 Settings (⌘,)
Small window, one pane initially:
- Backup înainte de migrare (default on) + backup location (Lângă destinație /
  Folder ales).
- Normalizare nume implicit (on/off default for the migrate option).
- Confirmări (arată/ascunde confirmările non-distructive).
- Aspect: Sistem / Deschis / Închis (override `NSAppearance`).
All read/written via persisted state; no logic impact.

### 6.6 Quick Look / audio preview — **optional**
`Space` on a selected track. Prefer native: (Path A) `QLPreviewPanel` for the
file, or a tiny `AVAudioPlayer` transport (play/pause, scrubber, name/artist/
duration/location). (Path B) shell out to `qlmanage -p` or `afplay` with a stop
control. **Do not build a media player.** If it can't be done simply and
reliably, ship without it.

### 6.7 Command palette ⌘K — **optional, after the primary UI is stable**
Fuzzy list of verbs: Scanează Music · Scanează orfane · Migrează biblioteca ·
Analizează metadata lipsă · Deschide Jurnal · Setări… · Reveal library in Finder.
Complements menus + shortcuts, never replaces them.

### 6.8 Undo / operation history
- **Metadata edits:** candidate for real Undo — capture the previous
  `{tag: value}` per track before `apply_edits`, offer `Editare ▸ Undo`
  (re-applies the captured values). Only if it can be made reliably reversible
  including the ID3 write; otherwise **no Undo**, just an Activity entry.
- **Migration / rebuild / add-orphans / export:** **never** claim Undo. They
  leave a timestamped backup (`_Serato_ (backup …)`, `database V2 (orfane
  backup …)`, the pre-migration `.zip`) and an Activity entry describing exactly
  what happened. The user restores by renaming a backup — documented, not automated.

### 6.9 Per-path component mapping
| Concern | Path A (native) | Path B (Tk) |
|---|---|---|
| Shell | `NSWindow` + `NSSplitViewController` + unified `NSToolbar` | `PanedWindow`/frames + custom toolbar frame |
| Sidebar | `NSOutlineView` source list, `.sidebar` material, SF Symbols | grouped label column, symbol PNGs, accent read from `NSColor` |
| Tables | view-based `NSTableView` + `NSMenu` | `ttk.Treeview` + `tag_configure` + `Menu`; `_attach_column_sort` kept |
| Outline | `NSOutlineView` | `Treeview` `show=tree` + count text |
| Dialogs | window sheets (`beginSheet`) | restyled `_show_dialog` `Toplevel`, centered |
| Pickers | `NSOpenPanel` / `NSSavePanel` | `filedialog` (already native) |
| Progress | `NSProgressIndicator` + progress panel | `ttk.Progressbar` in a dedicated panel |
| Drag & drop | `NSDraggingDestination` | `tkdnd` if present, else omit (B only) |
| Quick Look | `QLPreviewPanel` / `AVAudioPlayer` | `qlmanage` / `afplay` |
| Colors / type | semantic `NSColor` + `preferredFont(forTextStyle:)` | runtime token module from `NSColor`, named font styles |
| Dark mode | automatic via `NSAppearance` | subscribe `AppleInterfaceThemeChangedNotification` / poll `AppleInterfaceStyle`, swap tokens, repaint |
| State | `NSUserDefaults` | `~/Library/Application Support/Serato Migrator/state.json` |
| Menu / About / Settings | standard AppKit | Tk `Menu` on root; custom About + Settings `Toplevel`s |

State to persist: window frame · sidebar collapsed · inspector collapsed ·
selected destination · active library root · per-table sort · last migration
destination · last orphan scan root · Jurnal Activitate/Raw + level filter ·
per-library "last scan" timestamp · Settings values.

---

## 7. Implementation plan (Phase 4)

Incremental, one screen/system at a time, `build → run → verify checklist →
commit → PR`. Each PR keeps the app runnable; no placeholder UI, no TODO
handlers on `main`.

| Issue | Scope | Depends on |
|---|---|---|
| **UI-00** | Design-system foundation: token module (spacing/radii/type-style names/semantic colors), the reusable component set from §6.1 as stubs backed by real behaviour, `format_int` locale helper | UI-01 |
| **UI-01** | Window shell + unified toolbar + menu bar + About panel + Settings (⌘,) window + state-persistence layer; splash decision; py2app build/launch check | — |
| **UI-02** | Sidebar navigation (grouped, SF Symbols, accent, collapse ⌘⌥S, persisted selection) + **active-library status footer** + retire "Despre" | UI-01, UI-00 |
| **UI-09** | Inspector architecture (three-column split, per-screen, collapse + persist) | UI-01, UI-00 |
| **UI-10** | Dark Mode + system accent + semantic color tokens + Reduce Transparency / Increase Contrast + font-style hierarchy; verify hand-drawn icons/logo both appearances | UI-01, UI-00 |
| **UI-16** | Library Health + Crate Health derived model (no logic change) + per-library "last scan" timestamp; health links navigate to filtered screens | UI-02, UI-10 |
| **UI-14** | **Prezentare / Overview** screen (single- and multi-library), quick actions, empty state | UI-02, UI-16 |
| **UI-15** | **Track Inspector** reusable component (Crate-uri + Metadata single + missing/orphan) | UI-09, UI-10 |
| **UI-03** | Biblioteci: header, summary strip, table upgrade, Health badge, context menu, inspector content, empty state, row = active library | UI-02, UI-09, UI-10, UI-16 |
| **UI-04** | Crate-uri: outline + counts + `⚠ N`, expand/collapse, toolbar search/segmented, crate + track context menus, Track Inspector wiring, empty states | UI-02, UI-10, UI-15, UI-16 |
| **UI-05** | Fișiere orfane: BEFORE / SCANNING / NOTHING / RESULTS states, search/sort, bulk selection, selection-aware "Adaugă N în «Orfane»", Reveal / Copy paths, empty state | UI-02, UI-10 |
| **UI-06** | Migrare hero flow: Sursă→Destinație→Opțiuni→Verificare→Migrare→Verificare-post→Complet; destination storage math; **backup-before-migrate** (reuse `export_database`); dedicated progress surface; **post-migration verification**; result ✓ / ⚠ / ✕ panels | UI-02, UI-10, UI-16; (optional) `copier` cooperative-cancel sub-issue |
| **UI-07** | Metadata: segmented filters (Toate/Incomplete/Fără artist/Fără titlu), bulk editor with explicit per-field `Actualizează …` checkboxes, review as sheet; single-edit via Track Inspector | UI-02, UI-09, UI-10, UI-15 |
| **UI-08** | Jurnal: additive `log(msg, level, op, detail)`, **Activitate / Raw** switch, Activitate grouped-by-day filterable table, Raw = current console, copy/clear/export, empty state | UI-01, UI-10, UI-00 |
| **UI-17** | Context menus pass (track / crate / library) consolidated via the §6.2 spec; remove now-redundant permanent buttons | UI-03, UI-04, UI-05 |
| **UI-18** | Keyboard-first pass: ⌘F / ⌘R / ⌘, / ⌘C / ⌘A wired per view; full menu bar; focus-ring discipline | UI-01, UI-03…UI-08 |
| **UI-19** | Global operation status strip (transient) + wire cancellable ops; consistent progress across scans/migration/rebuild | UI-05, UI-06, UI-08 |
| **UI-11** | Empty / loading / success / warning / error states audited for **every** view (Section 20) | UI-03…UI-08, UI-14 |
| **UI-20** | Drag & drop: folder → Orfane scan, folder/volume → Migrare destination (Path A; Path B only if `tkdnd`) | UI-05, UI-06 |
| **UI-21** | *(optional)* Quick Look / audio preview on `Space` | UI-04, UI-15 |
| **UI-22** | *(optional)* Command palette ⌘K | UI-18 |
| **UI-23** | *(optional)* Undo for metadata edits only (capture-and-reapply); Activity-only history for everything else | UI-07, UI-08 |
| **UI-12** | Final visual consistency pass vs Finder / Music / Disk Utility / Console / macOS Settings | all non-optional |
| **UI-13** | Functional regression testing against the §8 checklist; fix regressions; verify py2app bundle | all non-optional |

---

## 8. Functionality-preservation checklist

Every item must still work after the redesign. `handler` = current method.
New features (Overview, Health, Track Inspector, hero flow, Activity log, context
menus, drag & drop, keyboard, Settings, optional Quick Look / palette / Undo) are
**additions** tracked by their issues — this list is only about **not regressing**.

### Navigation & shell
- [ ] Reach all real destinations (now: Prezentare, Biblioteci, Crate-uri,
      Fișiere orfane, Migrare, Metadata, Jurnal) — was `_select_tab`
- [ ] About reachable (now app menu) — was `_build_tab_about`
- [ ] Launch runs an initial library scan — `refresh_libraries` in `__init__`
- [ ] Window cannot close while a background op runs; the op is named — `_on_close` + `_busy_labels`
- [ ] "Serato DJ Pro is running" guard before DB writes — `_guard_serato_not_running`
      (rebuild, add-orphans, save-metadata, apply artist/title, migration when copying `_Serato_`)
- [ ] Current activity reflected somewhere visible — `set_status` → global op status

### Biblioteci
- [ ] Auto-detected libraries listed with name / root / tracks / present / missing / crates — `_on_libraries_scanned`
- [ ] Manual "choose a library folder" (validates `_Serato_` exists) — `askdirectory` + `scanner.load_library_at`
- [ ] Refresh / rescan — `refresh_libraries`
- [ ] Verifică fișiere lipsă (needs selection) → "found elsewhere" + "still missing" — `_check_missing_elsewhere` → `_show_missing_results`
- [ ] Rebuild Database (needs selection) → confirm → lightweight backup → new `database V2` (on-disk tracks only) → drop empty crates → result counts + backup path — `_rebuild_database` → `copier.rebuild_database_from_disk` → `_poll_rebuild`
- [ ] Export Database (needs selection) → `asksaveasfilename` → ~2 MB `.zip` — `_export_database` → `copier.export_database`

### Crate-uri
- [ ] Hierarchical crate tree (`%%` parents/subcrates) — `_refresh_crates_tree`
- [ ] Selecting a crate shows its tracks with present/missing status — `_on_crate_selected` → `_render_tracks_tree`
- [ ] Filter Toate / Doar OK / Doar lipsă — `track_filter_var`
- [ ] Click-sort Artist / Titlu / Cale, sort survives filter — `_sort_tracks` + `_tracks_sort`

### Fișiere orfane
- [ ] Scan root = a library volume root (combobox) or a chosen folder — `orphan_combo` + `_browse_orphan_root`
- [ ] Scan for audio unknown to Serato, live progress — `_scan_orphans` → `_poll_orphan_progress` → `_on_orphans_found`
- [ ] Result list: path + size, size sorts numerically — `orphans_list` + `_attach_column_sort`
- [ ] "Adaugă în crate «Orfane»" — enabled only after a scan finds orphans under a known library; confirm; backs up `database V2`; idempotent; refreshes libraries — `_add_orphans_to_crate` → `copier.add_orphans_to_crate`

### Migrare / Reorganizare
- [ ] Choose one or more source libraries — `lib_vars` / `_selected_libraries`
- [ ] Crate picker: per-crate + per-group ☑/☐/▣, Toate/Niciunul, background per-crate size, live "K/N • ~X GB" — `_build_migrate_crate_tree` … `_poll_mig_sizes`
- [ ] "Include și track-urile care nu-s în niciun crate" — `migrate_unsorted_var`
- [ ] `_selected_crate_keys()` returns `None` (full) or a set
- [ ] Destination picker — `_browse_dest`
- [ ] Options: copy `_Serato_`, rewrite paths, generate fresh DB, normalize CAPS — the four vars
- [ ] Previzualizare builds a `CopyPlan` off-thread — `_preview_migration` → `copier.plan_copy(...)`
- [ ] Plan summary (copies / hardlinks / total size / skipped-missing) — `_on_plan_ready`
- [ ] Space-fit verdict incl. cross-volume hardlink cost + `_Serato_` dir size — `_space_report` → `copier.estimate_required_bytes`; verdict shown — `_refresh_space_label`
- [ ] "Doesn't fit" confirm before running — `_run_migration`
- [ ] Guard: copy `_Serato_` requires exactly one library — `_run_migration`
- [ ] Final confirm lists counts, size, DB action, "originals not deleted" — `_run_migration`
- [ ] Runs `copier.execute_plan` + then `write_fresh_serato` **or** `copy_serato_folder` (+ `rewrite_serato_database` if enabled)
- [ ] Progress: determinate bar + per-file detail + phase labels (`fresh_start/done`, `serato_start/done`, `rewrite_start/done`) — `_poll_progress`
- [ ] Error path surfaces the exception and re-enables the action — `_poll_progress` `("error", …)`
- [ ] Success confirmation — `_poll_progress` `None`

### Metadata
- [ ] Library selector (auto libs + "Deschide folder…") — `_refresh_metadata_lib_choices` / `_open_metadata_folder`
- [ ] Text search across artist/title/album/genre/filename — `_search_metadata_tracks`
- [ ] Multi-select list, sortable columns — `metadata_tree` + `_attach_column_sort`
- [ ] Single-track edit applies all 4 fields (incl. deliberate blanks) — `_save_metadata_edit`
- [ ] Multi-track edit changes only the fields the user opted into (UX fix: was "any non-empty field") — `_save_metadata_edit`
- [ ] "Scrie și în ID3" toggle — `metadata_write_id3_var`
- [ ] Writes reach `database V2` **and** file tags — `metadata_editor.apply_edits`
- [ ] Post-write reload of affected tracks — `_save_metadata_edit` tail
- [ ] Analizează Artist/Titlu lipsă → review → apply selected (+ ID3) → reload — `_analyze_artist_title` → `_show_artist_title_review`

### Jurnal
- [ ] Every op appends a timestamped entry — `self.log` (now also structured)
- [ ] Migration/rebuild detail visible (Activitate + Raw + the progress surface)
- [ ] Clear the journal — `_clear_log`
- [ ] Existing single-arg `log("…")` calls keep working unchanged

### Cross-cutting
- [ ] Native folder/file pickers wherever they exist today
- [ ] Confirmations for: close-during-op, rebuild DB, add-orphans, doesn't-fit, final migration, "nothing to save", "nothing selected"
- [ ] Tooltips on every icon-only control
- [ ] `.icns` still generated by `build_icon.py`; py2app bundle still builds (`setup.py`)
- [ ] **No change** to `serato_db.py` / `scanner.py` / `copier.py` / `metadata_editor.py` public signatures, except the additive `log()` params and — only if separately approved — a cooperative-cancel flag in `copier.execute_plan` and a pre-`apply_edits` value-capture for metadata Undo

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Path A adds `pyobjc` and a much larger `gui.py` surface | one `ui/` package; logic modules frozen; each screen behind its own PR that keeps the app runnable |
| py2app + PyObjC packaging quirks | UI-01 includes a build + launch check before screen work |
| Regressions in the 6 background flows | UI-13 runs the §8 checklist end-to-end on the real Music library; every prior PR spot-checks its screen |
| "Cancel" expectation vs no safe cancel today | never fake it; a cooperative flag in `copier.execute_plan` / `find_orphan_files` is an explicit opt-in sub-issue with its own review |
| Post-migration verification touching migration logic | verification is a **separate read-only pass** (dest file exists + size match + DB parses); it does not modify `execute_plan` |
| Backup-before-migrate misread as a new backup engine | it is literally `copier.export_database` run before the copy; timestamped `.zip`; nothing new |
| Metadata Undo unreliable across ID3 formats | ship Undo only if reversible incl. the tag write; otherwise Activity-only history |
| Scope creep into logic (orphan→missing relink, audio engine) | out of scope; noted as future; optional items (Quick Look, palette, Undo) gated behind the core UI |
| Localised number formatting shifting test expectations | central `format_int`; display code only |
| Dark-mode contrast on hand-drawn icons / gradient logo | UI-10 verifies each in both appearances; recolor to semantic tokens |
| Empty-state / health text sprawl | one `EmptyState` and one `StatusIndicator` component; copy reviewed once |
| If Path B is chosen | drag & drop needs `tkdnd`, Quick Look/sheets/command-palette are degraded or dropped, and the final quality bar (brief §21) is **not** met — documented, your call |

---

## 10. What happens next

1. **You approve a path (A or B)** and the IA in §4.
2. I open / update issues per §7: new **UI-00, UI-14, UI-15, UI-16, UI-17, UI-18,
   UI-19, UI-20** (+ optional UI-21/22/23) and revise **UI-02, UI-05, UI-06,
   UI-07, UI-08, UI-09, UI-11**.
3. Phase 4: implement issue by issue, PR by PR, each keeping the app runnable and
   the §8 checklist green.

No UI code changes until step 1.
