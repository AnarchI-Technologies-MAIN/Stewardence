from __future__ import annotations

import os


def bounded_integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


port = bounded_integer("PORT", 8000, 1, 65535)

bind = f"0.0.0.0:{port}"
worker_class = "gthread"
workers = bounded_integer("WEB_CONCURRENCY", 1, 1, 8)
threads = bounded_integer("GUNICORN_THREADS", 4, 1, 16)
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1_000
max_requests_jitter = 100
preload_app = True
worker_tmp_dir = "/dev/shm"  # noqa: S108 - container-owned memory filesystem.
accesslog = "-"
errorlog = "-"
capture_output = True

# Deliberately excludes query strings, headers, cookies, referrers,
# and request bodies from production request logs.
access_log_format = '%(t)s %(p)s "%(m)s %(U)s %(H)s" %(s)s %(B)s %(D)s'
