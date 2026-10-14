# Jira Support Library

Internal Streamlit app for reusable Jira/IT-support responses. UI follows the **Jira Command Library** prototype.

## Run
```bash
cp .env.example .env            # set APP_SECRET_KEY and BOOTSTRAP_ADMIN_PASSWORD
pip install -r requirements.txt
streamlit run app.py
```
Docker: `docker compose up -d --build`. First sign-in uses `BOOTSTRAP_ADMIN_USERNAME` (default `admin`) and `BOOTSTRAP_ADMIN_PASSWORD`; you are forced to change it. The app starts **empty**: add projects in Admin Settings, then add or import responses (format: `docs/import-format.md`). Docker Compose has no default credentials; set `POSTGRES_PASSWORD` and `DATABASE_URL` in `.env`.

## Design system (single source of truth)
| Layer | File | Role |
|---|---|---|
| Static components | `assets/styles.css` | Reads tokens only; no hard-coded colours |
| Per-user tokens | `services/preference_service.py` | Light / dark / system, accent, radius, density |
| Native theme | `.streamlit/config.toml` | Prototype light palette, fonts, sidebar |
| UI blocks | `components/cards.py` | Hero, project card, response card, headers |
| Fonts | `static/fonts/` | Syne, DM Sans, IBM Plex Mono — self-hosted (SIL OFL), no CDN |

Rule: a stylesheet must not contain the `<` character (the HTML sanitiser drops the whole sheet). `tests/test_theme.py` enforces this.

## Features
- **Roles:** `user` (view/copy/AI, submits AI text for approval) · `manager` (+create/edit/duplicate, saves to library, approves AI) · `admin` (+import/delete/manage content) · `superadmin` (all, plus user create/role/reset-password/delete).
- **Jira integration** (`services/jira_*.py`, `views/jira_*.py`): per-user Cloud API token or Server PAT (Fernet-encrypted), library project → Jira key links, transition aliases, and the 🎫 dialog on each response (comment with reporter swap, log time, transition). Configure `JIRA_BASE_URL` (HTTPS in production). Set the connection under Personal settings; link projects and aliases under Admin Settings.
- **AI approval:** AI-generated text from `user` role goes to a pending queue; managers/admins approve or reject (checked server-side).
- **Bulk comment** (`services/bulk_comment.py`, `views/bulk_jira.py`): 📣 button on the project page. One Jira project per run, hard cap `BULK_MAX_TICKETS` (25), pause between posts, explicit confirmation, aborts on auth failure, per-ticket reporter/summary placeholders. Every run is stored in the **bulk log** (own history in the dialog; all users under Admin Settings → Audit & logs).
- **Ticket placeholders** in any response: `@TICKET @SUMMARY @ASSIGNEE @PROJECT @STATUS` (filled from the loaded ticket; left visible if no ticket is loaded) plus `@NAME @DESIGNATION @ROLE @R @DATE`.
- **Confluence** (`services/confluence_*.py`): per-user PAT, resolution notes from a page link. The host is locked to `CONFLUENCE_BASE_URL`; links on other hosts are rejected.
- **Attachments**: png/jpg/gif/webp/pdf/txt/log only, size-limited (`JIRA_MAX_ATTACHMENT_MB`), file signature checked.
- **Project access**: `user` and `manager` see only assigned projects (Admin → Content & users → Project access). Enforced on Home, project pages, search, favorites, notifications, AI and in the content service. Admins see all.
- New tables are created automatically by `init_db()` (`create_all`); there are no Alembic revisions in this repo yet.

## Security notes
- Production requires `APP_SECRET_KEY`; `FORCE_RESET_ADMIN_PASSWORD` is ignored in production.
- RBAC is enforced in `services/content_service.py`, not only in the UI.
- Run behind HTTPS (Nginx). Session cookie is JS-set (Streamlit limitation), so it cannot be HttpOnly.
- Never commit `.env` or `data/*.db`.

## Tests
```bash
pip install -r requirements-dev.txt && python -m pytest -q
```
