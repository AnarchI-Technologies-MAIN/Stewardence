import pytest
from django.db import DatabaseError, transaction
from django.test import Client
from django.urls import reverse
from apps.organizations.models import WorkflowProfile

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def test_owner_records_profile_once_and_malicious_fields_cannot_reinterpret_it(client, report_context):
    user, organization, _, _, _ = report_context
    url = reverse("organizations:workflow-profile")
    response = client.post(url, {"profile":"business.v1", "name":"Chicago", "jurisdiction":"US-IL",
        "created_by":"forged", "organization":"forged"})
    assert response.status_code == 302
    profile = WorkflowProfile.objects.get(organization=organization)
    assert profile.created_by_id == user.id
    assert profile.settings == {"name":"Chicago", "jurisdiction":"US-IL"}
    assert client.post(url, {"profile":"development.v1", "name":"main"}).status_code == 403
    with pytest.raises(DatabaseError), transaction.atomic():
        WorkflowProfile.objects.filter(id=profile.id).update(profile="development.v1")
    with pytest.raises(DatabaseError), transaction.atomic():
        WorkflowProfile.objects.filter(id=profile.id).delete()


def test_cross_profile_settings_fail_and_viewers_cannot_decide(client, report_context):
    _, _, membership, _, _ = report_context
    url = reverse("organizations:workflow-profile")
    assert client.post(url, {"profile":"business.v1", "name":"Chicago", "repository_ref":"firm/repo"}).status_code == 200
    assert not WorkflowProfile.objects.exists()
    membership.role = "viewer"
    membership.save(update_fields=["role"])
    assert client.get(url).status_code == 403
    assert client.post(url, {"profile":"business.v1", "name":"Chicago"}).status_code == 403


def test_profile_setup_requires_csrf(client, report_context):
    protected = Client(enforce_csrf_checks=True)
    protected.cookies = client.cookies.copy()
    assert protected.post(reverse("organizations:workflow-profile"), {"profile":"business.v1", "name":"Chicago"}).status_code == 403
    assert not WorkflowProfile.objects.exists()


def test_real_application_role_cannot_spoof_profile_actor(report_context):
    from agentledger.tenancy.context import identity_transaction, tenant_transaction
    from django.contrib.auth import get_user_model
    user, organization, _, _, _ = report_context
    forged_actor = get_user_model().objects.create_user("forged-profile-actor@example.invalid")
    with identity_transaction(user.id, using="app_runtime"), tenant_transaction(organization.id, using="app_runtime"):
        with pytest.raises(DatabaseError), transaction.atomic(using="app_runtime"):
            WorkflowProfile.objects.using("app_runtime").create(organization=organization,
                created_by=forged_actor, profile="business.v1", settings={"name":"Chicago"})
        record = WorkflowProfile.objects.using("app_runtime").create(organization=organization,
            created_by=user, profile="business.v1", settings={"name":"Chicago"})
        assert record.created_by_id == user.id
