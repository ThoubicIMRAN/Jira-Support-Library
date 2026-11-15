# Bug fixes

Track **fixes only** here (no feature blurbs). Newest version first.

Update this file on **every release** together with `docs/releases.json`, `CHANGELOG.md`, and the in-app What's New page (loads `docs/releases.json`).

See also: [RELEASE_PROCESS.md](RELEASE_PROCESS.md) · [CHANGELOG.md](../CHANGELOG.md)

---

## 2.3.0 — 2026-11-02

- Restored Jira action dialog after regression (template fields, module integrity).
- Restored `views/my_dashboard.py` after a bad merge replaced it with a PLACEHOLDER string.
- Replaced silent `except: pass` in dashboard paths with `log_ignored` so CI stays green.
- CI: enforce no silent except/pass and no raw exception text in the UI.

## 2.2.0 — 2026-10-29

- Login rate-limit and password policy edge cases for production deployments.
- Avatar upload validation edge cases (MIME vs real bytes).

## 2.1.0 — 2026-10-01

- Initial tracked baseline (library + Jira/Confluence core). No separate fix list recorded.
