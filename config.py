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

# The insecure default SECRET_KEY. Fine for dev/testing, but production must
# never run with it — ProductionConfig.init_app refuses to start if it does.
PLACEHOLDER_SECRET_KEY = "change-me-in-production"


class Config:
    """Base configuration shared across all environments."""

    # --- Security -------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", PLACEHOLDER_SECRET_KEY)

    @staticmethod
    def init_app(app):
        """Config-specific startup validation hook. No-op by default.

        Called by the app factory after the config is loaded. Subclasses
        override this to enforce environment-specific invariants.
        """

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
    # 2-letter country code hashed into every event's user_data to lift match
    # quality for a single-country audience. Default "pk" (Pakistan) matches the
    # 03XX phone format the form expects; clear or override for other markets.
    META_DEFAULT_COUNTRY = os.environ.get("META_DEFAULT_COUNTRY", "pk")
    # Absolute URL of the landing page, sent as event_source_url. Optional.
    META_EVENT_SOURCE_URL = os.environ.get("META_EVENT_SOURCE_URL", "")
    # Per-request timeout (seconds) so a slow Meta never blocks a lead write.
    META_TIMEOUT = int(os.environ.get("META_TIMEOUT", "10"))
    # Delivery strategy: "sync" sends inline (today). A future background queue
    # registers a new dispatcher in meta_service and this switches to it,
    # without any change to lead_service.
    META_DISPATCH_MODE = os.environ.get("META_DISPATCH_MODE", "sync")

    # --- Pagination -----------------------------------------------------
    LEADS_PER_PAGE = int(os.environ.get("LEADS_PER_PAGE", "20"))

    # --- Media uploads (admin CMS) --------------------------------------
    # Cap upload size so a large file can't exhaust memory/disk. Applies to
    # the whole request body; videos are the practical driver here.
    # Default 64 MB — enough for a compressed 30–60s H.264 clip.
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "64")) * 1024 * 1024

    # --- Session cookies ------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    @staticmethod
    def init_app(app):
        """Config-time hook run by the app factory. No-op by default;
        ProductionConfig overrides it to enforce a safe SECRET_KEY."""


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    # Require HTTPS-only cookies in production (cPanel serves via SSL).
    SESSION_COOKIE_SECURE = True

    @staticmethod
    def init_app(app):
        """Fail fast if the app would run production with an unsafe secret.

        A missing or placeholder SECRET_KEY in production means forgeable
        session cookies and CSRF tokens, so we refuse to start rather than
        boot silently insecure.
        """
        secret = app.config.get("SECRET_KEY")
        if not secret or secret == PLACEHOLDER_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY must be set to a strong, unique value in "
                "production. Set the SECRET_KEY environment variable "
                "(it is currently missing or still the insecure default)."
            )


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
