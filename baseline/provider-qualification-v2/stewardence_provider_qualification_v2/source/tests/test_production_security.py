from __future__ import annotations

import os
import runpy
import subprocess
import sys

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from agentledger import health


def production_environment(**overrides):
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "agentledger.settings.production",
            "DJANGO_SECRET_KEY": "phase19-test-" + ("S3cur3!" * 8),
            "DATABASE_URL": ("postgresql://app:phase19-test@db.internal/agentledger"),
            "ALLOWED_HOSTS": (
                "agentledger.example,agentledger-production.up.railway.app"
            ),
            "CSRF_TRUSTED_ORIGINS": (
                "https://agentledger.example,"
                "https://agentledger-production.up.railway.app"
            ),
            "REPORTS_BUCKET_NAME": "phase19-test-reports",
            "REPORTS_BUCKET_ENDPOINT": "https://storage.railway.app",
            "REPORTS_BUCKET_ACCESS_KEY_ID": "phase19-test-access",
            "REPORTS_BUCKET_SECRET_ACCESS_KEY": "phase19-test-secret",
            "REPORTS_BUCKET_REGION": "auto",
            "REPORTS_BUCKET_URL_STYLE": "virtual",
            "REPORT_RENDERER_URL": "http://renderer:8080",
            "PYTHONPATH": os.pathsep.join(["src", "."]),
        }
    )
    environment.update(overrides)
    return environment


def import_production_settings(environment):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; "
                "os.environ['DJANGO_SETTINGS_MODULE']="
                "'agentledger.settings.production'; "
                "import django; django.setup(); "
                "from django.conf import settings; "
                "print(repr(settings.ALLOWED_HOSTS)); "
                "print(repr(settings.CSRF_TRUSTED_ORIGINS))"
            ),
        ],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


def test_production_security_settings_are_explicit_and_hardened():
    completed = import_production_settings(production_environment())

    assert completed.returncode == 0, completed.stderr
    assert "agentledger.example" in completed.stdout
    assert "agentledger-production.up.railway.app" in completed.stdout
    assert "healthcheck.railway.app" in completed.stdout
    assert "https://agentledger.example" in completed.stdout
    assert "https://agentledger-production.up.railway.app" in completed.stdout


def test_production_collectstatic_serves_the_branded_login_without_database(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, re; import django; django.setup(); "
            "from django.conf import settings; "
            "settings.STATIC_ROOT = sys.argv[1]; "
            "from django.core.management import call_command; "
            "call_command('collectstatic', interactive=False, verbosity=0); "
            "from django.test import Client; client = Client(); "
            "page = client.get('/accounts/login/', secure=True, "
            "HTTP_HOST='agentledger.example'); "
            "assert page.status_code == 200; "
            "html = page.content.decode(); assert 'Stewardence' in html; "
            r"asset = re.search(r'/static/agentledger\.[a-f0-9]+\.css', html).group(); "
            "css = client.get(asset, secure=True, HTTP_HOST='agentledger.example'); "
            "assert css.status_code == 200; "
            "assert css['Content-Type'].startswith('text/css'); "
            "assert b'--ink-950' in b''.join(css.streaming_content)",
            str(tmp_path / "static"),
        ],
        env=production_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "weak_secret",
    [
        "short",
        "s" * 64,
        "django-insecure-" + ("xY7!" * 16),
    ],
)
def test_production_rejects_weak_secret_keys(weak_secret):
    completed = import_production_settings(
        production_environment(
            DJANGO_SECRET_KEY=weak_secret,
        )
    )

    assert completed.returncode != 0
    assert "strong production secret" in completed.stderr


@pytest.mark.parametrize(
    "origin",
    [
        "http://agentledger.example",
        "https://*.example.com",
        "https://",
    ],
)
def test_production_rejects_non_explicit_or_insecure_csrf_origins(origin):
    completed = import_production_settings(
        production_environment(
            CSRF_TRUSTED_ORIGINS=origin,
        )
    )

    assert completed.returncode != 0
    assert (
        "CSRF_TRUSTED_ORIGINS must contain explicit HTTPS origins" in completed.stderr
    )


def test_production_rejects_wildcard_allowed_hosts():
    completed = import_production_settings(
        production_environment(
            ALLOWED_HOSTS="*",
        )
    )

    assert completed.returncode != 0
    assert "Wildcard ALLOWED_HOSTS is forbidden" in completed.stderr


def test_gunicorn_access_log_format_omits_secret_bearing_request_atoms():
    configuration = runpy.run_path("src/agentledger/gunicorn.conf.py")

    access_format = configuration["access_log_format"]

    assert "%(m)s" in access_format
    assert "%(U)s" in access_format
    assert "%(s)s" in access_format

    assert "%(q)s" not in access_format
    assert "%(r)s" not in access_format
    assert "%(f)s" not in access_format
    assert "}i" not in access_format
    assert "}e" not in access_format


@pytest.mark.django_db
def test_health_endpoints_bypass_stale_tenant_session():
    user = get_user_model().objects.create_user(
        "phase19-health@example.com",
        "valid-password",
    )

    client = Client()
    client.force_login(user)

    session = client.session
    session["active_organization_id"] = "not-a-valid-uuid"
    session.save()

    health_response = client.get("/healthz")
    ready_response = client.get("/readyz")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready"}


@pytest.mark.django_db
def test_readyz_returns_503_when_database_is_unavailable(monkeypatch):
    def unavailable_cursor():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        health.connection,
        "cursor",
        unavailable_cursor,
    )

    response = Client().get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


@pytest.mark.django_db
def test_readyz_returns_503_when_migrations_are_pending(monkeypatch):
    class PendingMigrationExecutor:
        def __init__(self, connection):
            self.loader = self
            self.graph = self

        def leaf_nodes(self):
            return [("example", "0002_pending")]

        def migration_plan(self, leaf_nodes):
            return [("pending", False)]

    monkeypatch.setattr(
        health,
        "MigrationExecutor",
        PendingMigrationExecutor,
    )

    response = Client().get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_production_hsts_is_deliberate_initial_ramp_up():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; "
                "os.environ['DJANGO_SETTINGS_MODULE']="
                "'agentledger.settings.production'; "
                "import django; django.setup(); "
                "from django.conf import settings; "
                "assert settings.DEBUG is False; "
                "assert settings.SECURE_SSL_REDIRECT is True; "
                "assert settings.SECURE_REDIRECT_EXEMPT == "
                "['^healthz$', '^readyz$']; "
                "assert settings.SESSION_COOKIE_SECURE is True; "
                "assert settings.CSRF_COOKIE_SECURE is True; "
                "assert settings.SECURE_HSTS_SECONDS == 3600; "
                "assert settings.SECURE_HSTS_INCLUDE_SUBDOMAINS is True; "
                "assert settings.SECURE_HSTS_PRELOAD is False; "
                "assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True; "
                "assert settings.X_FRAME_OPTIONS == 'DENY'; "
                "assert settings.STATIC_URL == '/static/'; "
                "assert settings.MIDDLEWARE[1] == "
                "'whitenoise.middleware.WhiteNoiseMiddleware'; "
                "assert settings.STORAGES['staticfiles']['BACKEND'] == "
                "'whitenoise.storage.CompressedManifestStaticFilesStorage'; "
                "assert settings.SECURE_PROXY_SSL_HEADER == "
                "('HTTP_X_FORWARDED_PROTO', 'https')"
            ),
        ],
        cwd=os.getcwd(),
        env=production_environment(),
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
