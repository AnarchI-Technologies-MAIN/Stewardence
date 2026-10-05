from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from agentledger.tenancy.context import identity_transaction
from apps.accounts.models import User
from apps.billing.models import BillingCustomer, Subscription
from apps.organizations.models import Organization, OrganizationMember

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "extra", [{"website": "spam"}, {"password1": "12345678", "password2": "12345678"}]
)
def test_signup_rejects_bot_and_weak_password(client, extra):
    data = {
        "email": "reject@example.com",
        "password1": "RiverStone!Ledger7-MVP",
        "password2": "RiverStone!Ledger7-MVP",
    }
    data.update(extra)
    assert client.post(reverse("accounts:signup"), data).status_code == 200
    assert not User.objects.filter(email="reject@example.com").exists()


def test_signup_and_setup_require_csrf():
    client = Client(enforce_csrf_checks=True)
    assert client.post(reverse("accounts:signup"), {}).status_code == 403


def test_current_brand_is_visible_on_public_entry(client):
    for route in ("home", "accounts:login", "accounts:signup"):
        body = client.get(reverse(route)).content.decode()
        assert "Stewardence" in body
        assert "AgentLedger" not in body


def test_public_home_exposes_real_signup(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert "Create your workspace" in response.content.decode()


def test_public_signup_hashes_password_and_logs_user_in(client):
    raw_password = "RiverStone!Ledger7-MVP"

    response = client.post(
        reverse("accounts:signup"),
        {
            "first_name": "Avery",
            "last_name": "Morgan",
            "email": "Avery.Morgan@Example.COM",
            "password1": raw_password,
            "password2": raw_password,
            "website": "",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("billing:portfolio")

    user = User.objects.get(email="avery.morgan@example.com")

    assert user.password != raw_password
    assert user.check_password(raw_password)

    session = client.session
    assert str(session["_auth_user_id"]) == str(user.id)


def test_public_signup_rejects_case_insensitive_duplicate_email(client):
    User.objects.create_user(
        email="owner@example.com",
        password="Existing!Credential7",
    )

    response = client.post(
        reverse("accounts:signup"),
        {
            "first_name": "Other",
            "last_name": "Person",
            "email": "OWNER@EXAMPLE.COM",
            "password1": "RiverStone!Ledger7-MVP",
            "password2": "RiverStone!Ledger7-MVP",
            "website": "",
        },
    )

    assert response.status_code == 200
    assert User.objects.filter(email__iexact="owner@example.com").count() == 1

    assert "already exists" in response.content.decode().lower()


def test_signup_rejects_mismatched_passwords(client):
    response = client.post(
        reverse("accounts:signup"),
        {
            "first_name": "Avery",
            "last_name": "Morgan",
            "email": "avery@example.com",
            "password1": "RiverStone!Ledger7-MVP",
            "password2": "Different!Ledger8-MVP",
            "website": "",
        },
    )

    assert response.status_code == 200
    assert not User.objects.filter(email="avery@example.com").exists()


def test_guided_setup_creates_owner_membership_and_activates_workspace(client):
    user = User.objects.create_user(
        email="owner@example.com",
        password="Owner!Credential7",
    )

    client.force_login(user)
    billing_customer = BillingCustomer.objects.create(user=user)
    Subscription.objects.create(
        billing_customer=billing_customer,
        portfolio=Subscription.Portfolio.CORE,
        status=Subscription.Status.ACTIVE,
        current_price_cents=9900,
    )

    details_response = client.post(
        reverse("organizations:setup"),
        {
            "name": "Northstar Advisory",
            "industry": Organization.Industry.ACCOUNTING_BOOKKEEPING,
        },
    )

    assert details_response.status_code == 302
    assert details_response.url == reverse("organizations:setup-start")

    start_response = client.post(
        reverse("organizations:setup-start"),
        {
            "start_choice": "explore",
        },
    )

    assert start_response.status_code == 302
    assert start_response.url == reverse("organizations:setup-review")

    review_response = client.post(
        reverse("organizations:setup-review"),
    )

    assert review_response.status_code == 302
    assert review_response.url == reverse("organizations:workspace-selection")

    with identity_transaction(user.id):
        organization = Organization.objects.get(name="Northstar Advisory")

        membership = OrganizationMember.objects.get(
            organization=organization,
            user=user,
        )

    assert membership.role == OrganizationMember.Role.OWNER
    assert client.session["active_organization_id"] == str(organization.id)


def test_guided_setup_import_choice_routes_to_real_import_flow(client):
    user = User.objects.create_user(
        email="importer@example.com",
        password="Importer!Credential7",
    )

    billing_customer = BillingCustomer.objects.create(user=user)
    Subscription.objects.create(
        billing_customer=billing_customer,
        portfolio=Subscription.Portfolio.CORE,
        status=Subscription.Status.ACTIVE,
        current_price_cents=9900,
    )

    client.force_login(user)

    client.post(
        reverse("organizations:setup"),
        {
            "name": "Import Test Firm",
            "industry": Organization.Industry.OTHER,
        },
    )

    client.post(
        reverse("organizations:setup-start"),
        {
            "start_choice": "import_csv",
        },
    )

    response = client.post(
        reverse("organizations:setup-review"),
    )

    assert response.status_code == 302
    assert response.url == reverse("imports:upload")


def test_guided_setup_manual_choice_routes_to_real_inventory(client):
    user = User.objects.create_user(
        email="manual@example.com",
        password="Manual!Credential7",
    )

    billing_customer = BillingCustomer.objects.create(user=user)
    Subscription.objects.create(
        billing_customer=billing_customer,
        portfolio=Subscription.Portfolio.CORE,
        status=Subscription.Status.ACTIVE,
        current_price_cents=9900,
    )

    client.force_login(user)

    client.post(
        reverse("organizations:setup"),
        {
            "name": "Manual Test Firm",
            "industry": Organization.Industry.OTHER,
        },
    )

    client.post(
        reverse("organizations:setup-start"),
        {
            "start_choice": "manual",
        },
    )

    response = client.post(
        reverse("organizations:setup-review"),
    )

    assert response.status_code == 302
    assert response.url == reverse("inventory:list")
