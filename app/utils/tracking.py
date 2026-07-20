"""Extract attribution and request metadata from an incoming request.

Isolated here so the lead service stays focused on business logic and does
not need to know how Flask exposes headers, proxies, or query strings.
"""
from __future__ import annotations  # 3.9-safe PEP 604 unions in annotations

import time
from typing import Any


def get_client_ip(request: Any) -> str | None:
    """Best-effort client IP, honouring a single proxy hop (cPanel/Apache)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # First entry is the original client.
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def get_fbc(request: Any) -> str | None:
    """Meta click id (`fbc`) for the Conversions API.

    Prefer the `_fbc` cookie the Pixel sets. If it is absent but the URL still
    carries an `fbclid` (first landing, before the Pixel has written the
    cookie), synthesise the value in Meta's required format:
    ``fb.1.<creation_ms>.<fbclid>``.
    """
    cookie_fbc = request.cookies.get("_fbc")
    if cookie_fbc:
        return cookie_fbc
    fbclid = request.args.get("fbclid")
    if fbclid:
        return f"fb.1.{int(time.time() * 1000)}.{fbclid}"
    return None


def extract_tracking(request: Any) -> dict[str, str | None]:
    """Pull UTM params, referrer, IP and user agent from the request.

    Returns a dict whose keys match the tracking columns on the Lead model,
    so it can be splatted straight into lead creation.
    """
    args = request.args
    return {
        "utm_source": args.get("utm_source"),
        "utm_medium": args.get("utm_medium"),
        "utm_campaign": args.get("utm_campaign"),
        "referrer": request.referrer,
        "ip_address": get_client_ip(request),
        "user_agent": request.headers.get("User-Agent"),
        # Meta match-quality identifiers (see meta_service.build_payload).
        "fbc": get_fbc(request),
        "fbp": request.cookies.get("_fbp"),
    }
