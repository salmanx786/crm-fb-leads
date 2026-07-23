"""Custom Flask CLI commands.

Registered on the app in the factory so they're available via
`flask <command>` (and through manage.py, which builds the same app).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import click
from flask import Flask

from app.extensions import db
from app.models import Lead, LeadNote, TimelineEvent
from app.services import status_service, user_service
from app.services.user_service import UserAlreadyExistsError

# Sample data pools for seeding. Local-development only.
_DEMO_CITIES = [
    "Pune", "Mumbai", "Nagpur", "Nashik", "Delhi", "Jaipur",
    "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Indore", "Surat",
]
_DEMO_COURSES = [
    "B.Com", "BBA", "BCA", "B.Sc", "B.A", "M.Com", "MBA", "MCA",
]
_DEMO_FIRST = [
    "Asha", "Rahul", "Priya", "Vikram", "Sneha", "Arjun", "Neha",
    "Rohan", "Divya", "Karan", "Meera", "Aditya", "Pooja", "Sameer",
]
_DEMO_LAST = [
    "Sharma", "Verma", "Patil", "Nair", "Gupta", "Reddy", "Iyer",
    "Kulkarni", "Desai", "Joshi", "Mehta", "Rao",
]
_DEMO_SOURCES = ["google", "facebook", "instagram", "referral", "direct"]
_DEMO_MEDIUMS = ["cpc", "organic", "social", "email", "none"]
_DEMO_NOTES = [
    "Called and shared the prospectus.",
    "Interested in the evening batch.",
    "Asked about scholarship options.",
    "Will visit campus next week.",
    "Requested a callback after 6pm.",
]


def register_commands(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--name", prompt="Name", help="Administrator's full name.")
    @click.option("--email", prompt="Email", help="Login email address.")
    @click.password_option(
        "--password",
        prompt="Password",
        confirmation_prompt=True,
        help="Login password (hashed before storage).",
    )
    def create_admin(name: str, email: str, password: str) -> None:
        """Create the first administrator account."""
        try:
            user = user_service.create_admin(name=name, email=email, password=password)
        except UserAlreadyExistsError as exc:
            raise click.ClickException(str(exc))

        click.echo(f"Admin created: {user.name} <{user.email}>")

    @app.cli.command("seed-statuses")
    def seed_statuses() -> None:
        """Seed the lead-status list from defaults if the table is empty.

        Idempotent — safe to run on every deploy. Reproduces the historical
        statuses and their Meta-event mapping so behaviour is unchanged until an
        admin edits them in the dashboard.
        """
        count = status_service.seed_defaults()
        if count:
            click.echo(f"Seeded {count} default lead statuses.")
        else:
            click.echo("Lead statuses already present; nothing to seed.")

    @app.cli.command("seed-demo-data")
    @click.option("--count", default=50, show_default=True, help="Number of demo leads.")
    def seed_demo_data(count: int) -> None:
        """Generate demo leads with statuses, timeline events and notes.

        For LOCAL DEVELOPMENT only. Writes directly (bypassing lead_service)
        so it can backdate created_at and craft varied history quickly.
        """
        # Guard against accidentally seeding a production database. Tests set
        # TESTING=True and are allowed through without a prompt.
        if not app.config.get("DEBUG") and not app.config.get("TESTING"):
            if not click.confirm(
                "App is not in development mode. Seed demo data anyway?"
            ):
                click.echo("Aborted.")
                return

        now = datetime.utcnow()
        # Ensure statuses exist (fresh dev DBs may not be seeded yet), then draw
        # demo statuses from the live, admin-editable list.
        status_service.seed_defaults()
        statuses = status_service.get_statuses()
        created = 0
        for _ in range(count):
            first = random.choice(_DEMO_FIRST)
            last = random.choice(_DEMO_LAST)
            status = random.choice(statuses)
            # Spread creation over the last ~45 days.
            age = timedelta(
                days=random.randint(0, 45),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            created_at = now - age

            lead = Lead(
                name=f"{first} {last}",
                phone=f"+9198{random.randint(10000000, 99999999)}",
                email=f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@example.com",
                city=random.choice(_DEMO_CITIES),
                course=random.choice(_DEMO_COURSES),
                message=random.choice(["", "Please share fee details.", "Looking for hostel."]),
                status=status,
                utm_source=random.choice(_DEMO_SOURCES),
                utm_medium=random.choice(_DEMO_MEDIUMS),
                utm_campaign=random.choice(["summer-2026", "admissions", "brand", None]),
                referrer=random.choice(["https://google.com", "https://facebook.com", None]),
                ip_address=f"49.36.{random.randint(0, 255)}.{random.randint(1, 254)}",
                user_agent="Mozilla/5.0 (demo-seed)",
                created_at=created_at,
                updated_at=created_at,
            )
            db.session.add(lead)
            db.session.flush()  # assign lead.id for the related rows

            # Always record the creation event.
            db.session.add(
                TimelineEvent(
                    lead=lead,
                    event_type="created",
                    description="Lead captured from landing page.",
                    created_at=created_at,
                )
            )
            # If the lead moved past "New", log a status change too.
            if status != "New":
                db.session.add(
                    TimelineEvent(
                        lead=lead,
                        event_type="status_changed",
                        description=f"Status changed from New to {status}.",
                        created_at=created_at + timedelta(hours=1),
                    )
                )
            # Attach a note to roughly half the leads.
            if random.random() < 0.5:
                note_at = created_at + timedelta(hours=2)
                db.session.add(LeadNote(lead=lead, body=random.choice(_DEMO_NOTES), created_at=note_at))
                db.session.add(
                    TimelineEvent(
                        lead=lead,
                        event_type="note_added",
                        description="Note added.",
                        created_at=note_at,
                    )
                )
            created += 1

        db.session.commit()
        click.echo(f"Seeded {created} demo leads with timeline events and notes.")

    @app.cli.command("retry-meta-events")
    @click.option("--limit", default=100, show_default=True, help="Max events to retry.")
    def retry_meta_events(limit: int) -> None:
        """Resend all Meta Conversions API events currently marked failed."""
        from app.services import meta_service

        result = meta_service.retry_failed_events(limit=limit)
        click.echo(
            "Meta retry: retried={retried} sent={sent} failed={failed}".format(**result)
        )

    @app.cli.command("generate-vapid-keys")
    def generate_vapid_keys() -> None:
        """Generate a VAPID key pair for Web Push notifications.

        Prints the base64url-encoded public and private keys in the
        application-server-key format the browser's PushManager and pywebpush
        expect. Paste them into the dashboard Notifications page (or a .env's
        VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY). Run once; keys are long-lived.
        """
        import base64

        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid01

        def _b64url(raw: bytes) -> str:
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

        vapid = Vapid01()
        vapid.generate_keys()
        public_key = _b64url(
            vapid.public_key.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        )
        private_key = _b64url(
            vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        )

        click.echo("VAPID key pair generated. Store the private key securely.\n")
        click.echo(f"VAPID_PUBLIC_KEY={public_key}")
        click.echo(f"VAPID_PRIVATE_KEY={private_key}")
        click.echo(
            "\nPaste these into Dashboard → Notifications (or your .env), set a "
            "subject like mailto:admin@yourdomain, and enable push."
        )
