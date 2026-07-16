# Routes & endpoints

The app is server-rendered; most endpoints return HTML. The one data-style
endpoint is the public lead submission. All state-changing routes are
CSRF-protected (Flask-WTF); all dashboard routes require login.

## Public

### `GET /`
Renders the landing page with an empty `AdmissionForm`.

### `POST /admission`
Submits an admission enquiry.

**Form fields:** `name` (required), `phone` (required), `email`, `city`,
`course`, `message`, `csrf_token` (required).

**Query params captured as attribution:** `utm_source`, `utm_medium`,
`utm_campaign`. Referrer, IP, and user-agent are read from the request.

**Behaviour:**
- Valid → creates the lead via `lead_service.create_lead` (records a `created`
  timeline event), flashes success, `302` redirect to `/#admission`.
- Invalid → re-renders the page with field errors, HTTP `400`.
- Missing/invalid CSRF → rejected (`400`/`403`).

## Auth

### `GET/POST /login`
Login form. On success, establishes a session and redirects to the dashboard
(or a safe `?next=` target). Wrong credentials → `401`; disabled account →
`403`. Error messages are intentionally generic (no account enumeration).

### `POST /logout`
Ends the session and redirects to login. POST-only (state-changing), so it's a
form submission, not a link.

## Dashboard (login required)

### `GET /dashboard/`
Overview: eight summary cards + recent leads. Each card links into the filtered
lead list.

### `GET /dashboard/leads`
Paginated, searchable, filterable list (newest first).

| Query param | Effect |
|---|---|
| `q` | Case-insensitive search across name, phone, email, city, course |
| `status` | Exact status filter |
| `period` | `today` or `week` — filter by capture time (used by cards) |
| `page` | Page number |

Search, status, and period are preserved across pagination.

### `GET /dashboard/leads/<id>`
Full lead record: personal info, expanded tracking info, timeline, notes, and
the status/note action forms. `404` if not found.

### `POST /dashboard/leads/<id>/status`
Changes the lead's status via `lead_service.change_status` (logs a
`status_changed` event). Redirects back to the detail page with a flash.

### `POST /dashboard/leads/<id>/notes`
Adds a note via `lead_service.add_note` (logs a `note_added` event).

### `POST /dashboard/leads/<id>/delete`
Deletes the lead; notes and timeline cascade. Redirects to the list.

## Conventions

- **Thin routes.** Routes parse input and delegate to services; no business
  logic or aggregation queries live in view functions.
- **Redirect-after-POST.** Every successful mutation redirects and flashes, so a
  refresh never re-submits.
- **Service errors.** `LeadValidationError` carries a field→message map that
  routes surface as flashes or field errors.
