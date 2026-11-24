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

## [2.6.0] — 2026-11-23

### Added

- Passkey sign-in (WebAuthn / FIDO2) — add and remove passkeys under Profile → Sign-in methods; sign in with a security key or platform authenticator
- Remember me on sign-in — stay signed in on a trusted device for REMEMBER_ME_DAYS (default 30), with an optional separate idle timeout
- New app bar — clickable breadcrumb, library search on every page, notification badge, and your profile photo as the account menu
- Admin by role — admin tabs and Admin Settings sections now follow your role; admins see users read-only, only superadmins manage users and Health
- Project access — assign by user or by project, copy one user's access to another (audited)
- Home — sort libraries by order, name, responses or categories; honours your card-column setting; project initials instead of emoji
- Redesigned sign-in, create-account, notifications, support, settings and profile screens; consistent icons and compact sidebar
- Error catalogue (JSL-*) — support-friendly error codes with reference ids
- Design system, Privacy Policy and User Notice documents

### Fixed

- Delete-category confirmation never appeared (dialog decorators were swapped)
- New projects were audited with entity id None; project-access user picker reset on every refresh
- Deleting a tag now removes its response links; tag names are escaped and colours validated before rendering
- My Dashboard: missing plotly dependency declared; 'include unassigned' now supported by the queue query
- Profile screens no longer show raw exception text
- Create-account screen now uses the existing registration service with rate limit and email-domain check, and is off by default in production (ALLOW_SELF_REGISTRATION)
- Passkeys now switch themselves off in production until WEBAUTHN_RP_ID is set to the real hostname, instead of failing silently

### Security

- Self-registration disabled by default in production; sign-up is rate limited and honours the allowed-email-domain policy
- Passkey registration and sign-in verify relying-party ID and origin (WEBAUTHN_RP_ID / WEBAUTHN_ORIGIN)
- Remembered sessions are revocable like any other session and never extend past REMEMBER_ME_DAYS

## [2.5.3] — 2026-11-17

### Fixed

- Jira dialog: stopped using the streamlit module as a column context manager

## [2.5.2] — 2026-11-15

### Added

- What's New is now driven by docs/releases.json
- Privacy and Terms pages and a first-visit cookie notice
- CSV export helpers for project library responses
- Release process documented (docs/RELEASE_PROCESS.md)

## [2.5.1] — 2026-11-15

### Fixed

- Fixed a Jira dialog regression introduced in 2.5.0

## [2.5.0] — 2026-11-09

### Added

- Jira dialog: fillable [bracket] template fields and a smaller dialog

## [2.4.0] — 2026-11-09

### Added

- My Dashboard: improved issue management

### Fixed

- Restored views/my_dashboard.py after a bad merge replaced it with a placeholder
- Replaced silent except/pass in My Dashboard with logged errors

## [2.3.0] — 2026-11-05

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
