"""Isolated process settings: one admission-owned database, no webapp aliases."""
import os
from django.core.exceptions import ImproperlyConfigured
from .base import *  # noqa: F403
from .base import database_from_url, env_list

DEBUG = False
ROOT_URLCONF = "agentledger.billing_urls"
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware"]
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("Dedicated service secret required")
service_database = os.getenv("BILLING_ADMISSION_DATABASE_URL", "")
if not service_database:
    raise ImproperlyConfigured("Dedicated admission database required")
DATABASES = {"default": database_from_url(service_database)}
if DATABASES["default"]["USER"] != "agentledger_billing_admission":
    raise ImproperlyConfigured("Dedicated admission login required")
ALLOWED_HOSTS = env_list("BILLING_ADMISSION_ALLOWED_HOSTS")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Explicit admission hosts required")
BILLING_ADMISSION_WEBHOOK_SECRET = os.getenv("BILLING_ADMISSION_WEBHOOK_SECRET", "")
BILLING_ADMISSION_STRIPE_KEY = os.getenv("BILLING_ADMISSION_STRIPE_KEY", "")
BILLING_ADMISSION_ACCOUNT_ID = os.getenv("BILLING_ADMISSION_ACCOUNT_ID", "")
service_mode = os.getenv("BILLING_ADMISSION_MODE", "")
BILLING_ADMISSION_LIVEMODE = {"test": False, "live": True}.get(service_mode)
STRIPE_SECRET_KEY = ""
STRIPE_WEBHOOK_SECRET = ""
AUTOMATION_ENABLED = False
FOUNDER_OFFER_ENABLED = False
