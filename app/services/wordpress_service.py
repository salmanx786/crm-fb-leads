"""Server-side client for the MC College WordPress CRM API."""
from __future__ import annotations

from typing import Any
import requests
from flask import current_app


class WordPressAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


STATUS_CHOICES = (
    ("new", "New"),
    ("called", "Called"),
    ("interested", "Interested"),
    ("not_interested", "Not Interested"),
    ("visited", "Visited"),
    ("completed", "Completed"),
)


def status_choices():
    return list(STATUS_CHOICES)


def _request(method: str, path: str, **kwargs: Any) -> requests.Response:
    base_url = current_app.config["WP_CRM_API_URL"].rstrip("/")
    api_key = current_app.config.get("WP_CRM_API_KEY", "")
    timeout = current_app.config.get("WP_CRM_TIMEOUT", 10)
    if not api_key:
        raise WordPressAPIError("WordPress CRM API is not configured. Set WP_CRM_API_KEY.")

    headers = {"Accept": "application/json", "X-MC-CRM-Key": api_key}
    headers.update(kwargs.pop("headers", {}))

    try:
        response = requests.request(
            method, f"{base_url}/{path.lstrip('/')}",
            headers=headers, timeout=timeout, **kwargs
        )
    except requests.RequestException as exc:
        raise WordPressAPIError("Could not connect to the WordPress CRM API.") from exc

    if response.status_code >= 400:
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("message", "")
        except ValueError:
            pass
        if response.status_code == 404:
            raise WordPressAPIError("WordPress lead was not found.", 404)
        if response.status_code in (401, 403):
            raise WordPressAPIError("WordPress CRM authentication failed.", response.status_code)
        raise WordPressAPIError(
            detail or "WordPress CRM API request failed.", response.status_code
        )
    return response


def _json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise WordPressAPIError("WordPress returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise WordPressAPIError("WordPress returned an unexpected response.")
    return payload


def list_leads(*, page=1, per_page=20, status=None, search=None) -> dict:
    params = {"page": max(page, 1), "per_page": min(max(per_page, 1), 100)}
    if status:
        params["status"] = status
    if search:
        params["search"] = search
    return _json(_request("GET", "leads", params=params))


def get_lead(entry_id: int) -> dict:
    return _json(_request("GET", f"leads/{int(entry_id)}"))


def update_status(entry_id: int, status: str) -> dict:
    allowed = {value for value, _label in STATUS_CHOICES}
    if status not in allowed:
        raise WordPressAPIError("Invalid WordPress lead status.")
    return _json(_request("PATCH", f"leads/{int(entry_id)}", json={"status": status}))
