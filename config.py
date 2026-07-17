"""Application configuration.

All secrets and environment-specific values are read from environment
variables (loaded from a .env file in development). Nothing sensitive is
hard-coded, which keeps the same codebase safe to deploy on shared hosting.
"""
import os
from dotenv import load_dotenv

# Load variables from a .env file if present (development convenience).
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared across all environments."""

    # --- Security -------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

    # WTForms CSRF protection is on by default; make the token last a day.
    WTF_CSRF_TIME_LIMIT = 86400

    # --- Database -------------------------------------------------------
    # Built from discrete parts so it's easy to fill in via cPanel.
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "3306")
    DB_NAME = os.environ.get("DB_NAME", "mc_leads")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Recycle connections before shared-hosting MySQL drops idle ones.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 280,
        "pool_pre_ping": True,
    }

    # --- Meta (Facebook) Conversions API --------------------------------
    # Server-side conversion events. Disabled by default; enable per env.
    META_ENABLED = os.environ.get("META_ENABLED", "False").lower() in ("1", "true", "yes")
    META_PIXEL_ID = os.environ.get("META_PIXEL_ID", "")
    META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
    # Optional: routes events to Meta's Test Events tool when set.
    META_TEST_EVENT_CODE = os.environ.get("META_TEST_EVENT_CODE", "")
    # Graph API version used to build the endpoint URL.
    META_API_VERSION = os.environ.get("META_API_VERSION", "v19.0")
    # Per-request timeout (seconds) so a slow Meta never blocks a lead write.
    META_TIMEOUT = int(os.environ.get("META_TIMEOUT", "10"))
    # Delivery strategy: "sync" sends inline (today). A future background queue
    # registers a new dispatcher in meta_service and this switches to it,
    # without any change to lead_service.
    META_DISPATCH_MODE = os.environ.get("META_DISPATCH_MODE", "sync")

    # --- Pagination -----------------------------------------------------
    LEADS_PER_PAGE = int(os.environ.get("LEADS_PER_PAGE", "20"))

    # --- Session cookies ------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    # Require HTTPS-only cookies in production (cPanel serves via SSL).
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    # In-memory SQLite keeps tests fast and isolated from MySQL.
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}  # pool options above don't apply to SQLite
    WTF_CSRF_ENABLED = True  # keep CSRF on so tests exercise the real token flow


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
