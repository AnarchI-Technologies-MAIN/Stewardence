from __future__ import annotations

from django.db import connections

from agentledger.tenancy.context import identity_transaction


def create_owned_workspace(*, user_id, name: str, industry: str, using="default"):
    """Create a fresh workspace and fixed owner membership in one DB operation."""
    with identity_transaction(user_id, using=using):
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.create_owned_workspace(%s, %s)",
                [name, industry],
            )
            return cursor.fetchone()[0]
