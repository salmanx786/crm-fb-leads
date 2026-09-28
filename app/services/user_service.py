"""User/admin business logic.

Keeps user creation, lookup, and updates out of the routes and CLI so the
same rules (unique email, password hashing, active checks) apply everywhere.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.extensions import db
from app.models import User
from app.utils.helpers import clean_str, normalize_email


class UserAlreadyExistsError(ValueError):
    """Raised when creating or updating a user whose email is already registered."""


class UserOperationError(ValueError):
    """Raised for invalid user operations (e.g. self-deactivation)."""


def get_by_email(email: str) -> Optional[User]:
    """Look up a user by (normalised) email, or None."""
    email = normalize_email(email)
    if not email:
        return None
    return db.session.scalar(select(User).filter_by(email=email))


def get_user(user_id: int) -> Optional[User]:
    """Look up a user by primary key id, or None."""
    return db.session.get(User, user_id)


def list_users() -> list[User]:
    """Return all users ordered by creation date."""
    return list(db.session.scalars(select(User).order_by(User.created_at.asc())).all())


def create_user(name: str, email: str, password: str, role: str = "admin") -> User:
    """Create a user with specified role. Raises UserAlreadyExistsError on duplicate email."""
    name = clean_str(name, 120)
    email = normalize_email(email)
    if not name or not email or not password:
        raise ValueError("Name, email, and password are required.")

    if get_by_email(email):
        raise UserAlreadyExistsError(f"A user with email '{email}' already exists.")

    user = User(name=name, email=email, role=role if role in ("admin", "counselor") else "admin")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def create_admin(name: str, email: str, password: str) -> User:
    """Create an administrator. Alias for create_user with role='admin'."""
    return create_user(name=name, email=email, password=password, role="admin")


def update_profile(user: User, name: str, email: str) -> User:
    """Update a user's name and email. Checks for email collision."""
    name = clean_str(name, 120)
    email = normalize_email(email)
    if not name or not email:
        raise ValueError("Name and email are required.")

    if email != user.email:
        existing = get_by_email(email)
        if existing and existing.id != user.id:
            raise UserAlreadyExistsError(f"Email '{email}' is already in use by another account.")

    user.name = name
    user.email = email
    db.session.commit()
    return user


def change_password(
    user: User,
    new_password: str,
    old_password: Optional[str] = None,
    is_admin_reset: bool = False,
) -> None:
    """Change user password. Checks old_password unless is_admin_reset is True."""
    if not is_admin_reset:
        if not old_password or not user.check_password(old_password):
            raise ValueError("Current password is incorrect.")

    if not new_password or len(new_password) < 6:
        raise ValueError("New password must be at least 6 characters long.")

    user.set_password(new_password)
    db.session.commit()


def toggle_user_active(user_id: int, current_user_id: int) -> bool:
    """Toggle a user's active status. Cannot deactivate oneself."""
    if user_id == current_user_id:
        raise UserOperationError("You cannot deactivate your own account.")

    user = get_user(user_id)
    if not user:
        raise ValueError(f"User #{user_id} not found.")

    user.is_active_flag = not user.is_active_flag
    db.session.commit()
    return user.is_active_flag
