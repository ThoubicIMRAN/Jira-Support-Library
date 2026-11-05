# Security audit — fixes and residual risks

## Fixed in this change set
| Area | Fix |
|---|---|
| Jira attachments (HTTP 415) | The session default `Content-Type: application/json` blocked the multipart boundary. The upload now removes it for that call and guesses the file MIME type. Regression tests cover multipart and JSON requests. |
| Authorisation in services | `admin_set_password` and `delete_user` require a superadmin actor; `unlock_account` requires admin or superadmin. UI buttons are no longer the only gate. |
| Rate limiting | Jira writes (comment, attachment, worklog, transition, watchers), bulk runs, AI generation, content writes, password set and user delete are limited. `RateLimitExceeded` is a `ValueError` so users see "Too many attempts". A test fails if a listed write function loses its limiter. |
| Avatars | The real format is detected from the bytes (browser MIME ignored), decoded, size/pixel limited, re-encoded as a 256×256 PNG without metadata. Only `https://` external avatar URLs are rendered; initials are HTML-escaped. |
| Error handling | `utils/errors.py`: `safe_message()` shows validation messages only and logs unexpected errors with a reference code; `log_ignored()` replaces silent `except: pass`. A test forbids both patterns. |
| JQL | Identifiers validated; string literals escaped (backslash and quote). |
| Embeddings | At most 8 new embeddings per ticket load. |
| Audit log | The `create_category` audit row was written outside the transaction and lost; it is now committed with the change. |
| Repository hygiene | Removed orphan `views/admin_center.py` and its components, duplicate root workflow files and a stray pack. Tests now fail on missing or unimportable modules, committed patch scripts and large encoded blobs. |
| Config | `enableXsrfProtection` is explicit. `Pillow` added to requirements. |

## Residual risks (not changed here)
| Risk | Why | Recommended action |
|---|---|---|
| Session cookie is set from JavaScript, so it is not `HttpOnly` | Streamlit cannot set cookies server-side | Keep sessions short, serve over HTTPS only, add a strict reverse-proxy CSP, consider an OIDC/SSO front door |
| Rate limiter is in-process | Counters are per worker | Use Redis if you run more than one replica |
| Unpinned dependencies | `requirements.txt` uses ranges | Generate a hashed lock file (`pip-compile --generate-hashes`) |
| Category names are unique per project | Prevents the same sub-category name under two parents | Migrate the constraint to `(project_id, parent_id, name)` |
| App listens on plain HTTP | Compose binds to 127.0.0.1 | Put nginx/Traefik with TLS in front; never expose 8501 publicly |
| Rebuild required | New dependency (Pillow) | `docker compose build --no-cache app` |
