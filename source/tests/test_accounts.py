from __future__ import annotations

from uuid import UUID

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction

pytestmark = pytest.mark.django_db


def test_user_identity_is_uuid_and_normalized():
    user = get_user_model().objects.create_user(
        "  OWNER@Example.COM  ",
        "correct horse battery staple",
    )

    assert isinstance(user.id, UUID)
    assert user.email == "owner@example.com"
    assert user.check_password("correct horse battery staple")


def test_authentication_matches_email_case_insensitively():
    get_user_model().objects.create_user("owner@example.com", "valid-password")

    user = authenticate(username="OWNER@EXAMPLE.COM", password="valid-password")

    assert user is not None
    assert user.email == "owner@example.com"


def test_email_identity_is_unique_case_insensitively():
    user_model = get_user_model()
    user_model.objects.create_user("owner@example.com", "valid-password")

    with pytest.raises(IntegrityError), transaction.atomic():
        user_model.objects.create(email="OWNER@EXAMPLE.COM")


def test_email_is_required():
    with pytest.raises(ValueError, match="email address is required"):
        get_user_model().objects.create_user("", "valid-password")


@pytest.mark.parametrize("field", ["is_staff", "is_superuser"])
def test_superuser_flags_fail_closed(field):
    with pytest.raises(ValueError, match=f"{field}=True"):
        get_user_model().objects.create_superuser(
            "admin@example.com",
            "valid-password",
            **{field: False},
        )
