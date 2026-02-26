# Quality Audit UI — Design Tokens & Handoff

Single reference for theme tuning and future web/port. All values live in `styles.py`; this doc summarizes them for handoff.

## Colors (semantic)

| Token | Hex | Usage |
|-------|-----|--------|
| bg_primary (surface) | `#121212` | Main window |
| bg_secondary (surface_raised) | `#1a1a2e` | Panels, inputs |
| bg_tertiary (surface_raised_high) | `#252538` | Headers, list headers |
| text_primary | `#f5f5f5` | Body text |
| text_secondary | `#a0a0b0` | Labels, secondary |
| text_muted | `#6b6b80` | Placeholders, disabled |
| accent | `#00338D` | KPMG blue — CTAs, focus |
| accent_hover | `#002366` | Hover on accent |
| success | `#0d9488` | Success state |
| warning | `#d97706` | Warning state |
| error | `#dc2626` | Error state |
| border | `#3f3f50` | Borders, dividers |
| select_bg | `#1e3a5f` | Selected row/item |

Contrast: text_primary/secondary on bg_primary ≥ 4.5:1 (WCAG AA); large text ≥ 3:1.

## Spacing (8pt grid)

| Token | px | Use |
|-------|-----|-----|
| xs | 4 | Tight inline |
| sm | 8 | Row gap, inner padding |
| md | 12 | Medium gap |
| base | 16 | Section padx/pady, default |
| lg | 24 | Section padding (larger) |
| xl | 32 | Between major blocks |
| xxl | 48 | Large sections |

Section padding: `PADDING_SECTION` = 16; inner row gap: `PADDING_INNER` = 8.

## Typography

| Token | Font | Size | Use |
|-------|------|------|-----|
| caption | Segoe UI | 9 | Small labels, hints |
| body / ui | Segoe UI | 10 | Default labels, buttons |
| heading | Segoe UI | 11 | Section titles (LabelFrame) |
| monospace | Consolas | 11 | Command preview |
| log | Consolas | 10 | Log output |

Tk does not expose line-height; use same font/size for consistent line spacing. Commercial: Segoe UI Semibold for section titles optional; prefer consistency and readability.

## Breakpoints (view modes)

| Mode | Width | Behavior |
|------|--------|----------|
| compact | &lt; 1280 px | Optional: hide banner by default, shorter labels |
| full | ≥ 1280 px | Show banner if user expanded; full labels |

Use `winfo_width()` on the main window to switch; see `styles.VIEW_MODES`.

## Min resolution (1366×768)

- **Left panel:** Paths, Options, Tax Rate, Command Preview are inside a **scrollable canvas**; Run/Cancel bar is **sticky** at the bottom so RUN is always visible and clickable.
- **Mouse:** Scroll wheel (Windows/macOS) or Button-4/5 (Linux) over the left content area to scroll.
- Layout checked at 1366×768; no clipped RUN button or Individual file list.

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+Enter | Run audit |
| F5 | Rescan input path |
| Ctrl+L | Clear log |
| (Tab) | Move focus: Paths → Options → Tax Rate → Command Preview → Run |

Document in Help menu or tooltip so users can discover them.

## Application identity

- **Window title:** "Quality Audit — KPMG style" (or "Quality Audit — CLI runner"); keep consistent in dialogs.
- **Window / taskbar icon:** `.ico` loaded from (in order): `quality_audit/ui/icon.ico`, tool root `icon.ico`, tool root `assets/icon.ico`. If none found, fallback to default. Document icon path for packaging.

## Empty state & onboarding

- **Summary empty state:** When no run has completed, show 3-step guidance at top (F-pattern): (1) Chọn thư mục input/output, (2) Kiểm tra thuế nếu cần, (3) Bấm Run. Then "No run yet. Summary will appear here after RUN."
- **First-run Quick start:** One-time dialog or collapsible "Quick start" (3 steps + "Don't show again"); persisted as `quick_start_seen` in settings.
- **First-time tip:** On first focus of Input path, status bar shows once: "Tip: Ctrl+Enter = Run, F5 = Rescan"; persisted as `input_tip_shown`.

## Last error & feedback

- **Last error:** After each `messagebox.showerror`, store message and show in a dedicated "Last error" line (one line) with optional Clear (and Copy). User can refer back after closing the dialog.
- **Running phases:** Status bar shows "Preparing…" then "Running…" (or "Scanning…", "Validating…", "Writing…" if backend exposes phases).
- **Run completed:** On success, status bar shows "Run completed successfully" in success color for ~1.5 s, then "Done — N files" with success color (micro-interaction per frontend-design).
- **Preferences saved:** When saving settings (e.g. banner collapsed), status bar shows "Preferences saved" for ~2 s, then restores previous message.

## Help → About

- **About Quality Audit:** Version from `quality_audit.__version__`, optional build/date; sentence that settings are saved automatically; docs/support: "Xem README trong thư mục dự án."

## GUI section labels (user-facing)

Left panel sections: **1. Paths** (Input folder, Output folder, Previous run), **2. Options** (Cache size, Log level), **3. Tax Rate** (Default rate %, Set all), **4. Command Preview**. Run bar is below a horizontal separator. Status bar shows one-line summary on completion (e.g. "Done — N files", "Failed — see Terminal Output").

## Pre-delivery checklist (Tk)

- [ ] Tokens (color, spacing, font) defined in `styles.py` and summarized in this file.
- [ ] Contrast text/background meets WCAG AA (4.5:1 small text, 3:1 large).
- [ ] Every clickable control has cursor or visual feedback (e.g. `cursor="hand2"` on buttons).
- [ ] Tab order and shortcuts (Ctrl+Enter, F5, Ctrl+L) documented and exposed (Help/tooltip).
- [ ] No emoji as functional icons; use text (e.g. "Rescan") or consistent symbol (e.g. "●" for status only).
- [ ] Window min size and sash clamp set; layout checked at 1366×768 (left panel scroll + sticky Run bar).

## Handoff for web/other UI

- Export `COLORS` as CSS variables or theme JSON.
- Map `SPACING` to spacing scale (e.g. 4/8/12/16/24/32/48 px).
- Map `FONTS` to font-family + font-size; add line-height in CSS.
- Use same semantic names (surface, text_primary, accent, etc.) for consistency.
