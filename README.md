# MC College Admissions CRM

A lightweight admissions CRM for a college landing page: captures prospective-student
enquiries from a public form and gives the admissions team a dashboard to track, filter,
edit, and follow up on those leads. Built as a single Flask application with a clean
service layer, designed to run on shared cPanel/Passenger hosting.

## Features

- **Lead capture** — public landing-page form with server-side validation and UTM/referrer tracking
- **Admin dashboard** — paginated, searchable, status- and follow-up-filterable lead list with summary metrics
- **Authentication** — session-based admin login (Flask-Login), password hashing, CSRF protection
- **Lead timeline** — append-only, system-generated activity history per lead
- **Duplicate detection** — surfaces leads sharing a phone or email, computed on read
- **Follow-up management** — schedule, reschedule, and clear follow-up dates with overdue/today/upcoming filters
- **Lead editing** — edit applicant fields, status, and source from the list or detail view
- **Bulk actions** — change status, delete, and schedule/clear follow-ups across many leads in one transaction
- **CSV export** — download the currently filtered lead list as UTF-8 CSV
- **Editable lead statuses** — add, rename, and delete statuses from the dashboard; each maps to a Meta event
- **Admin CMS** — edit landing-page text, gallery images, and FAQ items without touching code
- **Transactional email** — optional SMTP confirmation email to the applicant on new lead
- **Web Push notifications** — optional VAPID push to logged-in admins on new lead
- **Meta Conversions API** — optional server-side conversion events

## Tech Stack

- **Python 3.9**
- **Flask** — application framework (app-factory + blueprints)
- **SQLAlchemy 2.x** — ORM via Flask-SQLAlchemy
- **WTForms** — forms and validation (Flask-WTF for CSRF)
- **Jinja2** — server-rendered templates (Tailwind via CDN, no build step)
- **pywebpush** — VAPID-signed Web Push notifications

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                            Browser                               │
│    Public visitor              │         Logged-in admin         │
└────────────┬───────────────────┼─────────────────────────────────┘
             │                   │
             ▼                   ▼
┌────────────────┐  ┌────────────────────────────────────────────┐
│   public_bp    │  │  auth_bp       dashboard_bp    content_bp  │
│ /              │  │  /login        /dashboard      /content    │
│ /admission     │  │  /logout       /leads          /slot       │
│ /thank-you     │  │                /settings       /gallery    │
│ /health        │  │                /push           /faq        │
└───────┬────────┘  └──────────────────┬─────────────────────────┘
        │                              │
        │           Service layer      │
        │  ┌───────────────────────────┴──────────────────────┐
        └─►│  lead_service      dashboard_service             │
           │  status_service    content_service               │
           │  settings_service  reference_service             │
           │  user_service                                    │
           └──────────────┬───────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
      ┌────────────────┐    ┌──────────────────────────┐
      │ SQLAlchemy      │    │  Side-effect services    │
      │ models          │    │  (best-effort, isolated) │
      │                 │    │                          │
      │ User            │    │  meta_service ──► Meta    │
      │ Lead            │    │    Conversions API (HTTP) │
      │ LeadNote        │    │  email_service ─► SMTP    │
      │ TimelineEvent   │    │  push_service ──► Web     │
      │ MetaEvent       │    │    Push (VAPID)           │
      │ AppSetting      │    └──────────────────────────┘
      │ LeadStatus      │
      │ PushSubscription│
      │ SiteContent     │
      │ GalleryItem     │
      │ FaqItem         │
      └───────┬─────────┘
              ▼
      ┌────────────────────────────┐
      │  Database                  │
      │  PostgreSQL (prod)         │
      │  SQLite in-memory (tests)  │
      └────────────────────────────┘
```

Routes stay thin: parse the request, call a service, render or redirect. All lead
writes flow through `lead_service`, so side effects — timeline events, validation,
normalisation, Meta/email/push dispatch — happen consistently regardless of caller.
Side-effect services are best-effort and isolated: a Meta outage, SMTP failure, or
push error is caught and recorded, never allowed to break a lead write. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detail.

## Project Structure

```
mc-landing-page/
├── app/
│   ├── __init__.py          # application factory: config, extensions, blueprints
│   ├── constants.py         # lead statuses, Meta event mapping
│   ├── extensions.py        # shared extension instances (db, login, csrf, migrate)
│   ├── cli.py               # CLI commands (create-admin, seed-*, retry-meta-events, generate-vapid-keys)
│   ├── blueprints/
│   │   ├── public/          # landing page, admission form, /health, /privacy
│   │   ├── auth/            # login / logout
│   │   └── dashboard/       # admin: leads (routes.py) + landing-page CMS (content_routes.py)
│   ├── models/              # SQLAlchemy models (see architecture diagram)
│   ├── services/            # business logic (lead, dashboard, status, content, settings, meta, email, push, user, reference)
│   ├── templates/           # Jinja2 templates (public, auth, dashboard)
│   └── utils/               # framework-agnostic helpers (validators, tracking, logger, helpers)
├── tests/                   # pytest suite (in-memory SQLite)
├── scripts/                 # init_db.py, create_admin.py, sync_db.py (manual schema sync)
├── docs/                    # ARCHITECTURE, DATABASE, DEPLOYMENT, API, ROADMAP, CHANGELOG
├── config.py                # environment-specific configuration classes
├── manage.py                # dev entry point + init-db command
└── wsgi.py                  # WSGI entry point (Passenger imports `application`)
```

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

Edit `.env` and set at least `SECRET_KEY` and `DATABASE_URL`. For local development
you can point `DATABASE_URL` at SQLite (`sqlite:///instance/dev.db`) or a local
PostgreSQL instance. Optional integrations (Meta, email, push) are disabled by
default and can be left blank.

### 4. Initialise the database and run

```bash
flask --app manage init-db          # create tables + seed default content/statuses
flask --app manage create-admin     # create the first admin account
flask --app manage seed-demo-data   # optional: 50 demo leads (dev only)

python manage.py                    # http://127.0.0.1:5000
```

`init-db` runs `db.create_all()` and seeds default FAQ content and lead statuses, so
dropdowns and the CMS work on first run.

Run the tests with `pytest -q` (uses in-memory SQLite; no database setup needed).

Verify the app is up:

```bash
curl http://127.0.0.1:5000/health   # {"status": "ok"}
```

### Optional: enable Web Push

```bash
flask --app manage generate-vapid-keys
```

Paste the printed keys into Dashboard → Notifications (or `.env`), set a
`VAPID_SUBJECT` like `mailto:admin@yourdomain`, and enable push.

## Deployment

Target: **cPanel shared hosting** with "Setup Python App" (Passenger). This section
summarises [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), which has the full checklist.

### Environment variables

Set these in the cPanel Python App's environment section (never commit `.env`):

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session/CSRF signing. **Required in production** — the app refuses to start if it is missing or still the placeholder value. |
| `FLASK_CONFIG` | `development` / `production`. Set to `production`. |
| `DATABASE_URL` | Full SQLAlchemy database URI (PostgreSQL in production). |
| `LEADS_PER_PAGE` | Optional pagination size (default 20). |
| `MAX_UPLOAD_MB` | Optional CMS media upload cap in MB (default 64). |
| `META_ENABLED`, `META_PIXEL_ID`, `META_ACCESS_TOKEN`, ... | Optional Meta Conversions API (disabled by default; also configurable from the dashboard). |
| `MAIL_ENABLED`, `MAIL_SMTP_HOST`, `MAIL_USERNAME`, `MAIL_PASSWORD`, ... | Optional applicant confirmation email (disabled by default). |
| `PUSH_ENABLED`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Optional Web Push (disabled by default). |

Meta, email, and push settings can also be managed from the dashboard settings
pages; dashboard values take precedence over environment variables.

### Database and schema changes

1. Create the database and fill `DATABASE_URL`.
2. Create the schema: `flask --app manage init-db`.
3. Create the first admin: `flask --app manage create-admin`.

**There is no migration framework (no Alembic/Flask-Migrate).** `db.create_all()`
creates *missing tables* but never ALTERs *existing* ones:

- **New table** — run `flask --app manage init-db` (or `python scripts/init_db.py`); it is added.
- **New column on an existing table** — apply an explicit `ALTER TABLE ... ADD COLUMN ...` by hand. `create_all` will not add it, and inserts will fail in prod on the missing column while tests (fresh SQLite) still pass. See `scripts/sync_db.py`.

### Running on cPanel / Passenger

1. **Create the app** — cPanel → *Setup Python App* → pick Python 3.9+, set the application root and startup file.
2. **Upload the code** into the app root (Git or File Manager).
3. **Install production dependencies** from the app's virtualenv: `pip install -r requirements.txt` (not `requirements-dev.txt`).
4. **Set the environment variables** (above), including `FLASK_CONFIG=production`.
5. **Create the schema and admin** (see above).
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
