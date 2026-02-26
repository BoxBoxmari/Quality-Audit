# KPMG Brand Guidelines — Quality Audit UI

Brand and design tokens for the Quality Audit desktop GUI, aligned with KPMG visual identity (professional, audit, trust).

## Primary Palette

| Token        | Hex       | Usage                          |
|-------------|-----------|---------------------------------|
| primary     | `#00338D` | KPMG blue — accent, CTAs, focus |
| primary_dark| `#002366` | Hover/pressed primary           |
| white       | `#FFFFFF` | Text on primary, highlights     |
| black       | `#121212` | Dark mode background (not pure black) |

## Semantic Colors (Dark Theme)

| Token         | Hex       | Usage                    |
|---------------|-----------|--------------------------|
| bg_primary    | `#121212` | Main window background   |
| bg_secondary  | `#1a1a2e` | Panels, inputs           |
| bg_tertiary   | `#252538` | Headers, list headers    |
| text_primary  | `#f5f5f5` | Body text (off-white)    |
| text_secondary| `#a0a0b0` | Labels, secondary text   |
| text_muted    | `#6b6b80` | Placeholders, disabled   |
| accent        | `#00338D` | KPMG blue — links, focus, primary actions |
| success       | `#0d9488` | Success state            |
| warning       | `#d97706` | Warning state            |
| error         | `#dc2626` | Error state              |
| border        | `#3f3f50` | Borders, dividers        |
| select_bg     | `#1e3a5f` | Selected item (blue tint)|

## Typography

- **Scale (styles.py):** caption 9pt, body 10pt, heading 11pt; monospace/log for terminal and command preview.
- **UI (headings, labels):** Segoe UI 10 — system clean sans; alternative for non-Windows: system default sans.
- **Monospace (log, command):** Consolas 11 — keep for terminal/log readability.
- **Scale range:** 8, 9, 10, 11, 12 pt used; no generic “slop” fonts (per ui-ux-designer).

## Spacing (8pt Grid)

- **Base unit:** 8px.
- **Tokens:** 4, 8, 12, 16, 24, 32, 48, 64 (px).
- **Padding (panels):** 10–16 px (mapped to 8pt grid where possible).

## Accessibility

- Contrast: text on bg ≥ 4.5:1 (WCAG AA); large text ≥ 3:1.
- Focus: visible focus (accent color); logical tab order.
- No color-only state: success/warning/error use color + text/label.

## Usage in Code

- Prefer tokens from `styles.COLORS` and `styles.FONTS`; add `styles.SPACING` if needed.
- **Window title:** “Quality Audit — KPMG style” (or “— CLI runner”); consistent in all dialogs.
- **Window / taskbar icon:** Load .ico from (in order): quality_audit/ui/icon.ico, tool root icon.ico, tool root ssets/icon.ico. Document path for packaging.
- No emoji as icons; use text or ASCII where needed.
- Banner/collapsible: keep; accent color for banner text = KPMG blue.
- **About:** Help → About shows `__version__`, note that settings are saved automatically, and README path for docs/support.
- **Onboarding:** Quick start (3 steps) once; "Last error" line after messagebox errors; "Preferences saved" in status bar when settings change.

## Breakpoints (Desktop)

- **Compact / full:** One mode switch at 1280px width (`VIEW_MODES` in styles.py). Use `winfo_width()` to collapse banner or shorten labels when narrow.
- **Min resolution 1366×768:** Left panel content (Paths, Options, Tax, Command Preview) is scrollable; Run/Cancel bar is sticky at bottom so RUN is always visible.

## Token & Handoff Reference

- **reference.md** in this folder: color, spacing, typography tokens, keyboard shortcuts (Ctrl+Enter, F5, Ctrl+L), tab order, and pre-delivery checklist. Use for theming or for a future web UI.

## Pre-delivery checklist (Tk)

- [ ] Tokens (color, spacing, font) documented in styles.py and reference.md.
- [ ] Contrast text/background meets WCAG AA (4.5:1 small text, 3:1 large).
- [ ] All clickable controls have cursor or visual feedback (hand2 on buttons).
- [ ] Tab order and shortcuts (Ctrl+Enter, F5, Ctrl+L) documented in Help and reference.md.
- [ ] No emoji as functional icons (use text e.g. “Rescan”; status dot “●” allowed if consistent).
- [ ] Window min size and sash clamp checked at 1366×768; left panel scroll + sticky Run; no clipped content.

## References

- KPMG visual identity (primary blue) used for accent and focus only; not an official KPMG asset.
- UI design system: see `.cursor/skills/ui-design-system`; UX: `ui-ux-designer`, `ui-ux-pro-max`.
- Token handoff: `quality_audit/ui/reference.md`.
