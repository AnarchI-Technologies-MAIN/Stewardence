from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.audit.verification import verify_tenant_audit_history


class Command(BaseCommand):
    help = "Verify one tenant's tamper-evident audit chain."

    def add_arguments(self, parser):
        parser.add_argument("organization_id", type=uuid.UUID)
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        try:
            result = verify_tenant_audit_history(
                options["organization_id"],
                using=options["database"],
            )
        except KeyError as error:
            raise CommandError("Unknown database alias") from error

        self.stdout.write(result.status.value)
        self.stdout.write(
            f"blocks={result.blocks_checked} events={result.events_checked}"
        )
        self.stdout.write(result.reason)
