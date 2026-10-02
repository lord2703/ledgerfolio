"""Django settings for Ledgerfolio.

Every secret and machine-specific value comes from environment variables
(loaded from `.env` in development). Nothing sensitive is hardcoded here.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "tracker",
    "ledger",
    "showcase",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "showcase.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("DB_NAME", default="ledgerfolio"),
        "USER": env("DB_USER", default="root"),
        "PASSWORD": env("DB_PASSWORD", default=""),
        "HOST": env("DB_HOST", default="127.0.0.1"),
        "PORT": env("DB_PORT", default="3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="Asia/Manila")
USE_I18N = True
USE_TZ = True

# --- Files ------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Public uploads: project screenshots shown on the Showcase.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Private files: receipt PDFs. Never served by a public URL; only staff can
# download them through the admin.
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"

# --- Cache (shared between workers, used by the chat rate limit) --------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "var" / "cache",
    }
}

# --- Email --------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = 20
EMAIL_FILE_PATH = BASE_DIR / "var" / "sent_emails"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Ledgerfolio <noreply@localhost>")

# --- REST framework (chat endpoint) --------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_RATES": {"chat": env("CHAT_RATE_LIMIT", default="20/min")},
    "UNAUTHENTICATED_USER": None,
}

# --- Site identity (shown on the Showcase, receipts and emails) ----------
SITE_NAME = env("SITE_NAME", default="Ledgerfolio")
# Public base URL, used to build the verify links and QR codes on receipts.
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
ADMIN_URL = env("ADMIN_URL", default="admin/")
OWNER_NAME = env("OWNER_NAME", default="Lord")
OWNER_TITLE = env("OWNER_TITLE", default="Freelance Systems Developer")
OWNER_EMAIL = env("OWNER_EMAIL", default="")
OWNER_PHONE = env("OWNER_PHONE", default="")
OWNER_LOCATION = env("OWNER_LOCATION", default="Philippines")
CURRENCY_CODE = env("CURRENCY_CODE", default="PHP")
# Spec section 13 (still open): show the amount on the public verify page?
VERIFY_SHOW_AMOUNT = env.bool("VERIFY_SHOW_AMOUNT", default=True)

# --- Blockchain ledger ----------------------------------------------------
CHAIN_NODE_URL = env("CHAIN_NODE_URL", default="http://127.0.0.1:8001").rstrip("/")
CHAIN_NODE_TIMEOUT = env.float("CHAIN_NODE_TIMEOUT", default=5.0)
# Seconds to wait for a new receipt transaction to be mined into a block.
CHAIN_CONFIRM_TIMEOUT = env.float("CHAIN_CONFIRM_TIMEOUT", default=10.0)
# The issuer wallet's private key. Use ONE of these. Keep it outside the repo,
# never log it, and back it up: without it no new receipts can be signed.
ISSUER_PRIVATE_KEY = env("ISSUER_PRIVATE_KEY", default="")
ISSUER_KEY_FILE = env("ISSUER_KEY_FILE", default="")

# --- AI assistant ----------------------------------------------------------
AI_ARTIFACTS_DIR = BASE_DIR / "ai" / "artifacts"
AI_CONFIDENCE_THRESHOLD = env.float("AI_CONFIDENCE_THRESHOLD", default=0.55)

# --- Production hardening (active when DEBUG is off) ------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "tracker": {"level": "INFO"},
        "ledger": {"level": "INFO"},
        "showcase": {"level": "INFO"},
    },
}
