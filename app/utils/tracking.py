"""Extract attribution and request metadata from an incoming request.

Isolated here so the lead service stays focused on business logic and does
not need to know how Flask exposes headers, proxies, or query strings.
"""
from typing import Any


def get_client_ip(request: Any) -> str | None:
    """Best-effort client IP, honouring a single proxy hop (cPanel/Apache)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # First entry is the original client.
        return forwarded.split(",")[0].strip()
    return request.remote_addr


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
    }
