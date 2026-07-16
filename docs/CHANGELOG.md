# Changelog

All notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 so
versions are milestone-based.

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
