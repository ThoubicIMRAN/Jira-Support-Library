# Jira Support Library

Internal Streamlit app for reusable Jira/IT-support responses. UI follows the **Jira Command Library** prototype.

**Release notes:** [CHANGELOG.md](CHANGELOG.md) · [docs/BUGFIXES.md](docs/BUGFIXES.md) · [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md) · in-app **What's New** (`docs/releases.json`).

## Run

```bash
cp .env.example .env            # set APP_SECRET_KEY and BOOTSTRAP_ADMIN_PASSWORD
pip install -r requirements.txt
streamlit run app.py
```

Docker: `docker compose up -d --build`. First sign-in uses `BOOTSTRAP_ADMIN_USERNAME` (default `admin`) and `BOOTSTRAP_ADMIN_PASSWORD`; you are forced to change it. The app starts **empty**: add projects in Admin Settings, then add or import responses (format: `docs/import-format.md`). Docker Compose has no default credentials; set `POSTGRES_PASSWORD` and `DATABASE_URL` in `.env`.

## Design system (single source of truth)

| Layer             | File                             | Role                                                         |
| ----------------- | -------------------------------- | ------------------------------------------------------------ |
| Static components | `assets/styles.css`              | Reads tokens only; no hard-coded colours                     |
| Per-user tokens   | `services/preference_service.py` | Light / dark / system, accent, radius, density               |
| Native theme      | `.streamlit/config.toml`         | Prototype light palette, fonts, sidebar                      |
| UI blocks         | `components/cards.py`            | Hero, project card, response card, headers                   |
| Fonts             | `static/fonts/`                  | Syne, DM Sans, IBM Plex Mono — self-hosted (SIL OFL), no CDN |

Rule: a stylesheet must not contain the `<` character (the HTML sanitiser drops the whole sheet). `tests/test_theme.py` enforces this.

## Features

- **Roles:** `user` (view/copy/AI, submits AI text for approval) · `manager` (+create/edit/duplicate, saves to library, approves AI) · `admin` (+import/delete/manage content) · `superadmin` (all, plus user create/role/reset-password/delete).
- **Jira integration** (`services/jira_*.py`, `views/jira_*.py`): per-user Cloud API token or Server PAT (Fernet-encrypted), library project → Jira key links, transition aliases, and the 🎫 dialog on each response (comment with reporter swap, log time, transition, people search, transition-chain presets). Configure `JIRA_BASE_URL` (HTTPS in production).
- **Jira dialog UX:** single-screen layout, reporter/assignee chips, placeholder & double-post guards, fillable `[bracket]` template fields.
- **My Dashboard / Queue:** open issues assigned to you, charts by project/status and due date, ticket pre-fill into the dialog.
- **AI approval:** AI-generated text from `user` role goes to a pending queue; managers/admins approve or reject (checked server-side).
- **Bulk comment** (`services/bulk_comment.py`, `views/bulk_jira.py`): 📣 on the project page, hard cap `BULK_MAX_TICKETS` (25), confirmation, bulk log under Admin → Audit & logs.
- **Ticket placeholders:** `@TICKET @SUMMARY @ASSIGNEE @PROJECT @STATUS` plus `@NAME @DESIGNATION @ROLE @R @DATE`.
- **Confluence** resolution notes from a page link (`CONFLUENCE_BASE_URL` host lock).
- **Attachments:** png/jpg/gif/webp/pdf/txt/log only, size-limited, signature checked.
- **Security:** service-layer RBAC, rate limits, session revoke on password/role change, Docker hardening. See [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md).
- **Project access:** `user` / `manager` see only assigned projects; enforced in UI and services. Admins assign access by user or by project and can copy one user's access to another (audited).
- **Admin area by role:** only `admin` / `superadmin` open Admin Settings; `superadmin` alone manages users and sees Health. Capabilities live in `auth.PERMISSIONS`.
- **App bar:** breadcrumb, library search on every page, notification badge, profile-photo account menu.
- **Passkeys (WebAuthn):** sign in with a security key or platform authenticator; see *Passkeys* below. In production they stay off until `WEBAUTHN_RP_ID` is set to the real hostname.
- **Remember me:** the sign-in checkbox keeps the session for `REMEMBER_ME_DAYS` (default 30); `REMEMBER_ME_IDLE_TIMEOUT_MINUTES` sets an optional idle timeout (0 = none).
- **Self-registration:** the public *Create an account* screen is controlled by `ALLOW_SELF_REGISTRATION` (default on in development, off in production); sign-ups are rate limited and follow the allowed-email-domain policy.
- **Error codes:** `JSL-*` catalogue in [docs/ERROR_CATALOGUE.md](docs/ERROR_CATALOGUE.md).
- **What's New:** in-app page driven by `docs/releases.json`. Bug fixes: [docs/BUGFIXES.md](docs/BUGFIXES.md). Full history: [CHANGELOG.md](CHANGELOG.md).
- **Privacy & Terms** and a first-visit session cookie notice (launch checklist).
- **CSV export** of project library responses (alongside JSON export).
- New tables are created automatically by `init_db()` (`create_all`); there are no Alembic revisions in this repo yet.

## Security notes

- Production requires `APP_SECRET_KEY`; `FORCE_RESET_ADMIN_PASSWORD` is ignored in production.
- RBAC is enforced in `services/content_service.py`, not only in the UI.
- Run behind HTTPS (Nginx). Session cookie is JS-set (Streamlit limitation), so it cannot be HttpOnly.
- Never commit `.env` or `data/*.db`.

### Passkeys

Users can add and remove passkeys under **Profile → Sign-in methods**. After adding a passkey, **Passkey** is available on the sign-in page. Passkeys require HTTPS (except localhost development) and correct relying-party settings: set `WEBAUTHN_RP_ID` to the public hostname and `WEBAUTHN_ORIGIN` to the exact public origin, including scheme and port if non-default. `WEBAUTHN_ENABLED=false` disables enrollment and passkey sign-in. Users cannot remove their last available sign-in method.

## Tests

```bash
pip install -r requirements-dev.txt && python -m pytest -q
```

## Docker image (GitHub Container Registry)

GitHub Actions (`.github/workflows/ci-docker.yml`) lints and tests every push, then builds and publishes the image to
`ghcr.io/<owner>/<repo>`. Pull requests build but do not push.

| Tag                 | Updated when          | Intended use          |
| ------------------- | --------------------- | --------------------- |
| `stable` / `latest` | Git tag `vX.Y.Z` only | Production (default)  |
| `main` / `edge`     | Every push to `main`  | Testing / staging     |
| `vX.Y.Z` / `X.Y`    | Matching git tag      | Explicit version pin  |
| `sha-…`             | Every build           | Exact reproducibility |

Run the published **stable** image instead of building locally:

```bash
echo YOUR_PAT | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin   # PAT with read:packages (private images only)
# in .env:  APP_IMAGE=ghcr.io/<owner>/<repo>:stable
docker compose pull app && docker compose up -d
```

To try the tip of main (testing only):

```bash
# APP_IMAGE=ghcr.io/<owner>/<repo>:main
```

The image contains no configuration, secrets or data: everything comes from `.env` and the database volume at runtime.
