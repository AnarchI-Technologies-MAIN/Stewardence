from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parents[3]


def env_list(name: str, default: str = "") -> list[str]:
    return [
        value.strip() for value in os.getenv(name, default).split(",") if value.strip()
    ]


def database_from_url(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use the postgresql scheme")
    if not parsed.hostname or not parsed.path.removeprefix("/"):
        raise ValueError("DATABASE_URL must identify a host and database")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.removeprefix("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 0,
    }


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "agentledger-development-only-key")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
    "apps.billing.apps.BillingConfig",
    "apps.organizations.apps.OrganizationsConfig",
    "apps.inventory.apps.InventoryConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.imports.apps.ImportsConfig",
    "apps.policies.apps.PoliciesConfig",
    "apps.roi.apps.RoiConfig",
    "apps.assessments.apps.AssessmentsConfig",
    "apps.jobs.apps.JobsConfig",
    "apps.audit.apps.AuditConfig",
    "apps.reports.apps.ReportsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.billing.middleware.BillingEntitlementMiddleware",
    "agentledger.tenancy.middleware.TenantContextResolutionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "agentledger.urls"
WSGI_APPLICATION = "agentledger.wsgi.application"

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
            ]
        },
    }
]

DATABASES = {
    "default": database_from_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql://agentledger:agentledger@127.0.0.1:55439/agentledger_dev",
        )
    )
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        )
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "organizations:workspace-selection"
LOGOUT_REDIRECT_URL = "accounts:login"

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_BILLING_PORTAL_CONFIGURATION_ID = os.getenv(
    "STRIPE_BILLING_PORTAL_CONFIGURATION_ID",
    "",
)

STRIPE_BILLING_PORTAL_FOUNDER_CONFIGURATION_ID = os.getenv(
    "STRIPE_BILLING_PORTAL_FOUNDER_CONFIGURATION_ID",
    "",
)

STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = os.getenv(
    "STRIPE_CORE_FOUNDER_INTRO_PRICE_ID",
    "",
)

STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = os.getenv(
    "STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID",
    "",
)

STRIPE_CORE_STANDARD_PRICE_ID = os.getenv(
    "STRIPE_CORE_STANDARD_PRICE_ID",
    "",
)
