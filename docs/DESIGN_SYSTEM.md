# Design system

Single visual language for the Jira Support Library. All screens consume these tokens and components. Do not invent page-specific colours, fonts, or one-off styles.

## Brand

| Role                       | Value                             | Notes                        |
| -------------------------- | --------------------------------- | ---------------------------- |
| Primary                    | `#099EE0`                         | Buttons, links, focus, chips |
| Navigation                 | `#0c1f6e` / `#0a1a5c`             | Sidebar (`--sb`, `--sb2`)    |
| Background                 | `#f0f4fb`                         | App canvas (`--bg`)          |
| Surface                    | `#ffffff`                         | Cards, dialogs (`--bg2`)     |
| Text                       | `#111827` / `#4b5675` / `#8898b8` | Primary / secondary / muted  |
| Success / danger / warning | `#10b981` / `#ef4444` / `#f59e0b` | Status only                  |

Dark theme tokens live in `services/preference_service.py` (`DARK_TOKENS`). Users may override accent; invalid values fall back to the brand primary.

## Typography

| Role               | Family                                                       | Source                      |
| ------------------ | ------------------------------------------------------------ | --------------------------- |
| Display / headings | Syne                                                         | Self-hosted `static/fonts/` |
| Body               | DM Sans (default), or Segoe UI / Arial / … from allowed list | Preference                  |
| Code               | IBM Plex Mono                                                | Self-hosted                 |

Do not put emoji in page titles, tab labels, or primary buttons. Icons are optional on `page_header` for backward compatibility; new screens omit them.

## Spacing and shape

- Radius: user preference (`border_radius`, default 8px) → `--rc`, `--r`, `--r2`
- Density padding: compact / comfortable / spacious → `--density-pad`
- Shadows: `--sh`, `--sh2` only — no extra elevations
- Focus: `:focus-visible` outline using `--accent`

## CSS rules

- Source of truth: `assets/styles.css` (tokens only; no hard-coded surfaces for new work)
- Per-user overrides: `preference_service.preference_css()`
- **The stylesheet must not contain the character `<`** (DOMPurify drops the sheet)

## Shared components (`components/cards.py`)

| Function                                                              | Use                                             |
| --------------------------------------------------------------------- | ----------------------------------------------- |
| `page_header(title, subtitle=None, icon=None)`                        | Every page top                                  |
| `section_header(title, count=None, color=None)`                       | Category / section bars                         |
| `empty_state(icon, title, hint=None)`                                 | No data; `icon` optional                        |
| `status_badge(label, tone=…)` / `render_status_badge`                 | neutral \| info \| success \| warning \| danger |
| `notice(message, level=…)`                                            | Inline info / success / warning / danger strip  |
| `help_text(text)`                                                     | Short guidance under a control                  |
| `hero_banner`, `project_card`, `response_card_header`, `preview_text` | Existing library surfaces                       |
| `safe_color`, `safe_key`, `accent_scope`                              | Safe dynamic colour / keys                      |

## Page structure (required for new or redesigned screens)

1. Breadcrumb (shell)
2. `page_header` — title + one-line description
3. One primary action
4. Search / filters when relevant
5. Main content
6. `help_text` or expander for non-obvious rules
7. Empty / loading / error via shared patterns (`empty_state`, `notice`, `safe_message`)

## Feedback

- Success / failure: show what happened; no optimistic “done” before completion
- Errors: use `utils.errors.safe_message`; never raw exceptions
- Toasts: `utils.layout.flash` / `show_flash` (survives one rerun)

## Accessibility

- Contrast: default and high-contrast preference paths
- Visible focus ring on interactive controls
- Do not convey status by colour alone — pair with text (`status_badge` label)
- Meaningful labels on inputs; keyboard-reachable Streamlit controls

## Out of scope for this system

Gradients as decoration, glassmorphism, glowing accents, oversized marketing cards, random per-page palettes, emoji navigation.
