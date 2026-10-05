import os
import subprocess
import sys


def load_production_database_settings(worker_database_url):
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "agentledger.settings.production",
            "DJANGO_SECRET_KEY": (
                "Abcdefghijklmnopqrstuvwxyz0123456789-qualification-key"
            ),
            "DATABASE_URL": "postgresql://agentledger_app:local-only@database:5432/stewardence",
            "WORKER_DATABASE_URL": worker_database_url,
            "ALLOWED_HOSTS": "localhost",
            "CSRF_TRUSTED_ORIGINS": "https://localhost",
            "REPORTS_BUCKET_NAME": "qualification-only",
            "REPORTS_BUCKET_ENDPOINT": "https://storage.invalid",
            "REPORTS_BUCKET_ACCESS_KEY_ID": "local-only",
            "REPORTS_BUCKET_SECRET_ACCESS_KEY": "local-only",
            "REPORT_RENDERER_URL": "http://renderer:8080",
            "PYTHONPATH": os.pathsep.join(("src", environment.get("PYTHONPATH", ""))),
        }
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; "
            "print(settings.DATABASES.get('worker_runtime', {}).get("
            "'USER', 'missing'))",
        ],
        capture_output=True,
        check=False,
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        text=True,
        timeout=15,
    )


def test_production_maps_the_restricted_worker_database_alias():
    result = load_production_database_settings(
        "postgresql://agentledger_worker:local-only@database:5432/stewardence"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "agentledger_worker"


def test_production_rejects_the_web_role_for_worker_runtime():
    result = load_production_database_settings(
        "postgresql://agentledger_app:local-only@database:5432/stewardence"
    )

    assert result.returncode != 0
    assert "WORKER_DATABASE_URL must use the agentledger_worker role" in result.stderr


def test_production_rejects_a_worker_database_on_another_host():
    result = load_production_database_settings(
        "postgresql://agentledger_worker:local-only@separate-db:5432/stewardence"
    )

    assert result.returncode != 0
    assert "WORKER_DATABASE_URL must target the application database" in result.stderr
