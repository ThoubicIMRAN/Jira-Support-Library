# 20-Point Launch Checklist — Jira Support Library

Adapted for an **internal Streamlit app** (not a public marketing site).

| # | Item | Status | How addressed |
|---|------|--------|----------------|
| 1 | Privacy policy | **Done** | `views/legal.py` · login footer · signed-in Support/legal |
| 2 | Terms and conditions | **Done** | Same legal view, Terms tab |
| 3 | Secrets off front end | **Done** | Env-only secrets; Fernet for Jira/SMTP; no API keys in client JS |
| 4 | Force HTTPS | **Done (ops)** | `docs/DEPLOY.md` · Docker binds localhost · `FORCE_HTTPS` + Secure cookie |
| 5 | Cookie consent | **Done** | Session notice on login (`components/cookie_notice.py`) |
| 6 | Meta titles / descriptions | **Done** | `st.set_page_config(page_title=APP_NAME)` · brand subtitle in chrome |
| 7 | Social preview image | **N/A / optional** | Internal app; add OG tags at reverse proxy if ever public |
| 8 | Favicon | **Done** | Streamlit `page_icon` (🎯); replace with `static/favicon.png` if desired |
| 9 | Sitemap + robots.txt | **Done** | `static/robots.txt` → `Disallow: /` (do not index internal app) |
| 10 | Image alt text | **Partial** | Avatars/uploads are user content; Streamlit limits DOM control |
| 11 | Compress images | **Done** | Avatar max size; attachment size + type checks |
| 12 | Page load speed | **Ongoing** | Cached bootstrap; keep Ollama internal; reverse proxy caching optional |
| 13 | Colour contrast | **Done** | Design tokens in `.streamlit/config.toml` + `assets/styles.css` |
| 14 | Mobile friendly | **Done** | Streamlit wide layout + responsive columns |
| 15 | Custom 404 | **Done** | App error boundary + “Back to Home”; unknown pages → Home |
| 16 | Broken links | **Done** | In-app `goto()` navigation; no public link graph |
| 17 | Form validation | **Done** | Login/signup/reset + server-side account/Jira validation |
| 18 | Spam / bot protection | **Done** | Login lockout, rate limits, XSRF on Streamlit server |
| 19 | Analytics | **Optional** | Streamlit `gatherUsageStats = false`; enable org analytics at proxy if needed |
| 20 | Clear CTA | **Done** | Login hero + primary **Sign in**; post-login Home / My Dashboard |

## Before go-live
1. Set production secrets and `APP_URL=https://…`
2. Terminate TLS on Caddy/Nginx (`docs/DEPLOY.md`)
3. Confirm privacy/terms links on the login page
4. Run `pytest` and CI green on the release branch
