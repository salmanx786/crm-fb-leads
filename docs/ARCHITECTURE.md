# Architecture

MC College Lead Management System — a Flask application for capturing
admission enquiries from a public landing page and managing them through an
authenticated admin dashboard.

## Goals & constraints

- **Deployable on shared hosting (SymbolHost cPanel).** No build step for the
  frontend, a pure-Python MySQL driver, and connection pooling tuned for hosts
  that drop idle connections.
- **Not overengineered.** No message queue, no SPA, no container runtime.
  Server-rendered Jinja2 templates and a thin service layer.

## Layered design

```
Request
  │
  ▼
Blueprint route  ──►  thin: parse request, call a service, render/redirect
  │
  ▼
Service layer    ──►  all business logic, validation, transactions
  │
  ▼
SQLAlchemy model ──►  persistence (MySQL in prod, SQLite in tests)
```

The rule that keeps the codebase maintainable: **routes never contain business
logic and never build aggregation queries.** They translate HTTP to service
calls. This makes the logic testable without a request context and reusable
from the CLI.

### Packages

| Package | Responsibility |
|---|---|
| `app/blueprints/public` | Landing page + public admission form (`POST /admission`) |
| `app/blueprints/auth` | Login / logout via Flask-Login |
| `app/blueprints/dashboard` | Protected admin views (overview, leads, lead detail, actions) |
| `app/services` | Business logic: `lead_service`, `dashboard_service`, `user_service`, `reference_service` (dropdown data), `meta_service` (Facebook Conversions API) |
| `app/utils` | Framework-agnostic helpers: `validators`, `helpers` (normalisation), `tracking`, `logger` |
| `app/models` | `BaseModel` + `User`, `Lead`, `LeadNote`, `TimelineEvent`, `MetaEvent` |
| `app/templates` | Jinja2 templates (public + dashboard trees) |

### Why a service layer

Every lead write (create, status change, note) flows through `lead_service`,
which owns the transaction and always records a `TimelineEvent`. If routes wrote
to the DB directly, the timeline would drift out of sync with reality. One entry
point per write keeps side effects consistent.

## Application factory

`create_app(config_name)` builds and configures the app. This lets tests and the
WSGI entry point construct isolated instances with different configs. It wires:

- **Extensions** — SQLAlchemy, Flask-Migrate, Flask-Login, CSRFProtect
  (instances live in `app/extensions.py` to avoid circular imports).
- **Blueprints** — public, auth, dashboard.
- **CLI** — `create-admin`, `seed-demo-data`, `retry-meta-events` (see `app/cli.py`).
- **Context processors** — `current_year` for templates.

## Configuration

`config.py` exposes `DevelopmentConfig`, `ProductionConfig`, and `TestingConfig`,
selected via `FLASK_CONFIG`. Secrets and DB credentials come from environment
variables (a `.env` file in development). See [DEPLOYMENT.md](DEPLOYMENT.md).

## Frontend

- **Landing page** — Jinja2 + Tailwind (CDN) + a little vanilla JS. Responsive,
  single page, anchored sections.
- **Dashboard** — Jinja2 + Tailwind (CDN). Sidebar + top nav shell in
  `dashboard/base.html`; a `status_badge` macro keeps status styling consistent.

Tailwind via CDN is deliberate: it removes the Node build step, which shared
hosting can't run cleanly. The trade-off (a runtime CDN dependency and a console
warning) is documented in [ROADMAP.md](ROADMAP.md).

## Data integrity

- `status` is a plain string validated against `app/constants.LEAD_STATUSES`, so
  new stages need no migration.
- `LeadNote` and `TimelineEvent` cascade-delete with their `Lead`.
- Timeline events are append-only — the system's audit trail, distinct from
  editable notes.

## Meta Conversions API integration

Server-side conversion events are sent to Facebook (Meta) when important lead
actions occur — lead creation and reaching certain statuses.

```
lead_service.create_lead / change_status
  │  (the only touchpoint — passes a lead + a trigger string)
  ▼
meta_service.track_event(lead, trigger)
  │  build_payload → hash_user_data (SHA-256 email/phone) → send_event (HTTP)
  ▼
MetaEvent row  ──►  pending → sent | failed   (every attempt persisted)
```

Design decisions:

- **It lives in a service, not in routes.** The CAPI triggers are lead lifecycle
  moments, which already belong to `lead_service`. If the Meta call sat in a
  route, every path that creates or updates a lead (public API, dashboard,
  CLI, future importers) would need its own copy and they would drift.
  `lead_service` only ever calls `meta_service.track_event(...)`; it never
  builds a payload or knows Meta's wire format.
- **Events are never lost.** Each send is a `MetaEvent` row written as `pending`
  *before* the HTTP call, then flipped to `sent` or `failed`. A Meta outage
  cannot break lead creation — `track_event` catches and records failures
  instead of raising.
- **Retries are idempotent.** Each event carries a `event_id` (UUID). Retries
  reuse it so Meta deduplicates against any partial success.
  `retry_failed_events()` resends only `failed` rows; `flask retry-meta-events`
  drives it.
- **Event mapping is configuration.** `app/constants.META_EVENT_MAP` maps a
  trigger (`"lead_created"` or a status) to a Meta event name. Adding a mapping
  is a one-line edit; unmapped triggers are simply not sent.
- **PII never leaves raw.** `hash_user_data` SHA-256-hashes email and phone
  before they enter a payload or the database. Raw email/phone are never stored
  on `MetaEvent` and never logged.

Toggle with `META_ENABLED`; credentials via `META_PIXEL_ID` /
`META_ACCESS_TOKEN`, plus optional `META_TEST_EVENT_CODE`. See
[DEPLOYMENT.md](DEPLOYMENT.md).

See [DATABASE.md](DATABASE.md) for the schema and [API.md](API.md) for routes.
