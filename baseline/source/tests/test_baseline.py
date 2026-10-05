from __future__ import annotations

import os
import runpy
import subprocess
import sys
from unittest.mock import patch

from django.test import SimpleTestCase

from agentledger.settings.base import database_from_url


class BaselineTests(SimpleTestCase):
    databases = set()

    def test_healthz_is_tenant_independent(self):
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @patch("agentledger.health.MigrationExecutor")
    @patch("agentledger.health.connection")
    def test_readyz_checks_database_and_migrations(self, connection, executor_class):
        cursor = connection.cursor
        cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        executor = executor_class.return_value
        executor.loader.graph.leaf_nodes.return_value = ["leaf"]
        executor.migration_plan.return_value = []

        response = self.client.get("/readyz")

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            "SELECT 1"
        )

    @patch("agentledger.health.MigrationExecutor")
    @patch("agentledger.health.connection")
    def test_readyz_fails_closed_for_pending_migrations(
        self, connection, executor_class
    ):
        cursor = connection.cursor
        cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        executor = executor_class.return_value
        executor.loader.graph.leaf_nodes.return_value = ["leaf"]
        executor.migration_plan.return_value = ["pending"]

        response = self.client.get("/readyz")

        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}

    @patch("agentledger.health.connection")
    def test_readyz_fails_closed_without_leaking_database_error(self, connection):
        connection.cursor.side_effect = RuntimeError("offline")
        response = self.client.get("/readyz")

        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}

    def test_database_url_requires_postgresql(self):
        with self.assertRaisesRegex(ValueError, "postgresql scheme"):
            database_from_url("sqlite:///tmp/agentledger.db")

    def test_database_url_preserves_connection_fields(self):
        result = database_from_url(
            "postgresql://ledger%2Dapp:p%40ss@db.internal:5433/ledger%2Dprod"
        )
        assert result["ENGINE"] == "django.db.backends.postgresql"
        assert result["NAME"] == "ledger-prod"
        assert result["USER"] == "ledger-app"
        assert result["PASSWORD"] == "p@ss"
        assert result["HOST"] == "db.internal"
        assert result["PORT"] == 5433

    def test_production_settings_import_with_explicit_configuration(self):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SECRET_KEY": "phase19-test-" + ("S3cur3!" * 8),
                "DATABASE_URL": "postgresql://app:secret@db.internal/agentledger",
                "ALLOWED_HOSTS": "agentledger.example",
                "CSRF_TRUSTED_ORIGINS": "https://agentledger.example",
                "REPORTS_BUCKET_NAME": "agentledger-test-reports",
                "REPORTS_BUCKET_ENDPOINT": "https://storage.railway.app",
                "REPORTS_BUCKET_ACCESS_KEY_ID": "test-access-key",
                "REPORTS_BUCKET_SECRET_ACCESS_KEY": "test-secret-key",
                "REPORTS_BUCKET_REGION": "auto",
                "REPORTS_BUCKET_URL_STYLE": "virtual",
                "REPORT_RENDERER_URL": "http://renderer:8080",
                "PYTHONPATH": os.pathsep.join(["src", "."]),
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "os.environ['DJANGO_SETTINGS_MODULE']="
                    "'agentledger.settings.production'; "
                    "import django; django.setup()"
                ),
            ],
            cwd=os.getcwd(),
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr

    def test_production_settings_reject_wildcard_host(self):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SECRET_KEY": "phase19-test-" + ("S3cur3!" * 8),
                "DATABASE_URL": "postgresql://app:secret@db.internal/agentledger",
                "ALLOWED_HOSTS": "*",
                "CSRF_TRUSTED_ORIGINS": "https://agentledger.example",
                "PYTHONPATH": os.pathsep.join(["src", "."]),
            }
        )
        completed = subprocess.run(
            [sys.executable, "-c", "import agentledger.settings.production"],
            cwd=os.getcwd(),
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode != 0
        assert "Wildcard ALLOWED_HOSTS is forbidden" in completed.stderr

    @patch.dict(os.environ, {"PORT": "9123"})
    def test_gunicorn_uses_railway_port(self):
        configuration = runpy.run_path("src/agentledger/gunicorn.conf.py")

        assert configuration["bind"] == "0.0.0.0:9123"

    @patch.dict(
        os.environ,
        {"WEB_CONCURRENCY": "2", "GUNICORN_THREADS": "6"},
    )
    def test_gunicorn_concurrency_is_explicitly_bounded(self):
        configuration = runpy.run_path("src/agentledger/gunicorn.conf.py")

        assert configuration["worker_class"] == "gthread"
        assert configuration["workers"] == 2
        assert configuration["threads"] == 6
        assert configuration["max_requests"] == 1_000
        assert configuration["worker_tmp_dir"] == "/dev/shm"  # noqa: S108

    @patch.dict(os.environ, {"GUNICORN_THREADS": "17"})
    def test_gunicorn_rejects_unbounded_thread_configuration(self):
        with self.assertRaisesRegex(
            ValueError,
            "GUNICORN_THREADS must be between 1 and 16",
        ):
            runpy.run_path("src/agentledger/gunicorn.conf.py")
