"""Abstract base model shared by every table.

Centralises the surrogate primary key and the created/updated timestamps so
each concrete model declares only its own domain fields. `__abstract__`
tells SQLAlchemy not to map a table for this class itself.
"""
from datetime import datetime

from app.extensions import db


class BaseModel(db.Model):
    __abstract__ = True

    # Legacy declarative style (db.Column assignment). We deliberately avoid
    # annotating these attributes: SQLAlchemy 2.0 treats any annotated class
    # attribute as a Mapped[] declaration, which conflicts with this style.
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
