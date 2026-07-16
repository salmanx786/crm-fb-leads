# Database

MySQL in production (via `PyMySQL`), SQLite in-memory for tests. All models
inherit from `BaseModel`, which provides the surrogate key and timestamps.

## BaseModel (abstract)

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `created_at` | DateTime | defaults to `utcnow`, indexed |
| `updated_at` | DateTime | `utcnow`, auto-updates on modify |

`__allow_unmapped__ = True` is set so SQLAlchemy 2.0 tolerates the legacy
column-assignment style used across the models.

## users

Admin accounts for the dashboard.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(120) | |
| `email` | String(255) | unique, indexed |
| `password_hash` | String(255) | `pbkdf2:sha256` (portable on shared hosting) |
| `is_active` | Boolean | mapped from `is_active_flag`; default true |
| `created_at`, `updated_at` | DateTime | from BaseModel |

## leads

The core entity: a prospective student captured from the landing page.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(120) | required |
| `phone` | String(20) | required, normalised |
| `email` | String(255) | optional, lowercased |
| `city` | String(120) | optional |
| `course` | String(120) | optional |
| `message` | Text | optional |
| `utm_source` | String(120) | attribution |
| `utm_medium` | String(120) | attribution |
| `utm_campaign` | String(120) | attribution |
| `referrer` | String(512) | HTTP referrer |
| `ip_address` | String(45) | IPv4/IPv6, honours one proxy hop |
| `user_agent` | String(512) | raw UA string |
| `status` | String(32) | validated against `LEAD_STATUSES`, default `New` |
| `created_at`, `updated_at` | DateTime | from BaseModel |

### Indexes

Single-column: `status`, `phone`, `email`, `city`, `course` (the columns the
dashboard filters/searches on), plus `created_at` from BaseModel.

Composite: `(status, created_at)` — backs the most common query, "leads in a
given stage, newest first," satisfying both filter and sort from one index.

## lead_notes

Admin-authored free-text notes.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `lead_id` | FK → leads.id | `ON DELETE CASCADE`, indexed |
| `author_id` | FK → users.id | `ON DELETE SET NULL` (notes survive staff removal) |
| `body` | Text | required |
| `created_at`, `updated_at` | DateTime | from BaseModel |

## timeline_events

System-generated, append-only audit log.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `lead_id` | FK → leads.id | `ON DELETE CASCADE`, indexed |
| `actor_id` | FK → users.id | `ON DELETE SET NULL` |
| `event_type` | String(50) | `created`, `status_changed`, `note_added`, `updated` |
| `description` | String(512) | human-readable summary |
| `created_at`, `updated_at` | DateTime | from BaseModel |

## Lead lifecycle statuses

Defined in `app/constants.py`:

`New → Called → Interested → Follow-up → Documents Pending → Fee Pending →
Admitted / Rejected / Spam`

Stored as strings so adding a stage is a one-line change, no migration.

## Migrations

Flask-Migrate (Alembic) is wired in. For a fresh local DB you can also run
`flask init-db` (via `manage.py`) to create tables directly. See
[DEPLOYMENT.md](DEPLOYMENT.md).
