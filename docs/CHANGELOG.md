# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 so
versions are milestone-based.

## [Unreleased] — Meta Conversions API integration

### Added
- `app/services/meta_service.py` — Meta (Facebook) Conversions API integration:
  `track_event`, `build_payload`, `hash_user_data`, `send_event`,
  `save_result`, `retry_failed_events`. Business code only ever calls
  `track_event`; it never builds a payload or knows Meta's wire format.
- `MetaEvent` model — persists every send attempt (`pending`/`sent`/`failed`/
  `orphaned`) with request/response payloads, so a failed send is never lost.
  Indexed on `status`, `lead_id`, and `created_at` (via `BaseModel`).
- `email` and `phone` are SHA-256 hashed (lowercase/trim, digits-only for
  phone) before entering any payload or the database. Raw PII is never sent,
  stored, or logged.
- CRM-trigger → Meta-event mapping in `app/constants.META_EVENT_MAP`
  (`lead_created`/`Interested` → `Lead`, `Documents Pending` →
  `SubmitApplication`, `Admitted` → `CompleteRegistration`), so event names are
  configuration, not hardcoded.
- `flask retry-meta-events` CLI — resends only `failed` events, reusing each
  event's `event_id` so Meta deduplicates against the original attempt.
- Config: `META_ENABLED`, `META_PIXEL_ID`, `META_ACCESS_TOKEN`,
  `META_TEST_EVENT_CODE`. `requests` added to requirements.
- Tests (`tests/test_meta_service.py`) covering payload generation, hashing,
  successful send, failed send, network error, retry, disabled/untracked
  no-ops, and status-change triggering — all HTTP mocked; Meta is never called.

### Changed
- Renamed the previous `meta_service.py` (course/status dropdown data) to
  `reference_service.py` to free the `meta_service` name for the Facebook
  integration. Updated its two importers (`public/forms.py`, `public/routes.py`).
- `lead_service` now calls `meta_service.track_event` on lead creation and on
  status change. Meta failures are swallowed and persisted — they never break a
  lead write.

## [Unreleased] — Production-readiness: structured logging

### Added
- `app/utils/logger.py` — reusable logging setup. `configure_logging(app)` is
  called once from the factory; `get_logger(__name__)` gives any module a
  namespaced logger under the `mc` root.
- Rotating file handler at `logs/app.log` (INFO+, 1 MB × 5 backups); console
  handler at WARNING+. File handler is skipped under the testing config so the
  suite stays filesystem-free.
- Log events: lead creation, login success/failure, disabled-account block,
  logout, lead status changes, and unhandled (500-class) exceptions with
  traceback. Passwords, session tokens, and CSRF tokens are never logged.

### Changed
- Application factory wires up logging and an exception handler that logs real
  errors while letting HTTP responses (404/400/401) pass through untouched.

## [Unreleased] — Technical-debt cleanup

### Changed
- Migrated all `Model.query` usage to the SQLAlchemy 2.x `select()` / session
  API (`db.session.scalar`, `db.session.scalars`, `db.session.execute`,
  `db.paginate`) across services, routes, and tests.
- Dashboard metrics reworked into eight cards — Today, This Week, Total, New,
  Follow-up, Documents Pending, Interested, Admitted — all computed in
  `dashboard_service`, none in routes.
- Dashboard search now also matches **city** and **course** (still
  case-insensitive).
- Lead-detail tracking section expanded: UTM source/medium/campaign, referrer,
  landing page URL (when stored), IP, user agent, and submission date/time,
  professionally formatted.

### Added
- Clickable metric cards that drill into the filtered lead list; search, status,
  and period filters are preserved across pagination.
- Sidebar placeholders for Users, Settings, and Profile (disabled, "Coming
  Soon" badge).
- `flask seed-demo-data` CLI command — generates demo leads with random
  statuses/cities/courses plus timeline events and notes (local dev only).
- `docs/`: ARCHITECTURE, DATABASE, API, ROADMAP, DEPLOYMENT, CHANGELOG.
- Tests for dashboard search, dashboard metrics, and the seed command.

## [Milestone 3] — Admin authentication & dashboard

### Added
- Auth blueprint: login and logout via Flask-Login.
- `flask create-admin` CLI and `user_service`.
- Protected dashboard: summary cards, searchable/filterable/paginated leads
  table, lead detail with timeline and notes, status updates.
- Responsive Tailwind dashboard shell (sidebar, top nav, flash, status badges).
- Tests: login, protected routes, create-admin, status update, note creation.

### Changed
- Pinned password hashing to `pbkdf2:sha256` for shared-hosting portability.

## [Milestone 2] — Public lead capture

### Added
- Application factory wiring SQLAlchemy, Migrate, Login, and CSRF.
- Public blueprint: responsive landing page and `POST /admission`.
- `AdmissionForm` with server-side validation and CSRF.
- Attribution capture (UTM, referrer, IP, user-agent) and lead creation through
  `lead_service`, recording a `created` timeline event.
- `TestingConfig` and the first end-to-end tests.

### Fixed
- SQLAlchemy 2.0 mapped-annotation error (dropped bare column annotations).
- Python 3.9 compatibility for `X | None` annotations.

## [Milestone 1] — Foundation

### Added
- Project structure, config classes, environment-variable driven settings.
- `BaseModel` and models: `User`, `Lead`, `LeadNote`, `TimelineEvent`.
- Service and utils packages; string-based lead status with a canonical
  constants list; database indexes including composite `(status, created_at)`.
