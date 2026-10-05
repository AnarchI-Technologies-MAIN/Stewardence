"""Local lifecycle tests only; does NOT qualify PostgreSQL grants or RLS."""

from agentledger.settings.development import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
# Populate local app labels explicitly; PostgreSQL migrations run in DO harness.
MIGRATION_MODULES = {
    label: None
    for label in (
        "auth",
        "contenttypes",
        "sessions",
        "accounts",
        "billing",
        "organizations",
        "inventory",
        "catalog",
        "imports",
        "policies",
        "assessments",
        "jobs",
        "audit",
        "reports",
        "integrations",
    )
}
