"""User/admin business logic.

Keeps user creation and lookup out of the routes and CLI so the same rules
(unique email, password hashing) apply wherever an admin is created.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.extensions import db
from app.models import User
from app.utils.helpers import clean_str, normalize_email


class UserAlreadyExistsError(ValueError):
    """Raised when creating a user whose email is already registered."""


def get_by_email(email: str) -> Optional[User]:
    """Look up a user by (normalised) email, or None."""
    email = normalize_email(email)
    if not email:
        return None
    return db.session.scalar(select(User).filter_by(email=email))


def create_admin(name: str, email: str, password: str) -> User:
    """Create an administrator. Raises UserAlreadyExistsError on duplicate email."""
    name = clean_str(name, 120)
    email = normalize_email(email)

    if get_by_email(email):
        raise UserAlreadyExistsError(f"A user with email {email} already exists.")

    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user
