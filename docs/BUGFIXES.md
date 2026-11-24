# Bug fixes

Track **fixes only** here (no feature blurbs). Newest version first.

Update this file on **every release** together with `docs/releases.json`, `CHANGELOG.md`, and the in-app What's New page (loads `docs/releases.json`).

See also: [RELEASE_PROCESS.md](RELEASE_PROCESS.md) · [CHANGELOG.md](../CHANGELOG.md)

---

## 2.6.0 — 2026-11-23

- Delete-category confirmation never appeared (dialog decorators were swapped)
- New projects were audited with entity id None; project-access user picker reset on every refresh
- Deleting a tag now removes its response links; tag names are escaped and colours validated before rendering
- My Dashboard: missing plotly dependency declared; 'include unassigned' now supported by the queue query
- Profile screens no longer show raw exception text
- Create-account screen now uses the existing registration service with rate limit and email-domain check, and is off by default in production (ALLOW_SELF_REGISTRATION)
- Passkeys now switch themselves off in production until WEBAUTHN_RP_ID is set to the real hostname, instead of failing silently

## 2.5.3 — 2026-11-17

- Jira dialog: stopped using the streamlit module as a column context manager

## 2.5.1 — 2026-11-15

- Fixed a Jira dialog regression introduced in 2.5.0

## 2.4.0 — 2026-11-09

- Restored views/my_dashboard.py after a bad merge replaced it with a placeholder
- Replaced silent except/pass in My Dashboard with logged errors

## 2.3.0 — 2026-11-05

- Restored Jira action dialog after regression (template fields, module integrity).
- Restored `views/my_dashboard.py` after a bad merge replaced it with a PLACEHOLDER string.
- Replaced silent `except: pass` in dashboard paths with `log_ignored` so CI stays green.
- CI: enforce no silent except/pass and no raw exception text in the UI.

## 2.2.0 — 2026-10-29

- Login rate-limit and password policy edge cases for production deployments.
- Avatar upload validation edge cases (MIME vs real bytes).

## 2.1.0 — 2026-10-01

- Initial tracked baseline (library + Jira/Confluence core). No separate fix list recorded.
