# Security Audit Report — Jira Support Library

**Date:** 2026-10-29  
**Scope:** Streamlit monolith (`app.py`), auth/session, Jira/Confluence credential storage, Docker deploy  
**Classification:** Internal / production hardening

---

## 1. Executive Summary

The application is a **Streamlit multi-page app** (not a classic REST API). Authentication uses **server-side sessions** (opaque tokens hashed at rest) with **RBAC** by role. Jira/Confluence/SMTP secrets are **Fernet-encrypted** in Postgres.

**Initial posture:** Reasonable foundation for an internal tools app (bcrypt passwords, locked login attempts, encrypted third-party tokens, production refusal of empty `APP_SECRET_KEY`).  

**Major residual risks** come from Streamlit architecture (session cookie set via JS → **not HttpOnly**), historical missing rate limits (now added), weak default Docker passwords, published Ollama port, and password policy that only required length ≥ 8 (now strengthened).

This pass implements: in-process rate limiting on login/signup/reset, stronger password rules, stricter production config validation, and safer compose defaults.

---

## 2. Vulnerability Audit Report

### Critical

| ID | Issue | Location | Risk |
|----|--------|----------|------|
| C1 | Default compose DB password `StrongPassword123` | `docker-compose.yml` | Trivial DB compromise if `.env` omitted |
| C2 | Session token written via `document.cookie` (no HttpOnly) | `services/cookie_service.py` | XSS in any injected script can steal session |

### High

| ID | Issue | Location | Risk |
|----|--------|----------|------|
| H1 | No rate limit on login/signup/reset (pre-fix) | `auth.py`, `views/login.py` | Brute-force / credential stuffing |
| H2 | Weak password rule (length only) (pre-fix) | `utils/validators.py` | Easy-to-guess passwords |
| H3 | Ollama port `11434` published on host | `docker-compose.yml` | Unauthenticated model API on network |
| H4 | `ALLOW_URL_SESSION` can put token in query string | `cookie_service.py` / config | Token leakage via logs/Referer |

### Medium

| ID | Issue | Location | Risk |
|----|--------|----------|------|
| M1 | FERNET_KEY optional (derived from APP_SECRET_KEY) | `utils/security.py` | Key rotation complexity |
| M2 | Jira email stored plaintext | `user_jira_credentials.email` | PII in DB dumps |
| M3 | In-memory rate limit not shared across replicas | `services/rate_limit.py` | Limits weaker under horizontal scale |
| M4 | Username enumeration timing | `auth.authenticate` | Minor info leak |

### Already in good shape

- SQLAlchemy ORM parameterized queries
- Bcrypt password hashing
- Session tokens stored as SHA-256 hashes only
- Login lockout via `LoginAttempt`
- Production raises if `APP_SECRET_KEY` missing
- Seed data disabled unless `ALLOW_SEED_DATA=true`
- Page RBAC via `_can_open` / `allowed()`
- Jira API token encrypted with Fernet before DB write

---

## 3. Fixes Applied

| Fix | File |
|-----|------|
| Sliding-window rate limit (login / signup / reset) | `services/rate_limit.py` |
| `authenticate(..., client_ip=)` + rate limit | `auth.py` |
| Login/signup/reset call rate limits | `views/login.py` |
| Password: upper + lower + digit, 8–128 | `utils/validators.py` |
| Production requires `FERNET_KEY`; blocks `ALLOW_URL_SESSION`; rejects default DB password | `config.py` |
| Compose requires explicit passwords; Ollama port not published | `docker-compose.yml` |

### Cookie / XSS residual (Streamlit limitation)

True **HttpOnly** session cookies require a reverse proxy or custom auth gateway. Mitigate with HTTPS, CSP at proxy, and no untrusted HTML.

---

## 4. Production checklist

- [ ] `APP_ENV=production`
- [ ] Strong `APP_SECRET_KEY` + dedicated `FERNET_KEY`
- [ ] No `ALLOW_URL_SESSION` / no `ALLOW_SEED_DATA`
- [ ] Strong `POSTGRES_PASSWORD` / `DATABASE_URL`
- [ ] `APP_URL` and `JIRA_BASE_URL` are HTTPS
- [ ] Ollama and Postgres not public
- [ ] TLS + HSTS at reverse proxy
