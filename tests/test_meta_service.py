"""Tests for the Meta Conversions API service.

All HTTP is mocked — these tests never contact Meta. We monkeypatch
``meta_service.requests.post`` so payload building, hashing, persistence, and
the retry loop are exercised end-to-end against the in-memory database.

Covers: payload generation, PII hashing, successful send, failed send, retry
of failed events, and MetaEvent persistence.
"""
import hashlib
import json

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Lead, MetaEvent
from app.services import lead_service, meta_service


# --- helpers --------------------------------------------------------------

class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"events_received": 1}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


@pytest.fixture()
def meta_on(app):
    """Enable Meta on the app config for the duration of a test."""
    app.config["META_ENABLED"] = True
    app.config["META_PIXEL_ID"] = "1234567890"
    app.config["META_ACCESS_TOKEN"] = "test-token"
    app.config["META_TEST_EVENT_CODE"] = "TEST123"
    yield app


@pytest.fixture()
def a_lead(app):
    """A lead created directly (Meta disabled here, so no event is fired)."""
    return Lead(
        name="Asha Verma",
        phone="+91 98765 43210",
        email="Asha@Example.com",
        course="MBA",
        status="New",
    )


# --- hashing --------------------------------------------------------------

def test_hash_user_data_hashes_email_and_phone(meta_on, a_lead):
    db.session.add(a_lead)
    db.session.commit()

    user_data = meta_service.hash_user_data(a_lead)

    # Email: lowercased + trimmed then sha256.
    expected_email = hashlib.sha256("asha@example.com".encode()).hexdigest()
    # Phone: digits only then sha256.
    expected_phone = hashlib.sha256("919876543210".encode()).hexdigest()

    assert user_data["em"] == [expected_email]
    assert user_data["ph"] == [expected_phone]
    # Raw PII must never appear in the hashed block.
    serialized = json.dumps(user_data)
    assert "asha@example.com" not in serialized
    assert "9876543210" not in serialized


# --- payload --------------------------------------------------------------

def test_build_payload_shape(meta_on, a_lead):
    db.session.add(a_lead)
    db.session.commit()

    payload = meta_service.build_payload(a_lead, "Lead", "evt-123", event_time=1_700_000_000)

    assert payload["data"][0]["event_name"] == "Lead"
    assert payload["data"][0]["event_id"] == "evt-123"
    assert payload["data"][0]["event_time"] == 1_700_000_000
    assert payload["data"][0]["action_source"] == "website"
    assert "em" in payload["data"][0]["user_data"]
    # Test event code from config is included.
    assert payload["test_event_code"] == "TEST123"


# --- successful send ------------------------------------------------------

def test_track_event_success_persists_sent(meta_on, a_lead, monkeypatch):
    db.session.add(a_lead)
    db.session.commit()

    monkeypatch.setattr(
        meta_service.requests, "post", lambda *a, **k: _FakeResponse(200)
    )

    event = meta_service.track_event(a_lead, "lead_created")

    assert event is not None
    assert event.status == "sent"
    assert event.sent_at is not None
    assert event.event_name == "Lead"
    # Persisted.
    stored = db.session.get(MetaEvent, event.id)
    assert stored.status == "sent"


def test_untracked_trigger_sends_nothing(meta_on, a_lead, monkeypatch):
    db.session.add(a_lead)
    db.session.commit()
    monkeypatch.setattr(
        meta_service.requests, "post", lambda *a, **k: _FakeResponse(200)
    )

    # "Called" is not in META_EVENT_MAP.
    assert meta_service.track_event(a_lead, "Called") is None
    assert db.session.scalar(select(func.count(MetaEvent.id))) == 0


def test_disabled_meta_sends_nothing(app, a_lead, monkeypatch):
    app.config["META_ENABLED"] = False
    db.session.add(a_lead)
    db.session.commit()

    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return _FakeResponse(200)

    monkeypatch.setattr(meta_service.requests, "post", _boom)

    assert meta_service.track_event(a_lead, "lead_created") is None
    assert called["n"] == 0  # never even attempted the HTTP call


# --- failed send ----------------------------------------------------------

def test_track_event_failure_persists_failed(meta_on, a_lead, monkeypatch):
    db.session.add(a_lead)
    db.session.commit()

    monkeypatch.setattr(
        meta_service.requests,
        "post",
        lambda *a, **k: _FakeResponse(400, {"error": {"message": "bad"}}),
    )

    event = meta_service.track_event(a_lead, "lead_created")

    assert event is not None
    assert event.status == "failed"
    assert event.sent_at is None
    # The failure response is stored so we can inspect it later.
    assert "bad" in event.response_payload


def test_network_error_is_caught_and_marked_failed(meta_on, a_lead, monkeypatch):
    import requests as real_requests

    db.session.add(a_lead)
    db.session.commit()

    def _raise(*a, **k):
        raise real_requests.RequestException("connection reset")

    monkeypatch.setattr(meta_service.requests, "post", _raise)

    event = meta_service.track_event(a_lead, "lead_created")
    assert event.status == "failed"
    assert "connection reset" in event.response_payload


# --- retry ----------------------------------------------------------------

def test_retry_failed_events_resends_only_failed(meta_on, a_lead, monkeypatch):
    db.session.add(a_lead)
    db.session.commit()

    # First attempt fails.
    monkeypatch.setattr(
        meta_service.requests, "post", lambda *a, **k: _FakeResponse(500, {"error": "x"})
    )
    event = meta_service.track_event(a_lead, "lead_created")
    original_event_id = event.event_id
    assert event.status == "failed"

    # Now the endpoint recovers; retry should flip it to sent.
    monkeypatch.setattr(
        meta_service.requests, "post", lambda *a, **k: _FakeResponse(200)
    )
    summary = meta_service.retry_failed_events()

    assert summary == {"retried": 1, "sent": 1, "failed": 0}
    refreshed = db.session.get(MetaEvent, event.id)
    assert refreshed.status == "sent"
    # Same event_id is reused so Meta deduplicates.
    assert refreshed.event_id == original_event_id


def test_retry_skips_sent_events(meta_on, a_lead, monkeypatch):
    db.session.add(a_lead)
    db.session.commit()

    calls = {"n": 0}

    def _count(*a, **k):
        calls["n"] += 1
        return _FakeResponse(200)

    monkeypatch.setattr(meta_service.requests, "post", _count)

    meta_service.track_event(a_lead, "lead_created")  # 1 call, sent
    assert calls["n"] == 1

    summary = meta_service.retry_failed_events()
    # No failed rows, so no additional HTTP calls.
    assert calls["n"] == 1
    assert summary["retried"] == 0


# --- integration through lead_service -------------------------------------

def test_status_change_to_admitted_fires_event(meta_on, monkeypatch):
    monkeypatch.setattr(
        meta_service.requests, "post", lambda *a, **k: _FakeResponse(200)
    )

    lead = lead_service.create_lead(
        {"name": "Rohan Das", "phone": "+91 90000 00000", "email": "r@example.com"}
    )
    # create_lead fired "lead_created" -> "Lead".
    assert db.session.scalar(select(func.count(MetaEvent.id))) == 1

    lead_service.change_status(lead, "Admitted")
    events = db.session.scalars(select(MetaEvent).order_by(MetaEvent.id)).all()
    names = [e.event_name for e in events]
    assert "CompleteRegistration" in names
    assert all(e.status == "sent" for e in events)


# --- dispatcher abstraction (sync today, queue-able later) ----------------

def test_track_event_delegates_to_active_dispatcher(meta_on, a_lead, monkeypatch):
    """track_event hands the persisted row id to the dispatcher, without
    caring how delivery happens. A custom dispatcher that does nothing proves
    the event stays `pending` — i.e. delivery is fully the dispatcher's call."""
    monkeypatch.setattr(
        meta_service.requests, "post", lambda *a, **k: _FakeResponse(200)
    )
    db.session.add(a_lead)
    db.session.commit()

    seen: dict[str, int] = {}

    class _CapturingDispatcher(meta_service.MetaDispatcher):
        def dispatch(self, meta_event_id: int) -> None:
            seen["id"] = meta_event_id  # e.g. a queue would enqueue this id

    meta_service.set_dispatcher(_CapturingDispatcher())
    try:
        event = meta_service.track_event(a_lead, "lead_created")
    finally:
        meta_service.set_dispatcher(None)  # restore config-based selection

    # The dispatcher received the persisted row id...
    assert seen["id"] == event.id
    # ...and because our dispatcher didn't deliver, the row is still pending.
    assert event.status == "pending"
    # No HTTP happened either — delivery never ran.
    refreshed = db.session.get(MetaEvent, event.id)
    assert refreshed.status == "pending"


def test_deliver_now_delivers_a_pending_event(meta_on, a_lead, monkeypatch):
    """A queue worker's unit of work: deliver_now(id) reloads and sends."""
    monkeypatch.setattr(
        meta_service.requests, "post", lambda *a, **k: _FakeResponse(200)
    )
    db.session.add(a_lead)
    db.session.commit()

    # Persist a pending event via a no-op dispatcher, then deliver it by id.
    meta_service.set_dispatcher(meta_service.MetaDispatcher())  # dispatch() raises if called
    try:
        # MetaDispatcher.dispatch raises NotImplementedError; use a silent one.
        class _Noop(meta_service.MetaDispatcher):
            def dispatch(self, meta_event_id: int) -> None:
                pass

        meta_service.set_dispatcher(_Noop())
        event = meta_service.track_event(a_lead, "lead_created")
        assert event.status == "pending"

        delivered = meta_service.deliver_now(event.id)
    finally:
        meta_service.set_dispatcher(None)

    assert delivered.status == "sent"
    assert delivered.sent_at is not None
