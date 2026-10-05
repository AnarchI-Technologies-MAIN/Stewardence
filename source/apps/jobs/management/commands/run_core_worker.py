from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.jobs.handlers import build_job_handler_resolver
from apps.jobs.worker import drain_queue


class Command(BaseCommand):
    help = (
        "Drain a bounded deterministic Core queue batch, without LISTEN "
        "or provider access."
    )

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", required=True)
        parser.add_argument("--max-jobs", type=int, default=10)

    def handle(self, *args, **options):
        if not getattr(settings, "CORE_WORKFLOWS_ENABLED", False):
            raise CommandError("Core scheduled execution is disabled")
        if not 1 <= options["max_jobs"] <= 25:
            raise CommandError("Core batches require 1 to 25 jobs")
        if "worker_runtime" not in connections.databases:
            raise CommandError("WORKER_DATABASE_URL is required for Core execution")
        resolver = build_job_handler_resolver(using="worker_runtime")
        processed = drain_queue(
            options["worker_id"],
            resolver,
            using="worker_runtime",
            max_jobs=options["max_jobs"],
        )
        self.stdout.write(f"Core completed batch: {processed} processed jobs")
