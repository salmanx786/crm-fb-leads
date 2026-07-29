# Deployment

Target: **SymbolHost cPanel shared hosting** with "Setup Python App"
(Passenger). Also covers local development.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env          # then edit DB_* and SECRET_KEY

# Create tables (quick path) or run migrations
flask --app manage init-db    # or: flask --app manage db upgrade

flask --app manage create-admin
flask --app manage seed-demo-data     # optional: 50 demo leads (dev only)

python manage.py              # http://127.0.0.1:5000
```

Run the tests with `pytest -q` (uses in-memory SQLite; no DB setup needed).

## Environment variables

Set these in `.env` locally, and in the cPanel Python App's environment section
in production. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session/CSRF signing. **Set a strong random value in prod.** |
| `FLASK_CONFIG` | `development` / `production` |
| `DATABASE_URL` | Full Postgres URI (Supabase). The app reads this only. |
| `LEADS_PER_PAGE` | Optional pagination size (default 20) |

The engine uses `pool_pre_ping` so a connection dropped by the pooler is
detected and replaced rather than raising mid-request. Supabase requires SSL —
keep `?sslmode=require` on the URL.

## cPanel deployment (Passenger)

1. **Create the app.** cPanel → *Setup Python App* → pick a Python 3.x version,
   set the application root and a startup file. Passenger imports `application`
   from the WSGI entry (`wsgi.py`, which exposes the app).
2. **Upload the code** (Git or the File Manager) into the app root.
3. **Install dependencies.** From the app's virtualenv:
   `pip install -r requirements.txt` (production deps only — not
   `requirements-dev.txt`).
4. **Provision the database.** Create a Postgres project in Supabase and set
   `DATABASE_URL` to its connection string (use the Session pooler host on
   IPv4-only hosting; keep `?sslmode=require`).
5. **Create the schema.** Run `flask --app manage db upgrade` (or `init-db`) from
   the app's Python environment.
6. **Create the first admin:** `flask --app manage create-admin`.
7. **Restart the app** from the cPanel Python App screen.

### Notes for shared hosting

- **Driver:** `psycopg2-binary` ships a precompiled wheel — no compiler needed
  on the host. Connect to Supabase over the Session pooler on IPv4-only hosting.
- **Password hashing:** `pbkdf2:sha256`, because some hosts' Python builds lack
  OpenSSL `scrypt` (Werkzeug's default).
- **Python version:** the code targets 3.9+ (`from __future__ import
  annotations` keeps `X | None` annotations working on 3.9).
- **HTTPS:** `ProductionConfig` sets `SESSION_COOKIE_SECURE = True`; serve the
  site over SSL (cPanel AutoSSL).
- **Do not** run `seed-demo-data` against a production database.

## Post-deploy checklist

- [ ] `SECRET_KEY` is a strong, unique value
- [ ] `FLASK_CONFIG=production`
- [ ] Site served over HTTPS
- [ ] Admin account created and login verified
- [ ] Landing form submits and a lead appears in the dashboard
