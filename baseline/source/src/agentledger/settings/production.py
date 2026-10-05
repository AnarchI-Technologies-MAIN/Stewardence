from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import database_from_url, env_list

DEBUG = False

production_secret = os.getenv("DJANGO_SECRET_KEY", "")
if (
    len(production_secret) < 50
    or len(set(production_secret)) < 5
    or production_secret.startswith("django-insecure-")
):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong production secret")
SECRET_KEY = production_secret

database_url = os.getenv("DATABASE_URL", "")
if not database_url:
    raise ImproperlyConfigured("DATABASE_URL must be present in production")
DATABASES = {"default": database_from_url(database_url)}

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be explicit in production")
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Wildcard ALLOWED_HOSTS is forbidden in production")
if "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS must be explicit in production")
if any(
    not origin.startswith("https://") or origin == "https://" or "*" in origin
    for origin in CSRF_TRUSTED_ORIGINS
):
    raise ImproperlyConfigured(
        "CSRF_TRUSTED_ORIGINS must contain explicit HTTPS origins"
    )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
# Private report object storage.
REPORTS_STORAGE_BACKEND = "s3"

REPORTS_BUCKET_NAME = os.getenv("REPORTS_BUCKET_NAME", "")
REPORTS_BUCKET_ENDPOINT = os.getenv("REPORTS_BUCKET_ENDPOINT", "")
REPORTS_BUCKET_ACCESS_KEY_ID = os.getenv(
    "REPORTS_BUCKET_ACCESS_KEY_ID",
    "",
)
REPORTS_BUCKET_SECRET_ACCESS_KEY = os.getenv(
    "REPORTS_BUCKET_SECRET_ACCESS_KEY",
    "",
)
REPORTS_BUCKET_REGION = os.getenv(
    "REPORTS_BUCKET_REGION",
    "auto",
)
REPORTS_BUCKET_URL_STYLE = os.getenv(
    "REPORTS_BUCKET_URL_STYLE",
    "virtual",
)

for variable_name, value in (
    ("REPORTS_BUCKET_NAME", REPORTS_BUCKET_NAME),
    ("REPORTS_BUCKET_ENDPOINT", REPORTS_BUCKET_ENDPOINT),
    ("REPORTS_BUCKET_ACCESS_KEY_ID", REPORTS_BUCKET_ACCESS_KEY_ID),
    (
        "REPORTS_BUCKET_SECRET_ACCESS_KEY",
        REPORTS_BUCKET_SECRET_ACCESS_KEY,
    ),
):
    if not value:
        raise ImproperlyConfigured(f"{variable_name} must be present in production")

if REPORTS_BUCKET_URL_STYLE not in {"virtual", "path"}:
    raise ImproperlyConfigured("REPORTS_BUCKET_URL_STYLE must be virtual or path")

REPORT_RENDERER_URL = os.getenv("REPORT_RENDERER_URL", "")
if not REPORT_RENDERER_URL:
    raise ImproperlyConfigured("REPORT_RENDERER_URL must be present in production")

REPORT_RENDERER_TIMEOUT_SECONDS = 70
