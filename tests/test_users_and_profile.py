"""Tests for user management and profile settings."""
import re
import pytest
from app.extensions import db
from app.models import User
from app.services import user_service

_CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="csrf_token"')


def _csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match, "CSRF token not found"
    return match.group(1) or match.group(2)


@pytest.fixture()
def admin(app):
    """A persisted admin user."""
    return user_service.create_admin("Admin User", "admin@mc.edu", "s3cret-pass")


@pytest.fixture()
def second_user(app):
    """Create a second user in the database."""
    with app.app_context():
        u = user_service.create_user(
            name="Counselor Bilal",
            email="bilal@mccollege.edu.pk",
            password="password123",
            role="counselor",
        )
        return u.id


def _login(client, email="admin@mc.edu", password="s3cret-pass"):
    token = _csrf(client.get("/login").get_data(as_text=True))
    resp = client.post(
        "/login",
        data={"csrf_token": token, "email": email, "password": password},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_list_users(app, admin, second_user):
    with app.app_context():
        users = user_service.list_users()
        assert len(users) >= 2
        emails = [u.email for u in users]
        assert "admin@mc.edu" in emails
        assert "bilal@mccollege.edu.pk" in emails


def test_create_user_success(app):
    with app.app_context():
        user = user_service.create_user(
            name="Sana Tariq",
            email="sana@mccollege.edu.pk",
            password="secretpassword",
            role="counselor",
        )
        assert user.id is not None
        assert user.name == "Sana Tariq"
        assert user.email == "sana@mccollege.edu.pk"
        assert user.role == "counselor"
        assert user.is_active is True
        assert user.check_password("secretpassword") is True


def test_create_user_duplicate_email_rejected(app, admin):
    with app.app_context():
        with pytest.raises(user_service.UserAlreadyExistsError):
            user_service.create_user(
                name="Duplicate Admin",
                email="admin@mc.edu",
                password="newpassword",
            )


def test_toggle_user_active_prevents_self(app, admin):
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(email="admin@mc.edu"))
        with pytest.raises(user_service.UserOperationError, match="cannot deactivate your own account"):
            user_service.toggle_user_active(user.id, current_user_id=user.id)


def test_toggle_user_active_success(app, second_user, admin):
    with app.app_context():
        active = user_service.toggle_user_active(second_user, current_user_id=admin.id)
        assert active is False
        u = user_service.get_user(second_user)
        assert u.is_active is False

        active = user_service.toggle_user_active(second_user, current_user_id=admin.id)
        assert active is True
        u = user_service.get_user(second_user)
        assert u.is_active is True


def test_admin_reset_password(app, second_user):
    with app.app_context():
        user = user_service.get_user(second_user)
        user_service.change_password(user, new_password="newbrandpassword123", is_admin_reset=True)
        assert user.check_password("newbrandpassword123") is True


def test_user_self_change_password(app, second_user):
    with app.app_context():
        user = user_service.get_user(second_user)
        with pytest.raises(ValueError, match="Current password is incorrect"):
            user_service.change_password(user, new_password="newpassword123", old_password="wrongpassword")

        user_service.change_password(user, new_password="newpassword123", old_password="password123")
        assert user.check_password("newpassword123") is True


def test_update_profile(app, second_user):
    with app.app_context():
        user = user_service.get_user(second_user)
        user_service.update_profile(user, name="Bilal Khan", email="bilal.khan@mccollege.edu.pk")
        assert user.name == "Bilal Khan"
        assert user.email == "bilal.khan@mccollege.edu.pk"


def test_users_routes_authenticated(client, admin, second_user):
    _login(client)

    # Users list
    resp = client.get("/dashboard/users")
    assert resp.status_code == 200
    assert "Users & Staff" in resp.get_data(as_text=True)
    assert "bilal@mccollege.edu.pk" in resp.get_data(as_text=True)

    # Profile page
    resp = client.get("/dashboard/profile")
    assert resp.status_code == 200
    assert "Account Profile" in resp.get_data(as_text=True)


def test_create_user_via_route(client, admin, app):
    _login(client)
    html = client.get("/dashboard/users/new").get_data(as_text=True)
    token = _csrf(html)
    resp = client.post(
        "/dashboard/users/new",
        data={
            "csrf_token": token,
            "name": "Khadija Bibi",
            "email": "khadija@mccollege.edu.pk",
            "password": "strongpassword123",
            "role": "counselor",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Khadija Bibi" in resp.get_data(as_text=True)
    with app.app_context():
        u = user_service.get_by_email("khadija@mccollege.edu.pk")
        assert u is not None
        assert u.role == "counselor"
