# Profile photo + What\'s New + Version

## Profile photo fix
- `init_db()` now runs `ensure_schema_patches()` so `avatar_mime` / `avatar_data` are added on existing DBs
- Profile page reloads avatar from DB and shows real error messages if save fails

## What\'s New page
- Sidebar: **✨ What\'s New**
- Lists v2.2.0 and earlier highlights

## Version
- `APP_VERSION = "2.2.0"` in `config.py`
- Shown on Profile caption, Settings → Application information, What\'s New header
