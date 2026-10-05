from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.db import connection, transaction

from agentledger.tenancy.context import (
    _set_local_context,
    activate_tenant,
    identity_transaction,
    tenant_transaction,
)

pytestmark = pytest.mark.django_db(transaction=True)


def current_setting(name: str):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [name])
        return cursor.fetchone()[0]


def test_identity_context_is_transaction_local():
    user_id = uuid4()

    with identity_transaction(user_id):
        assert current_setting("app.current_user_id") == str(user_id)

    assert current_setting("app.current_user_id") in (None, "")


def test_tenant_context_is_transaction_local():
    organization_id = uuid4()

    with tenant_transaction(organization_id):
        assert current_setting("app.current_organization_id") == str(organization_id)

    assert current_setting("app.current_organization_id") in (None, "")


def test_tenant_activation_requires_explicit_transaction():
    with pytest.raises(RuntimeError, match="explicit transaction"):
        activate_tenant(uuid4())


def test_context_rejects_non_uuid_value():
    with transaction.atomic(), pytest.raises(ValueError):
        activate_tenant("not-a-uuid")


def test_context_name_is_allowlisted():
    with transaction.atomic(), pytest.raises(ValueError, match="Unsupported"):
        _set_local_context("app.untrusted_context", uuid4(), using="default")


def test_identity_context_uses_the_selected_database_alias():
    connection_for_alias = MagicMock(in_atomic_block=True)
    cursor = connection_for_alias.cursor.return_value.__enter__.return_value

    with (
        patch("agentledger.tenancy.context.connections") as connections,
        patch("agentledger.tenancy.context.transaction.atomic") as atomic,
    ):
        connections.__getitem__.return_value = connection_for_alias
        with identity_transaction(uuid4(), using="app_runtime"):
            pass

    atomic.assert_called_once_with(using="app_runtime")
    connections.__getitem__.assert_called_once_with("app_runtime")
    assert cursor.execute.call_args.args[0] == "SELECT set_config(%s, %s, true)"
