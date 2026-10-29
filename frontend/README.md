# Frontend demo — Clinic Booking API

A dependency-free static page (plain HTML + CSS + JS, no build step) that
demonstrates how the Clinic Booking REST API is consumed from a browser:

- `GET /doctors` — doctor cards
- `GET /doctors/{id}/availability?date=…` — free-slot chips (clinic-local dates)
- `POST /patients` — inline registration form
- `POST /appointments` — booking, plus a one-click 409 `SLOT_TAKEN` demo
- `GET /patients/{id}/appointments?status=…` — per-patient history with filters
- `PATCH /appointments/{id}/cancel` — with the API's required reason
- `PATCH /appointments/{id}/reschedule` — pick a new date + slot inline
- `GET /health` — connection pill in the header

An **API console** panel logs every request and response (method, path,
status code, latency, JSON payloads) so reviewers can watch the HTTP
conversation in real time.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Page structure (semantic, accessible) |
| `styles.css` | Design system — no external fonts or assets |
| `app.js` | All logic: fetch wrapper, state, rendering, console |
| `vercel.json` | Security headers + cache hints for static hosting |

The API base URL defaults to the deployed Render service and can be
overridden with `?api=<base-url>` in the address bar (useful for pointing
the demo at a local `uvicorn` instance: `?api=http://127.0.0.1:8000`).

## Run locally

```bash
# from this folder — any static file server works
python3 -m http.server 8080
# open http://127.0.0.1:8080
```

The page calls the live API cross-origin; the backend ships CORS enabled
(`CORS_ORIGINS` env var, default `*`) — see `app/main.py`.

## Deploy to Vercel

1. Push the repo (the `frontend/` folder is already committed).
2. [vercel.com/new](https://vercel.com/new) → import the repository.
3. Set **Root Directory** to `frontend` (Framework preset: *Other*).
4. Deploy — no build command, no dependencies.

The backend allows any origin by default; to lock it down, set
`CORS_ORIGINS=https://<your-vercel-subdomain>.vercel.app` on the Render
service and redeploy.
