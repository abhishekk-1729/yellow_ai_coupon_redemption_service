"""Django settings for the coupon redemption service.

Every environment-dependent value is read from the environment; nothing is
hardcoded. Required values fail fast at import time via ``_require_env``.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _require_env(name: str) -> str:
    """Read a mandatory environment variable.

    Args:
        name: Environment variable name.

    Returns:
        The variable's value.

    Raises:
        ImproperlyConfigured: If the variable is unset or empty.
    """
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(
            f"Missing required environment variable {name!r}. See .env.example."
        )
    return value


def _env_bool(name: str, default: bool) -> bool:
    """Read an optional boolean environment variable.

    Args:
        name: Environment variable name.
        default: Value used when the variable is unset.

    Returns:
        The parsed boolean.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Read an optional integer environment variable.

    Args:
        name: Environment variable name.
        default: Value used when the variable is unset.

    Returns:
        The parsed integer.

    Raises:
        ImproperlyConfigured: If the value is set but not an integer.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}.") from exc


SECRET_KEY = _require_env("DJANGO_SECRET_KEY")
DEBUG = _env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "redemption",
]

MIDDLEWARE = [
    "redemption.observability.correlation.CorrelationIdMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "coupon_service.urls"
WSGI_APPLICATION = "coupon_service.wsgi.application"
TEMPLATES = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _require_env("DB_NAME"),
        "USER": _require_env("DB_USER"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": _require_env("DB_HOST"),
        "PORT": _env_int("DB_PORT", 5432),
        "CONN_MAX_AGE": _env_int("DB_CONN_MAX_AGE", 60),
    }
}

# Transaction boundaries are an explicit part of the service design, so the
# per-request wrapper is deliberately off.
ATOMIC_REQUESTS = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "redemption.api.exception_handler.app_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "redemption.api.renderers.DecimalPreservingJSONRenderer",
    ],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
STATIC_URL = "static/"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "redemption.observability.formatter.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "redemption": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
