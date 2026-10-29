# Feature pack: User / Category / Compact Jira / Multi-step transitions

## 1. User management & avatars
- `User.avatar_mime` + `User.avatar_data` (BYTEA) — max 500 KB, PNG/JPEG/WebP
- `services/avatar_service.py` — set/clear/get/render
- Profile page: upload / remove photo
- Admin: edit full name, email, designation; set avatar; role/active via `admin_update_user` (RBAC)

## 2. Categories
- `update_category()` — rename, parent (nesting), sort_order
- Inline expander **Edit · {name}** on admin content categories tab

## 3. Jira dialog (compact)
- Reporter / Assignee / Status row (read-only)
- Mentions + **Validator / participant** field
- **Multi-select transitions** (order = execution order)
- `jira_service.multi_step_transition()` runs the chain server-side

## 4. Security
- Avatar type/size validation server-side
- Admin updates only via `admin_update_user` + superadmin role gates
- Existing rate limits on auth remain

## Deploy
```bash
python scripts/migrate_avatar.py   # or manual ALTER TABLE
# rebuild app image / restart
```


## 5. My Dashboard
- Page: **📊 My Dashboard** (`views/my_dashboard.py`)
- JQL: `assignee = currentUser() AND resolution = Unresolved`
- Charts: project × status bar chart; due-date buckets (Overdue / Today / 7 days / Later / None)
- Queue: grouped by **project → issue type**; 🎫 copies key for dialog prefill (`mq_prefill_ticket`)
- Rate limited via `limit_sensitive_api`
