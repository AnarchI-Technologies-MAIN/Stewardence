from __future__ import annotations

import os
from functools import partial

from django.core.management.base import BaseCommand, CommandError

from apps.jobs.handlers import build_job_handler_resolver
from apps.jobs.listener import EventDrivenJobListener
from apps.jobs.worker import drain_queue


class Command(BaseCommand):
    help = "Run the event-driven AgentLedger background-job worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker-id",
            help=(
                "Stable worker identity. Defaults to Railway's per-replica "
                "RAILWAY_REPLICA_ID."
            ),
        )

    def handle(self, *args, **options):
        del args

        worker_id = options.get("worker_id") or os.getenv("RAILWAY_REPLICA_ID", "")
        if not worker_id:
            raise CommandError(
                "A worker identity is required via --worker-id or RAILWAY_REPLICA_ID."
            )

        listener_dsn = os.getenv("DATABASE_URL", "")
        if not listener_dsn:
            raise CommandError("DATABASE_URL is required to run the worker.")

        resolver = build_job_handler_resolver(using="default")
        listener = EventDrivenJobListener(
            worker_id=worker_id,
            listener_dsn=listener_dsn,
        )
        listener.run(
            partial(
                drain_queue,
                handler_resolver=resolver,
                using="default",
            )
        )
