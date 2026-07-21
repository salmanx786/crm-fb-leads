# Plan: editable lead statuses with per-status Meta CAPI mapping

## Goal (in your words)
Manage the lead-status dropdown from the dashboard — add/remove options like
Called / Interested / Visited / Paid / Not serious. When a lead's status is
changed using that dropdown, send the matching signal to Meta so Meta learns
what a good lead looks like and optimizes future lead quality.

## The key design point
Meta only understands its own fixed event names. A free-text status like
"Visited" means nothing to Meta. So every editable status carries **two**
things:
1. **Label** — the text you type and see in the dropdown (e.g. "Visited").
2. **Meta event** — which standard Meta event fires when a lead reaches it,
   chosen from a fixed list, including **"Don't send to Meta"** for internal
   statuses (Spam, Not serious).

Meta events offered (the standard optimizable set):
`Lead`, `Contact`, `Schedule`, `SubmitApplication`, `CompleteRegistration`,
`Purchase`, `AddToWishlist`, `StartTrial` — plus **(none)**.

## What already works (no change needed)
- `change_status`, `update_lead`, and `bulk_action` already call
  `meta_service.track_event(lead, status)` after commit.
- `meta_service` already hashes PII + attaches fbc/fbp for match quality.
- Badge palette + metrics cards already fall back gracefully for unknown
  statuses (`.get(name, default)`), so custom statuses won't break the UI.

So this feature = make the **status list** and the **status→Meta-event map**
editable, and point every consumer at the DB instead of the hardcoded constant.

## Storage (reuses the settings pattern we just built)
New table `lead_statuses` (via `db.create_all()`, like `app_settings`):
- `name` (unique, the label)
- `meta_event` (nullable string; NULL = don't send to Meta)
- `sort_order` (int; drives dropdown/filter order)
- `is_protected` (bool; True for "New" so the default status can't be deleted)

Leads keep storing `status` as text (no change to the `leads` table). This is
the standard CRM approach and matches how the codebase already treats status.

New `status_service.py`:
- `get_statuses()` -> ordered list of names
- `get_status_rows()` -> full rows for the settings screen
- `is_valid_status(name)`
- `meta_event_for(name)` -> event or None (replaces constants.meta_event_for
  for status triggers)
- `add_status`, `rename_status`, `delete_status`, `set_meta_event`, `reorder`
- `seed_defaults()` — seeds the current `LEAD_STATUSES` + current
  `META_EVENT_MAP` on first run, so behavior is identical until edited.

## Rename/remove behavior (your choice: auto-update existing leads)
- **Rename**: `rename_status(old, new)` updates the row AND runs
  `UPDATE leads SET status = :new WHERE status = :old` in the same
  transaction, plus records a timeline note per affected lead? -> No: a bulk
  rename could touch many leads; instead record ONE audit log line
  (`logger.info`) with the count. Leads' individual timelines stay clean.
- **Delete**: only allowed if no leads currently use it OR the admin confirms
  reassignment to another status. Simpler + safe default: **block deletion
  while leads use it**, with a message "42 leads use this status — reassign or
  rename instead." "New" (protected) can never be deleted. This avoids
  silently orphaning leads. (Rename covers the "I picked a bad name" case.)

## Meta feedback on status change (the point of the feature)
`meta_service.track_event(lead, trigger)` currently calls
`constants.meta_event_for(trigger)`. Change it so that for a **status trigger**
it resolves the event via `status_service.meta_event_for(status)` (DB), falling
back to the constants map for the synthetic `"lead_created"` trigger. Net
effect: renaming "Interested" to "Hot Lead" and mapping it to `Lead` keeps the
Meta signal flowing under the new name — no code edit needed.

## Files touched
**New**
- `app/models/lead_status.py` — `LeadStatus` model
- `app/services/status_service.py` — CRUD + validation + meta mapping + seed
- `app/blueprints/dashboard/` route(s) for the statuses settings screen
- `app/templates/dashboard/settings_statuses.html`
- `tests/test_status_service.py`, `tests/test_status_settings_routes.py`

**Edited (point consumers at the service)**
- `app/constants.py` — keep `LEAD_STATUSES`/`META_EVENT_MAP` as the seed
  source; keep `meta_event_for` for the `lead_created` trigger only.
- `app/services/reference_service.py` — `get_statuses()` reads status_service.
- `app/services/lead_service.py` — `is_valid_status` -> status_service;
  `DEFAULT_LEAD_STATUS` stays "New".
- `app/services/dashboard_service.py` — `is_valid_status` -> status_service.
- `app/services/meta_service.py` — status triggers resolve event via
  status_service (see above).
- `app/blueprints/dashboard/forms.py` — Status/Bulk/Edit choices from service.
- `app/blueprints/dashboard/routes.py` — pass dynamic statuses; add status
  settings routes; wire nav.
- `app/templates/dashboard/base.html` — sidebar link "Lead Statuses".
- `app/cli.py` — seed statuses on init; `seed_leads` uses dynamic list.
- Seeding: call `status_service.seed_defaults()` from `scripts/init_db.py`
  and app startup guard (only if table empty), like other reference data.

## Meta standard-event guardrail
The Meta-event dropdown is a fixed whitelist in the form, so an admin can only
map to a real Meta event or "none". No free-typing an event name that Meta
would silently reject.

## Tests
- status_service: seed, add, rename cascades to leads, delete blocked while in
  use, protected status, meta_event_for resolution, reorder.
- meta_service: status trigger resolves event from DB mapping (renamed status
  still fires); "none" mapping sends nothing; `lead_created` still uses Lead.
- routes: settings screen add/rename/delete/reorder happy + error paths;
  login-gated.
- Regression: existing status/dropdown/filter tests still pass with the
  service seeded to today's defaults.

## Deploy note (same as before — no auto-migrate)
`lead_statuses` is a new table -> created by `db.create_all()` /
`scripts/init_db.py`. No `ALTER` needed (leads table unchanged). Seed runs
once and reproduces today's exact statuses + Meta mapping, so nothing changes
until you edit them.

## Out of scope (deferred, per our chat)
- Conversion **value** per status (revenue optimization). Not needed now.
- Reassign-on-delete UI (blocking delete-while-in-use is enough for v1).
