"""Tests for the browser Meta Pixel injected in base.html.

The pixel is gated on Meta being enabled (settings_service.META_ENABLED) with
a configured pixel id, so dev and test environments stay silent by default.
When it renders, the `eventID` passed to fbq must be a fresh id per request so
a browser event can be deduplicated against the matching server-side
Conversions API event.
"""
import re


def test_pixel_absent_by_default(client):
    """With Meta disabled (the testing default), the pixel must not render."""
    html = client.get("/").get_data(as_text=True)
    assert "fbq(" not in html
    assert "connect.facebook.net" not in html


def test_pixel_absent_when_enabled_without_id(app, client):
    """Enabled but no pixel id -> nothing to init, so stay silent."""
    app.config["META_ENABLED"] = True
    app.config["META_PIXEL_ID"] = ""
    html = client.get("/").get_data(as_text=True)
    assert "fbq(" not in html


def test_pixel_renders_when_enabled_and_configured(app, client):
    """When Meta is enabled with a pixel id, the pixel initialises with that
    id and tracks a PageView carrying a per-request eventID (camelCase: the
    browser dedup key, distinct from the server-side 'event_id' field)."""
    app.config["META_ENABLED"] = True
    app.config["META_PIXEL_ID"] = "1081042617927757"

    html = client.get("/").get_data(as_text=True)

    assert "connect.facebook.net/en_US/fbevents.js" in html
    assert "fbq('init', '1081042617927757')" in html
    # The noscript fallback carries the same id.
    assert "tr?id=1081042617927757" in html

    match = re.search(
        r"fbq\('track', 'PageView', \{\}, \{eventID: '([0-9a-f]{32})'\}\)", html
    )
    assert match, "PageView must pass a hex eventID for browser/server dedup"


def test_event_id_differs_per_request(app, client):
    """Each request mints a distinct event_id so it maps 1:1 to its own
    server-side event rather than collapsing many hits into one."""
    app.config["META_ENABLED"] = True
    app.config["META_PIXEL_ID"] = "1081042617927757"
    pattern = re.compile(r"eventID: '([0-9a-f]{32})'")

    first = pattern.search(client.get("/").get_data(as_text=True)).group(1)
    second = pattern.search(client.get("/").get_data(as_text=True)).group(1)

    assert first != second
