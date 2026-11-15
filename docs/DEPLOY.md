# Deploy: HTTPS and reverse proxy

The Streamlit app binds to **127.0.0.1:8501** in Docker Compose. Put TLS in front.

## Required production env
- `APP_ENV=production`
- `APP_SECRET_KEY` (long random)
- `FERNET_KEY` (Fernet key)
- `APP_URL=https://your.domain` (no trailing slash)
- `FORCE_HTTPS=true` (sets Secure on session cookie)
- Strong `POSTGRES_PASSWORD` / `DATABASE_URL`
- `ALLOW_URL_SESSION` must stay off

## Caddy example
```caddyfile
your.domain {
    reverse_proxy 127.0.0.1:8501
}
```

## Nginx example
```nginx
server {
    listen 443 ssl http2;
    server_name your.domain;
    # ssl_certificate /path/fullchain.pem;
    # ssl_certificate_key /path/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

## Health check
With `HEALTH_TOKEN` set, open `https://your.domain/?health=<token>` (superadmin health UI also available in-app).

## SEO / crawlers
Ship `static/robots.txt` with `Disallow: /` so public crawlers skip this internal app.
