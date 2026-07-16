from typing import Optional

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app.models.base import BaseModel


class User(UserMixin, BaseModel):
    """Admin user who can access the dashboard."""

    __tablename__ = "users"

    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active_flag = db.Column("is_active", db.Boolean, default=True, nullable=False)

    def set_password(self, password: str) -> None:
        # pbkdf2:sha256 is available in every Python/OpenSSL build (unlike
        # scrypt, Werkzeug's default), so hashing works on shared hosting.
        self.password_hash = generate_password_hash(
            password, method="pbkdf2:sha256"
        )

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self) -> bool:  # used by Flask-Login
        return self.is_active_flag

    def __repr__(self) -> str:
        return f"<User {self.email}>"


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    return db.session.get(User, int(user_id))
