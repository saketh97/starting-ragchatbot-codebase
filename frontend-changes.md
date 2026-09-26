# Frontend Changes: Light/Dark Theme Toggle

## `frontend/index.html`
- Added a `#themeToggle` button (sun + moon inline SVG icons) as the first child of `<body>`.
  - `role="switch"`, `aria-checked`, `aria-label="Toggle light theme"`, icons marked `aria-hidden`.
- Added a small inline `<script>` in `<head>` that sets `data-theme` on `<html>` from `localStorage` (falling back to the OS `prefers-color-scheme`) before first paint, avoiding a theme flash.
- Bumped asset cache-busting query strings to `?v=11`.

## `frontend/style.css`
- Added a `:root[data-theme="light"]` variable set (dark remains the default). New variables `--code-bg` and `--source-link-color` replace two hardcoded colours so they adapt per theme.
- `.theme-toggle`: fixed at top-right, 44px circular button using existing surface/border/primary/focus-ring tokens.
- Animation: sun and moon icons cross-fade with rotate + scale (0.4s); background/text/border colours across the app transition over 0.3s.
- Accessibility: visible `:focus-visible` ring; `prefers-reduced-motion` disables transitions.

## `frontend/script.js`
- Added `setupThemeToggle()`: toggles `data-theme` between `light`/`dark` on click, updates `aria-checked` and `title`, and persists the choice in `localStorage` (wrapped in try/catch).
- Keyboard: it's a native `<button>`, so Tab focuses it and Enter/Space activate it.

# Frontend Changes: Light Theme Refinement (accessibility)

## `frontend/style.css`
- Reworked `:root[data-theme="light"]` palette for WCAG AA:
  - Backgrounds: `--background #f1f5f9`, `--surface #ffffff`, `--surface-hover #e2e8f0`.
  - Text: `--text-primary #0f172a` (~17:1), `--text-secondary #475569` (~6–7:1).
  - Primary darkened to `#1d4ed8` (hover `#1e40af`); user-message bubbles use it with white text (6.7:1). Focus ring strengthened.
  - `--border-color #cbd5e1` for dividers; new `--input-border` (`#64748b`, 4.8:1) used on the chat input, suggested-question buttons and theme toggle so controls meet the 3:1 UI-component contrast. In dark theme it aliases `--border-color`.
- New variables `--error-text` / `--success-text` (darker `#b91c1c` / `#166534` in light) replace hardcoded light-on-dark colours in `.error-message` / `.success-message`.
- Light-only tweaks: assistant bubbles get a subtle border, source chips and error/success backgrounds use tints suited to a light surface.

## `frontend/index.html`
- Bumped stylesheet cache-buster to `?v=12`.

# Frontend Changes: Theme Switching Audit

Theme switching uses CSS custom properties, with a `data-theme` attribute on `<html>` (`script.js` `setupThemeToggle()`), as built above. This pass verified and closed gaps:

- `style.css`: fixed `.message-content blockquote` using an undefined `var(--primary)` (now `--primary-color`), so its border renders in both themes. Extended the 0.3s colour transition to code, pre, and blockquote elements.
- `script.js`: when no theme has been saved, the page now follows live OS `prefers-color-scheme` changes; an explicit toggle choice always wins.
- Remaining hardcoded colours are intentional and legible in both themes (white text on primary buttons, brand-blue tints, box-shadows).
- Cache-busters bumped to `?v=13`.
