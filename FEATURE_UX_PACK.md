# Feature pack: User / Category / Compact Jira / Multi-step / My Dashboard

## Avatars & admin user edit
- `User.avatar_mime` + `User.avatar_data` (BYTEA), max 500 KB PNG/JPEG/WebP
- `services/avatar_service.py`, profile upload, admin profile edit via `admin_update_user`

## Categories
- `update_category()` rename, parent, sort_order — inline expander in admin

## Jira dialog
- Reporter / Assignee / Status row; validator field; multi-select transitions
- `jira_service.multi_step_transition()`

## My Dashboard
- Page **My Dashboard** — JQL `assignee = currentUser() AND resolution = Unresolved`
- Charts: project×status; due-date buckets
- Queue grouped by project → issue type

## Security
- Rate limits (`services/rate_limit.py`), stronger passwords, production FERNET_KEY gate

## Deploy
```bash
python scripts/migrate_avatar.py
# ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime VARCHAR(64);
# ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data BYTEA;
```
