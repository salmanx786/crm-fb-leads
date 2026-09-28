# Roadmap

Status of the project by milestone, completed features, and future items.

## Done

### Milestone 1 — Foundation
Folder structure, config classes, `BaseModel` and core models (`User`, `Lead`, `LeadNote`, `TimelineEvent`, `MetaEvent`, `AppSetting`, `LeadStatus`, `PushSubscription`, `SiteContent`, `GalleryItem`, `FaqItem`), service and utils packages, database indexes.

### Milestone 2 — Public Lead Capture
Application factory, public blueprint, responsive landing page (hero, programs, why-us, facilities, affiliation proof, principal video, gallery, FAQ, contact, footer), multi-step `AdmissionForm` with client/server validation, eligibility checks, CSRF, attribution capture (UTM/referrer/IP/UA/`_fbc`/`_fbp`), debounce throttling, and lead creation through `lead_service`.

### Milestone 3 — Admin Authentication & Dashboard
Login/logout, `flask create-admin`, protected dashboard with summary metrics cards, searchable/filterable/paginated leads table, lead detail with append-only audit timeline, notes feed, follow-up scheduling/clearing, duplicate lead detection, bulk actions (status, follow-up, delete), and UTF-8 CSV exports.

### Milestone 4 — Meta Conversions API (CAPI) & Pixel
Server-side CAPI event dispatching with SHA-256 PII hashing, request-level event deduplication with browser Meta Pixel, offline retry mechanism (`flask retry-meta-events`), and configurable runtime settings via dashboard.

### Milestone 5 — Real-time Web Push & Email Notifications
VAPID-signed Web Push notifications for new leads, automatic pruning of expired push subscriptions, transactional applicant confirmation emails over SMTP, and instant admissions staff email alerts (`notify_team_new_lead`) configured from Dashboard.

### Milestone 6 — Analytics & Response Reporting
Speed-to-contact reporting: median and average time from enquiry to first response, cohort comparison (<=4h early response vs >4h late response), daily volume trends, and per-staff response metrics with filter-aware CSV export.

### Milestone 7 — Dynamic Lifecycle Stages & Landing-Page CMS
Custom lead status creation, renaming (with automated lead status cascading updates), deletion guards, sort ordering, and standard Meta event mappings. Integrated CMS for editing landing page text slots, media uploads, campus gallery photos/videos, and FAQ accordion items without code changes.

### Milestone 8 — Team User Management & Self-Service Profile
Replaced "Coming Soon" sidebar and navbar placeholders with active functionality:
- User listing with role badges and active status indicators.
- Team member creation/invitation (`admin` and `counselor` roles).
- Account activation/deactivation with self-deactivation safeguards.
- Administrator password reset modal.
- Self-service personal profile page (name, email) and secure password change form.

### Milestone 9 — Comprehensive Lead Editing & Counselor Quick-Actions
- Full-spectrum lead editing form covering all academic qualifications (Matric/Inter boards, marks bands, pre-medical study groups), specialization tracks, guardian details (name, phone, area/address), pipeline status, and internal notes.
- One-click counselor contact toolbar on lead detail: direct WhatsApp chat (pre-filled with student greeting and auto-formatted Pakistan numbers), phone call (`tel:`), email (`mailto:`), and guardian WhatsApp contact.

### Milestone 10 — WordPress / Kadence Leads Integration
Client connection and dashboard browsing for remote WordPress / Kadence form submissions with status updates.

---

## Next / Future Enhancements

- **Counselor Lead Assignment** — direct assignment of leads to specific counselors with a dedicated "My Leads" view.
- **Conversion Funnel Analytics** — visual stage-by-stage drop-off tracking from New to Admitted.
- **Precompiled Tailwind Build Pipeline** — optionally compile CSS before deployment to eliminate CDN runtime console warnings.
