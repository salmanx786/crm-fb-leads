"""Tests for request attribution extraction (app.utils.tracking).

Focus on the Meta match-quality identifiers (fbc/fbp): reading the Pixel's
``_fbc``/``_fbp`` cookies and synthesising ``fbc`` from an ``fbclid`` query
param when the cookie has not been set yet.
"""
from types import SimpleNamespace

from app.utils.tracking import extract_tracking, get_fbc


def _request(cookies=None, args=None, headers=None):
    """A minimal duck-typed stand-in for a Flask request."""
    return SimpleNamespace(
        cookies=cookies or {},
        args=args or {},
        headers=headers or {},
        referrer=None,
        remote_addr="203.0.113.7",
    )


def test_get_fbc_prefers_cookie():
    req = _request(cookies={"_fbc": "fb.1.123.cookieval"},
                   args={"fbclid": "shouldbeignored"})
    assert get_fbc(req) == "fb.1.123.cookieval"


def test_get_fbc_synthesises_from_fbclid():
    req = _request(args={"fbclid": "abc123"})
    fbc = get_fbc(req)
    assert fbc is not None
    parts = fbc.split(".")
    assert parts[0] == "fb" and parts[1] == "1" and parts[3] == "abc123"
    assert parts[2].isdigit()  # creation timestamp in ms


def test_get_fbc_none_when_absent():
    assert get_fbc(_request()) is None


def test_extract_tracking_includes_fbc_and_fbp():
    req = _request(
        cookies={"_fbc": "fb.1.123.x", "_fbp": "fb.1.456.y"},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    tracking = extract_tracking(req)
    assert tracking["fbc"] == "fb.1.123.x"
    assert tracking["fbp"] == "fb.1.456.y"
    assert tracking["user_agent"] == "Mozilla/5.0"
