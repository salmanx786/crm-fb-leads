# Roadmap

Status of the project by milestone, and what's deliberately deferred.

## Done

### Milestone 1 — Foundation
Folder structure, config classes, `BaseModel` and the four models
(`User`, `Lead`, `LeadNote`, `TimelineEvent`), service and utils packages,
string-based status with a canonical constants list, database indexes.

### Milestone 2 — Public lead capture
Application factory, public blueprint, responsive Tailwind landing page (hero,
programs, why-us, facilities, affiliation, testimonials, FAQ, contact, admission
form, footer), `AdmissionForm` with server-side validation and CSRF,
attribution capture (UTM/referrer/IP/UA), lead creation through the service.

### Milestone 3 — Admin authentication & dashboard
Login/logout, `flask create-admin`, protected dashboard with summary cards, a
searchable/filterable/paginated leads table, lead detail with timeline and
notes, status updates — all writes through the service layer.

### Technical-debt cleanup (this milestone)
- Migrated all `Model.query` usage to the SQLAlchemy 2.x `select()`/session API.
- Reworked dashboard metrics into eight cards, all computed in the service.
- Expanded the lead-detail tracking section.
- Extended search to city and course.
- Made metric cards clickable drill-downs.
- Sidebar placeholders (Users, Settings, Profile) with "Coming Soon" badges.
- Added `flask seed-demo-data` for local development.
- Added `docs/`.

## Next

- **Lead editing UI** — `lead_service.update_lead` exists but has no dashboard
  form yet.
- **User management** — build out the Users placeholder (list, invite, disable).
- **Settings & Profile** — the other two sidebar placeholders.
- **Precompiled Tailwind** — replace the CDN with a built stylesheet to remove
  the runtime dependency and production console warning. Needs a build step that
  runs before upload (not on the host).

## Explicitly out of scope (for now)

These have been requested to stay out until later, by product decision:

- Meta Conversion API
- Analytics
- CSV export
- Email notifications
- WhatsApp integration

## Known trade-offs

- **Tailwind via CDN** — zero build step (great for cPanel) but adds a runtime
  dependency and prints a production console warning. Acceptable until a build
  pipeline exists.
- **Status as free string** — flexible (no migration to add a stage) at the cost
  of DB-level enum enforcement; guarded in code by `LEAD_STATUSES`.
- **UTC timestamps** — stored and displayed in UTC. A per-user timezone display
  is a future nicety.
