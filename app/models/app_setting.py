"""Editable application settings, managed from the admin dashboard.

A small key/value store for operational configuration an admin changes at
runtime (currently the Meta Conversions API integration). Kept separate from
``SiteContent`` — that table is the marketing-content CMS and documents that it
never holds secrets, whereas this table intentionally may (the Meta access
token). Values are stored as strings; the settings service owns coercion and
which keys exist.
"""
from app.extensions import db
from app.models.base import BaseModel


class AppSetting(BaseModel):
    """One admin-editable setting. `key` is a stable identifier, `value` the
    stored string (NULL means "never set" — the reader falls back to env)."""

    __tablename__ = "app_settings"

    key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    value = db.Column(db.String(1024), nullable=True)
