"""Payment admission is trusted ingestion; PostgreSQL does not verify Stripe.

The separately credentialed ingester must authenticate provider evidence and
validate the supported contract before calling the narrow issuer. Ordinary app
and worker connections cannot issue coverage. Account pinning and clock checks
are enforced again by the database. No historical payment is synthesized here.
"""

import json

from django.db import connections


def issue_paid_coverage(evidence, *, using="billing_admission"):
    """Issue one already-verified evidence envelope; return its receipt UUID.

An independent admission connection does not share an app transaction. Callers
must use a durable staged workflow or an admission-owned transaction; do not
claim atomicity across two connections.
"""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT app_private.issue_paid_coverage(%s::jsonb)", [json.dumps(evidence, allow_nan=False)])
        return cursor.fetchone()[0]


def paid_subscription_access(subscription_id, *, using="default"):
    """Check issued current coverage using database time and caller visibility."""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT app_private.paid_subscription_access(%s)", [subscription_id])
        return bool(cursor.fetchone()[0])


def paid_subscription_export_access(subscription_id, *, using="default"):
    """Read/export eligibility only; never authorizes additional paid work."""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT app_private.paid_subscription_export_access(%s)", [subscription_id])
        return bool(cursor.fetchone()[0])
