from __future__ import annotations

import logging

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def healthz(request):
    return JsonResponse({"status": "ok"})


@require_GET
def readyz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            return JsonResponse({"status": "not_ready"}, status=503)
    except Exception:
        logger.exception("Readiness check failed")
        return JsonResponse({"status": "not_ready"}, status=503)
    return JsonResponse({"status": "ready"})
