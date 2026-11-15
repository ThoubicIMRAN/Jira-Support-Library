# Changelog

All notable changes to **Jira Support Library** are documented here.

Format inspired by [Keep a Changelog](https://keepachangelog.com/).
Versions align with `APP_VERSION` in `config.py` and the in-app **What's New** page (`docs/releases.json`).

**On every release, update:**
1. `docs/releases.json` (source of truth for the app)
2. This file (`CHANGELOG.md`)
3. `docs/BUGFIXES.md` (fixes only)
4. `config.py` → `APP_VERSION`
5. `README.md` Features section if user-facing capabilities changed

---

## [2.3.0] — 2026-11-02

### Added
- Security hardening (H1–H5): CI APPLY-script guard, service-layer RBAC, rate limits, session revoke, Docker binding.
- Jira dialog Package 2: single-screen layout, people search, reporter/assignee chips, safety guards.
- Transition chains Package 3: admin multi-step presets in the dialog.
- My Queue / dashboard charts and ticket pre-fill into the dialog.
- Semantic near-duplicates and ranked library suggestions.

### Fixed
- Jira dialog and My Dashboard regressions on main.
- Silent exception swallowing in dashboard code paths.

### Security
- Rate limits on Jira write, bulk, AI, and avatar paths.
- Sessions revoked after password or role changes.

## [2.2.0] — 2026-10-29

### Added
- My Dashboard (assigned open issues, charts).
- Profile avatars and admin user edit.
- Multi-step transitions and richer dialog ticket row.
- Stronger login rate limits and password policy.

### Fixed
- Production password / rate-limit edge cases.

## [2.1.0] — 2026-10-01

### Added
- Command library (projects, categories, responses, AI approval).
- Per-user Jira credentials, comment / time / transition dialog.
- Template fields, mentions → watchers, Confluence notes, bulk comment, health checks.
