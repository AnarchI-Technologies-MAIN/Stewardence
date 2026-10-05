"""Explicit-only 50x proposal PK wait and authority discrimination campaign."""

import pytest
import test_capture_proposal_pk_wait_authority as wait_probe

pytest_plugins = ["test_capture_admission"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.mark.parametrize("iteration", range(50))
def test_waiting_target_admits_once_when_authority_remains_valid(
    capture_context, settings, iteration
):
    wait_probe.test_chosen_revision_pk_wait_rechecks_paid_authority_after_foreign_rollback(
        capture_context,
        settings,
        revoke_authority=False,
        iteration=iteration,
        diagnostic=True,
    )


@pytest.mark.parametrize("iteration", range(50))
def test_waiting_target_denies_without_effects_after_authority_revocation(
    capture_context, settings, iteration
):
    wait_probe.test_chosen_revision_pk_wait_rechecks_paid_authority_after_foreign_rollback(
        capture_context,
        settings,
        revoke_authority=True,
        iteration=iteration,
        diagnostic=True,
    )
