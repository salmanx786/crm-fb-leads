# MC College Admissions CRM

A lightweight admissions CRM for a college landing page: it captures prospective-student
enquiries from a public form and gives the admissions team a dashboard to track, filter,
edit, and follow up on those leads. Built as a single Flask application with a clean
service layer, designed to run comfortably on shared cPanel/Passenger hosting.

## Features

- **Lead capture** — public landing-page form with server-side validation and UTM/referrer tracking
- **Admin dashboard** — paginated, searchable, status- and follow-up-filterable lead list with summary metrics
- **Authentication** — session-based admin login (Flask-Login), password hashing, CSRF protection
- **Lead timeline** — append-only, system-generated activity history per lead
- **Duplicate detection** — surfaces leads sharing a phone or email, computed on read (never stored)
- **Follow-up management** — schedule, reschedule, and clear follow-up dates with overdue/today/upcoming filters
- **Lead editing** — edit applicant fields, status, and source from the list or detail view
- **Bulk actions** — change status, delete, and schedule/clear follow-ups across many leads in one transaction
- **CSV export** — download the currently filtered lead list as UTF-8 CSV
- **Meta Conversions API** — optional server-side conversion events (disabled by default)

## Tech Stack

- **Python 3.9**
- **Flask** — application framework (app-factory + blueprints)
- **SQLAlchemy** — ORM (SQLAlchemy 2.x style via Flask-SQLAlchemy)
- **MySQL** — production database (PyMySQL driver); SQLite in-memory for tests
- **WTForms** — forms and validation (Flask-WTF for CSRF)
- **Jinja2** — server-rendered templates (Tailwind via CDN, no build step)

## Project Structure

```
mc-landing-page/
├── app/
│   ├── __init__.py          # application factory: config, extensions, blueprints
│   ├── constants.py         # lead statuses, Meta event mapping
│   ├── extensions.py        # shared extension instances (db, login, csrf, migrate)
│   ├── cli.py               # custom CLI commands (create-admin, seed-demo-data)
│   ├── blueprints/
│   │   ├── public/          # landing page, admission form, /health
│   │   ├── auth/            # login / logout
│   │   └── dashboard/       # admin lead management (list, detail, edit, bulk, export)
│   ├── models/              # SQLAlchemy models (Lead, LeadNote, TimelineEvent, User, MetaEvent)
│   ├── services/            # business logic: lead_service, dashboard_service, meta_service, ...
│   ├── templates/           # Jinja2 templates (public, auth, dashboard)
│   └── utils/               # framework-agnostic helpers (validation, tracking, logging)
├── tests/                   # pytest suite (in-memory SQLite)
├── docs/                    # ARCHITECTURE, DATABASE, DEPLOYMENT, API, ROADMAP, CHANGELOG
├── config.py                # environment-specific configuration classes
├── manage.py                # dev entry point + init-db command
└── wsgi.py                  # WSGI entry point (Passenger imports `application`)
```

All lead writes flow through the service layer (`app/services/`) so side effects — timeline
events, validation, normalisation, Meta events — happen consistently regardless of caller.
Routes stay thin: parse the request, call a service, render or redirect. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detail.

## Local Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install requirements

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Then edit `.env` — set at least `SECRET_KEY` and the `DB_*` values. For local
development you can point at SQLite via `DATABASE_URL`, or use a local MySQL.

### 4. Run the application

```bash
flask --app manage init-db          # create tables
flask --app manage create-admin     # create the first admin account
flask --app manage seed-demo-data   # optional: 50 demo leads (dev only)

python manage.py                    # http://127.0.0.1:5000
```

Run the tests with `pytest -q` (uses in-memory SQLite; no database setup needed).

Verify the app is up:

```bash
curl http://127.0.0.1:5000/health   # {"status": "ok"}
```

## Deployment

Target: **cPanel shared hosting** with "Setup Python App" (Passenger). This section
summarises [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), which has the full checklist.

### Environment variables

Set these in the cPanel Python App's environment section (never commit `.env`):

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session/CSRF signing. **Required in production** — the app refuses to start if it is missing or still the placeholder value. |
| `FLASK_CONFIG` | `development` / `production`. Set to `production`. |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` | MySQL connection parts |
| `DATABASE_URL` | Optional full URI; overrides the discrete `DB_*` parts |
| `LEADS_PER_PAGE` | Optional pagination size (default 20) |
| `META_ENABLED`, `META_PIXEL_ID`, `META_ACCESS_TOKEN`, ... | Optional Meta Conversions API (disabled by default) |

### Database setup

1. Create the MySQL database and user in cPanel, grant privileges, and fill the `DB_*` variables.
2. Create the schema from the app's Python environment: `flask --app manage init-db`.
3. Create the first admin: `flask --app manage create-admin`.

The database URI forces `charset=utf8mb4`, and the engine uses `pool_pre_ping` plus a
short `pool_recycle` so connections don't go stale on shared MySQL.

### Running on cPanel / Passenger

1. **Create the app** — cPanel → *Setup Python App* → pick Python 3.9+, set the
   application root and startup file.
2. **Upload the code** into the app root (Git or File Manager).
3. **Install production dependencies** from the app's virtualenv:
   `pip install -r requirements.txt` (not `requirements-dev.txt`).
4. **Set the environment variables** (above), including `FLASK_CONFIG=production`.
5. **Create the schema and admin** (see Database setup).
6. **Restart the app** from the cPanel Python App screen.

### WSGI entry point

Passenger imports `application` from [wsgi.py](wsgi.py):

```python
from app import create_app
application = create_app()
```

### Production recommendations

- **`SECRET_KEY`** — a strong, unique random value. Production will not boot without it.
- **`FLASK_CONFIG=production`** — enables `SESSION_COOKIE_SECURE` and disables debug.
- **HTTPS** — serve over SSL (cPanel AutoSSL); production cookies are secure-only.
- **Driver** — `PyMySQL` is pure Python (no compiler needed on shared hosting).
- **Password hashing** — `pbkdf2:sha256`, since some hosts' Python lacks OpenSSL `scrypt`.
- **Health checks** — point uptime monitoring at `GET /health` (no auth, no DB).
- **Do not** run `seed-demo-data` against a production database.

## Screenshots

### Dashboard

![Dashboard](docs/screenshots/dashboard.png)

### Lead Detail

![Lead Detail](docs/screenshots/lead-detail.png)

### Timeline

![Timeline](docs/screenshots/timeline.png)

### Bulk Actions

![Bulk Actions](docs/screenshots/bulk-actions.png)

### CSV Export

![CSV Export](docs/screenshots/csv-export.png)
