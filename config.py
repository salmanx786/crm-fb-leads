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
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

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

    # --- Web Push notifications (VAPID) ---------------------------------
    # Browser push to logged-in admins. Disabled by default; enable per env or
    # from the dashboard. Generate a key pair with `flask generate-vapid-keys`.
    PUSH_ENABLED = os.environ.get("PUSH_ENABLED", "False").lower() in ("1", "true", "yes")
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
    # Contact URI sent to push services with each request (spec requires a
    # mailto: or https: subject). e.g. "mailto:admin@mccollege.example".
    VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "")
    # Per-request timeout (seconds) so a slow push service never stalls a
    # request; mirrors META_TIMEOUT.
    PUSH_TIMEOUT = int(os.environ.get("PUSH_TIMEOUT", "10"))

    # --- Transactional email (SMTP) -------------------------------------
    # Applicant confirmation email on new lead. Disabled by default; enable per
    # env or from the dashboard. Defaults target Google Workspace SMTP, which
    # needs an *App Password* (account 2FA on) or the Workspace SMTP relay — the
    # ordinary account password is rejected. MAIL_FROM should be on the same
    # Workspace domain as MAIL_USERNAME so existing SPF/DKIM covers it.
    MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "False").lower() in ("1", "true", "yes")
    MAIL_SMTP_HOST = os.environ.get("MAIL_SMTP_HOST", "smtp.gmail.com")
    MAIL_SMTP_PORT = int(os.environ.get("MAIL_SMTP_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    # Envelope/From address. Falls back to MAIL_USERNAME when blank.
    MAIL_FROM = os.environ.get("MAIL_FROM", "")
    # Per-request timeout (seconds) so a slow SMTP never stalls a lead write;
    # mirrors META_TIMEOUT / PUSH_TIMEOUT.
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "10"))

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
