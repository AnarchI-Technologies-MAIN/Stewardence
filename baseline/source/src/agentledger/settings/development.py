import os

from .base import *  # noqa: F403
from .base import database_from_url

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

for alias, environment_name in (
    ("owner_runtime", "OWNER_DATABASE_URL"),
    ("app_runtime", "APP_DATABASE_URL"),
    ("worker_runtime", "WORKER_DATABASE_URL"),
):
    database_url = os.getenv(environment_name)
    if database_url:
        DATABASES[alias] = database_from_url(database_url)
        DATABASES[alias]["TEST"] = {"MIRROR": "default"}

REPORTS_LOCAL_STORAGE_ROOT = BASE_DIR / ".private-reports"

REPORTS_STORAGE_BACKEND = "local"
