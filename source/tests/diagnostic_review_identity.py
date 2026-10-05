"""Explicit-only disposable SQL diagnostic; never default-suite collection.

Run this file by its exact path to reproduce clock discontinuities. It temporarily
instruments the disposable issuer and always restores definition and privileges.
Canonical source and production SQL are never changed.
"""

import pytest
import test_review_workspace_views as ui
from django.db import connections
from review_identity_diagnostics import instrumented_issuer

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def workspace(report_context, settings, client, monkeypatch):
    with instrumented_issuer(connections["default"]) as mode:
        yield ui.workspace.__wrapped__(
            report_context, settings, client, monkeypatch, _identity_mode=mode
        )


def test_instrumented_exact_rollback_fixture(workspace, client, monkeypatch):
    ui.test_database_denial_rolls_back_open_cycle_before_safe_response(
        workspace, client, monkeypatch
    )


@pytest.mark.parametrize("diagnostic_repeat", range(8))
def test_instrumented_repeated_proposal_identity_inputs(
    workspace, client, diagnostic_repeat
):
    ui.test_repeated_synthetic_proposal_inputs_preserve_all_sql_identity_predicates(
        workspace, client, diagnostic_repeat=diagnostic_repeat
    )
