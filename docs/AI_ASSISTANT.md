# AI Response Assistant (Docker + Ollama)

Merged with the Copilot UI/UX update.

## Run

```bash
docker compose up --build -d
docker compose logs -f ollama-init   # first run: model download
```

Open http://localhost:8501 → sidebar **🤖 AI Assistant**.

## Admin login (first boot)

- Username: `admin`
- Password: value of `BOOTSTRAP_ADMIN_PASSWORD` in `.env` (default in sample: `Adm1n#X9kP2mQ7vR4!`)

## Behaviour

1. Search library by semantic similarity.
2. Reuse existing response if score ≥ threshold (default 0.82).
3. Otherwise generate once and optionally save with badge `AI`.
