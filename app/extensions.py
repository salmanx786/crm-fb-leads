"""Flask extension instances.

Kept in their own module so blueprints and models can import them without
triggering circular imports with the app factory.
"""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

# Where to send anonymous users who hit a protected view.
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to access the dashboard."
login_manager.login_message_category = "warning"
