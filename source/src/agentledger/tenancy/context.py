from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from django.db import connections, transaction

USER_CONTEXT = "app.current_user_id"
TENANT_CONTEXT = "app.current_organization_id"
_ALLOWED_CONTEXTS = frozenset({USER_CONTEXT, TENANT_CONTEXT})
_ISOLATION_SQL = {
    "repeatable_read": ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"),
}


def _uuid_text(value: Any) -> str:
    return str(UUID(str(value)))


def _set_local_context(name: str, value: Any, *, using: str) -> None:
    if name not in _ALLOWED_CONTEXTS:
        raise ValueError("Unsupported AgentLedger database context")

    connection = connections[using]
    if not connection.in_atomic_block:
        raise RuntimeError(
            "Database security context must be set inside an explicit transaction."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config(%s, %s, true)",
            [name, _uuid_text(value)],
        )


@contextmanager
def identity_transaction(
    user_id: Any,
    *,
    using: str = "default",
) -> Iterator[None]:
    with transaction.atomic(using=using):
        _set_local_context(USER_CONTEXT, user_id, using=using)
        yield


def activate_tenant(
    organization_id: Any,
    *,
    using: str = "default",
) -> None:
    _set_local_context(TENANT_CONTEXT, organization_id, using=using)


@contextmanager
def tenant_transaction(
    organization_id: Any,
    *,
    using: str = "default",
    isolation: str | None = None,
) -> Iterator[None]:
    with transaction.atomic(using=using):
        if isolation is not None:
            try:
                isolation_sql = _ISOLATION_SQL[isolation]
            except KeyError as error:
                raise ValueError("Unsupported transaction isolation level") from error

            with connections[using].cursor() as cursor:
                cursor.execute(isolation_sql)

        activate_tenant(organization_id, using=using)
        yield
