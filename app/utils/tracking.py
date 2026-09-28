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


def get_fbc(request: Any, fallback_fbclid: str | None = None) -> str | None:
    """Meta click id (`fbc`) for the Conversions API.

    Prefer the `_fbc` cookie the Pixel sets. If it is absent but the request
    (query args or form) or session still carries an `fbclid` (first landing,
    before the Pixel has written the cookie), synthesise the value in Meta's
    required format: ``fb.1.<creation_ms>.<fbclid>``.
    """
    cookie_fbc = getattr(request, "cookies", {}).get("_fbc")
    if cookie_fbc:
        return cookie_fbc

    args = getattr(request, "args", {})
    form = getattr(request, "form", {})
    fbclid = args.get("fbclid") or form.get("fbclid") or fallback_fbclid
    if fbclid:
        return f"fb.1.{int(time.time() * 1000)}.{fbclid}"
    return None


def extract_tracking(
    request: Any, fallback: dict[str, Any] | None = None
) -> dict[str, str | None]:
    """Pull UTM params, referrer, IP and user agent from the request.

    Inspects request.form, request.args, and an optional fallback dict
    (e.g. session-persisted attribution) in order of priority, ensuring
    campaign attribution is never lost when moving from landing to POST.
    """
    args = getattr(request, "args", {})
    form = getattr(request, "form", {})
    fallback = fallback or {}

    def _resolve(key: str) -> str | None:
        val = form.get(key) or args.get(key) or fallback.get(key)
        return str(val).strip() if val is not None and str(val).strip() else None

    return {
        "utm_source": _resolve("utm_source"),
        "utm_medium": _resolve("utm_medium"),
        "utm_campaign": _resolve("utm_campaign"),
        "referrer": getattr(request, "referrer", None) or fallback.get("referrer"),
        "ip_address": get_client_ip(request),
        "user_agent": getattr(request, "headers", {}).get("User-Agent") if hasattr(request, "headers") else None,
        # Meta match-quality identifiers (see meta_service.build_payload).
        "fbc": get_fbc(request, fallback.get("fbclid")),
        "fbp": getattr(request, "cookies", {}).get("_fbp") or fallback.get("fbp"),
    }

