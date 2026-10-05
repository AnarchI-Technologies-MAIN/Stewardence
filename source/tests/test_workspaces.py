from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.organizations.models import Organization, OrganizationMember
from tests.conftest import grant_core_entitlement

pytestmark = pytest.mark.django_db


def test_organization_enumerations_match_the_control_baseline():
    assert set(Organization.Industry.values) == {
        "accounting_bookkeeping",
        "legal",
        "healthcare",
        "construction",
        "agency",
        "other",
    }
    assert set(OrganizationMember.Role.values) == {
        "owner",
        "admin",
        "assessor",
        "viewer",
    }


@pytest.fixture
def isolation_fixture():
    user_model = get_user_model()
    user_a = user_model.objects.create_user("a@example.com", "valid-password")
    user_b = user_model.objects.create_user("b@example.com", "valid-password")
    firm_a = Organization.objects.create(
        name="Firm A",
        industry=Organization.Industry.ACCOUNTING_BOOKKEEPING,
    )
    firm_a_second = Organization.objects.create(name="Firm A Second")
    firm_b = Organization.objects.create(name="Firm B")
    OrganizationMember.objects.create(
        user=user_a,
        organization=firm_a,
        role=OrganizationMember.Role.OWNER,
    )
    OrganizationMember.objects.create(
        user=user_a,
        organization=firm_a_second,
        role=OrganizationMember.Role.ASSESSOR,
    )
    OrganizationMember.objects.create(
        user=user_b,
        organization=firm_b,
        role=OrganizationMember.Role.VIEWER,
    )

    grant_core_entitlement(user_a, firm_a)

    return user_a, user_b, firm_a, firm_a_second, firm_b


def test_login_requires_authentication_and_accepts_email(client, isolation_fixture):
    response = client.get(reverse("organizations:workspace-selection"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url

    response = client.post(
        reverse("accounts:login"),
        {"username": "A@EXAMPLE.COM", "password": "valid-password"},
    )
    assert response.status_code == 302
    assert response.url == reverse("organizations:workspace-selection")


def test_selection_lists_only_the_authenticated_users_firms(client, isolation_fixture):
    user_a, _user_b, _firm_a, _firm_a_second, _firm_b = isolation_fixture
    client.force_login(user_a)

    response = client.get(reverse("organizations:workspace-selection"))

    assert response.status_code == 200
    assert b"Firm A" in response.content
    assert b"Firm A Second" not in response.content
    assert b"Firm B" not in response.content


def test_user_cannot_activate_another_users_firm(client, isolation_fixture):
    user_a, _user_b, firm_a, _firm_a_second, firm_b = isolation_fixture
    client.force_login(user_a)
    session = client.session
    session["active_organization_id"] = str(firm_a.id)
    session.save()

    response = client.post(
        reverse("organizations:workspace-activate"),
        {"organization_id": str(firm_b.id)},
    )

    assert response.status_code == 403
    assert "active_organization_id" not in client.session


def test_malformed_workspace_id_is_denied_without_server_error(
    client, isolation_fixture
):
    user_a, *_ = isolation_fixture
    client.force_login(user_a)

    response = client.post(
        reverse("organizations:workspace-activate"),
        {"organization_id": "not-a-uuid"},
    )

    assert response.status_code == 403


def test_activation_is_post_only(client, isolation_fixture):
    user_a, _user_b, firm_a, *_ = isolation_fixture
    client.force_login(user_a)

    response = client.get(
        reverse("organizations:workspace-activate"),
        {"organization_id": str(firm_a.id)},
    )

    assert response.status_code == 405


def test_membership_in_second_firm_does_not_extend_core_subscription(
    client,
    isolation_fixture,
):
    user_a, _user_b, firm_a, firm_a_second, _firm_b = isolation_fixture
    client.force_login(user_a)

    first = client.post(
        reverse("organizations:workspace-activate"),
        {"organization_id": str(firm_a.id)},
    )

    assert first.status_code == 302
    assert client.session["active_organization_id"] == str(firm_a.id)

    second = client.post(
        reverse("organizations:workspace-activate"),
        {"organization_id": str(firm_a_second.id)},
    )

    assert second.status_code == 403
    assert "active_organization_id" not in client.session


def test_subscription_mismatched_session_tenant_is_cleared_before_resolution(
    client,
    isolation_fixture,
):
    user_a, _user_b, _firm_a, _firm_a_second, firm_b = isolation_fixture
    client.force_login(user_a)

    session = client.session
    session["active_organization_id"] = str(firm_b.id)
    session.save()

    response = client.get(
        reverse("organizations:workspace-selection")
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "organizations:workspace-selection"
    )
    assert "active_organization_id" not in client.session


def test_activation_requires_csrf(isolation_fixture):
    user_a, _user_b, firm_a, *_ = isolation_fixture
    client = Client(enforce_csrf_checks=True)
    client.force_login(user_a)

    response = client.post(
        reverse("organizations:workspace-activate"),
        {"organization_id": str(firm_a.id)},
    )

    assert response.status_code == 403


def test_logout_is_post_only_and_clears_workspace_session(client, isolation_fixture):
    user_a, _user_b, firm_a, *_ = isolation_fixture
    client.force_login(user_a)
    session = client.session
    session["active_organization_id"] = str(firm_a.id)
    session.save()

    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))

    assert response.status_code == 302
    assert "active_organization_id" not in client.session
    assert "_auth_user_id" not in client.session
